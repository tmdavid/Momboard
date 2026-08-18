"""T43: Segment lenses — compare two filter sets, themes + contradictions."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    Conversation,
    Highlight,
)

logger = logging.getLogger(__name__)

MIN_HIGHLIGHTS_PER_SIDE = 5


class InsufficientEvidenceError(Exception):
    """Raised when a side has fewer highlights than the minimum."""

    def __init__(self, side: str, count: int):
        self.side = side
        self.count = count
        super().__init__(
            f"Not enough evidence on side {side} ({count} highlights, need {MIN_HIGHLIGHTS_PER_SIDE})"
        )


async def _get_highlights_for_filters(
    db: AsyncSession,
    filters: dict[str, Any],
    *,
    limit: int = 100,
) -> list[Highlight]:
    """Retrieve accepted highlights matching filter set (excluding simulated).

    Filter grammar:
    - tag_key: str (single tag) or list[str] — OR match against any given tag.
      Comma-separated strings are also parsed safely.
    - company_id: int — filter by conversation company
    - status: str — filter highlight status ('accepted' or 'suggested'); defaults
      to both when absent
    - date_from / date_to: datetime filters on conversation.happened_at
    - contact_id: int — filter to conversations linked to this contact
    """
    query = (
        select(Highlight)
        .join(Conversation, Conversation.id == Highlight.conversation_id)
        .where(
            Conversation.source != "simulator",
        )
    )

    # Status filter (default: accepted + suggested)
    if "status" in filters and filters["status"]:
        status_val = filters["status"]
        if isinstance(status_val, list):
            query = query.where(Highlight.status.in_(status_val))
        else:
            query = query.where(Highlight.status == status_val)
    else:
        query = query.where(Highlight.status.in_(["accepted", "suggested"]))

    if "company_id" in filters:
        query = query.where(Conversation.company_id == filters["company_id"])

    # tag_key: support list, single string, or comma-separated string
    if "tag_key" in filters and filters["tag_key"]:
        tag_val = filters["tag_key"]
        if isinstance(tag_val, list):
            tag_keys = tag_val
        elif isinstance(tag_val, str) and "," in tag_val:
            tag_keys = [t.strip() for t in tag_val.split(",") if t.strip()]
        else:
            tag_keys = [tag_val]
        query = query.where(Highlight.tag_key.in_(tag_keys))

    if "date_from" in filters:
        query = query.where(Conversation.happened_at >= filters["date_from"])
    if "date_to" in filters:
        query = query.where(Conversation.happened_at <= filters["date_to"])
    if "contact_id" in filters:
        from app.models import ConversationContact

        convo_ids_sub = (
            select(ConversationContact.conversation_id)
            .where(ConversationContact.contact_id == filters["contact_id"])
        )
        query = query.where(Highlight.conversation_id.in_(convo_ids_sub))

    query = query.order_by(Highlight.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def build_lens(
    db: AsyncSession,
    *,
    filters_a: dict[str, Any],
    filters_b: dict[str, Any],
    label_a: str = "Side A",
    label_b: str = "Side B",
    llm: Any,
) -> Analysis:
    """Build a segment lens comparing two filter sets.

    Partition candidates by side, prompt LLM for per-side attribution,
    validate partition claims in code.

    Raises InsufficientEvidenceError if either side has <5 highlights.
    """
    from app.llm.schemas import LensOutput

    # Retrieve candidates for each side
    highlights_a = await _get_highlights_for_filters(db, filters_a)
    highlights_b = await _get_highlights_for_filters(db, filters_b)

    if len(highlights_a) < MIN_HIGHLIGHTS_PER_SIDE:
        raise InsufficientEvidenceError("A", len(highlights_a))
    if len(highlights_b) < MIN_HIGHLIGHTS_PER_SIDE:
        raise InsufficientEvidenceError("B", len(highlights_b))

    ids_a = {h.id for h in highlights_a}
    ids_b = {h.id for h in highlights_b}

    # Build prompt
    data_a = [{"id": h.id, "tag": h.tag_key, "quote": h.quote} for h in highlights_a[:40]]
    data_b = [{"id": h.id, "tag": h.tag_key, "quote": h.quote} for h in highlights_b[:40]]

    prompt = (
        "You are comparing two customer segments. Identify:\n"
        "1. themes_a: themes unique to Side A\n"
        "2. themes_b: themes unique to Side B\n"
        "3. themes_shared: themes present in both sides\n"
        "4. contradictions: direct contradictions between the sides\n\n"
        "RULES:\n"
        "- Every theme must cite evidence_highlight_ids\n"
        "- Side A IDs must come from the Side A evidence only\n"
        "- Side B IDs must come from the Side B evidence only\n"
        "- Shared themes can cite IDs from either side\n"
        "- Contradictions must cite IDs from both sides\n\n"
        f"SIDE A ({label_a}):\n{data_a}\n\n"
        f"SIDE B ({label_b}):\n{data_b}"
    )

    lens_output = await llm.generate(
        prompt=prompt,
        schema=LensOutput,
        model="lens",
    )

    # Validate partition claims: Side A themes must only cite Side A IDs, etc.
    for theme in lens_output.themes_a:
        theme.evidence_highlight_ids = [
            hid for hid in theme.evidence_highlight_ids if hid in ids_a
        ]
        theme.side = "a"

    for theme in lens_output.themes_b:
        theme.evidence_highlight_ids = [
            hid for hid in theme.evidence_highlight_ids if hid in ids_b
        ]
        theme.side = "b"

    all_ids = ids_a | ids_b
    for theme in lens_output.themes_shared:
        theme.evidence_highlight_ids = [
            hid for hid in theme.evidence_highlight_ids if hid in all_ids
        ]
        theme.side = "both"

    for theme in lens_output.contradictions:
        theme.evidence_highlight_ids = [
            hid for hid in theme.evidence_highlight_ids if hid in all_ids
        ]
        theme.side = "contradiction"
        # Validate contradiction has at least one ID from each side
        has_a = any(hid in ids_a for hid in theme.evidence_highlight_ids)
        has_b = any(hid in ids_b for hid in theme.evidence_highlight_ids)
        if not (has_a and has_b):
            theme.evidence_highlight_ids = []  # Drop invalid attribution

    # Build evidence context map for rendering (highlight_id → details)
    all_highlights = {h.id: h for h in highlights_a + highlights_b}
    # Fetch conversation titles for context
    convo_ids_needed = {h.conversation_id for h in all_highlights.values()}
    convo_map: dict[int, str] = {}
    if convo_ids_needed:
        convo_result = await db.execute(
            select(Conversation.id, Conversation.title)
            .where(Conversation.id.in_(convo_ids_needed))
        )
        convo_map = {cid: ctitle for cid, ctitle in convo_result.all()}

    evidence_context: dict[str, dict[str, Any]] = {}
    for hid, h in all_highlights.items():
        side_membership = "a" if hid in ids_a else "b"
        if hid in ids_a and hid in ids_b:
            side_membership = "both"
        evidence_context[str(hid)] = {
            "highlight_id": hid,
            "quote": h.quote,
            "tag_key": h.tag_key,
            "conversation_id": h.conversation_id,
            "conversation_title": convo_map.get(h.conversation_id, ""),
            "side": side_membership,
        }

    # Store as analysis
    result_dict = lens_output.model_dump()
    result_dict["evidence_context"] = evidence_context
    analysis = Analysis(
        conversation_id=None,
        kind="lens",
        input_scope={
            "filters_a": filters_a,
            "filters_b": filters_b,
            "label_a": label_a,
            "label_b": label_b,
        },
        result=result_dict,
        model=getattr(llm, "model_name", None),
        prompt_version="lens_v1",
    )
    db.add(analysis)
    await db.flush()
    return analysis
