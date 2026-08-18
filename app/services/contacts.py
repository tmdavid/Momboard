"""T29: Contact/company memory timelines and drift detection."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Contact,
    Conversation,
    ConversationContact,
    Drift,
    Highlight,
)

logger = logging.getLogger(__name__)


async def get_contact_timeline(
    db: AsyncSession,
    contact_id: int,
    *,
    kind_filter: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Build a chronological timeline of events for a contact.

    Events include: conversations, highlights (signals), commitments, drifts.
    Sorted newest-first by default.
    """
    events: list[dict[str, Any]] = []

    # Get conversations involving this contact (exclude simulated)
    convo_ids_q = (
        select(ConversationContact.conversation_id)
        .join(Conversation, Conversation.id == ConversationContact.conversation_id)
        .where(
            ConversationContact.contact_id == contact_id,
            Conversation.source != "simulator",  # T39: exclude simulated evidence
        )
    )
    convo_ids_result = await db.execute(convo_ids_q)
    convo_ids = [r[0] for r in convo_ids_result.all()]

    if not convo_ids:
        return events

    # Conversations
    if kind_filter is None or kind_filter == "conversations":
        convos_result = await db.execute(
            select(Conversation)
            .where(Conversation.id.in_(convo_ids))
            .order_by(Conversation.happened_at.desc().nullslast())
        )
        for convo in convos_result.scalars().all():
            events.append({
                "kind": "conversation",
                "timestamp": (convo.happened_at or convo.created_at).isoformat(),
                "conversation_id": convo.id,
                "title": convo.title,
                "status": convo.status,
            })

    # Highlights (signals)
    if kind_filter is None or kind_filter == "signals":
        highlights_result = await db.execute(
            select(Highlight)
            .where(
                Highlight.conversation_id.in_(convo_ids),
                Highlight.status.in_(["accepted", "suggested"]),
            )
            .options(selectinload(Highlight.tag))
            .order_by(Highlight.created_at.desc())
            .limit(limit)
        )
        for h in highlights_result.scalars().all():
            events.append({
                "kind": "highlight",
                "timestamp": h.created_at.isoformat(),
                "highlight_id": h.id,
                "conversation_id": h.conversation_id,
                "tag_key": h.tag_key,
                "tag_emoji": h.tag.emoji if h.tag else "",
                "quote": h.quote,
                "status": h.status,
            })

    # Commitments (followup/commitment highlights)
    if kind_filter is None or kind_filter == "commitments":
        commits_result = await db.execute(
            select(Highlight)
            .where(
                Highlight.conversation_id.in_(convo_ids),
                Highlight.tag_key.in_(["commitment", "followup"]),
                Highlight.status.in_(["accepted", "suggested"]),
            )
            .order_by(Highlight.created_at.desc())
            .limit(limit)
        )
        for h in commits_result.scalars().all():
            events.append({
                "kind": "commitment",
                "timestamp": h.created_at.isoformat(),
                "highlight_id": h.id,
                "conversation_id": h.conversation_id,
                "tag_key": h.tag_key,
                "quote": h.quote,
            })

    # Sort all events newest-first
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return events[:limit]


async def get_company_timeline(
    db: AsyncSession,
    company_id: int,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Build timeline aggregating all contacts of a company."""
    # Get all contacts for this company
    contacts_result = await db.execute(
        select(Contact.id).where(Contact.company_id == company_id)
    )
    contact_ids = [r[0] for r in contacts_result.all()]

    # Also include conversations directly linked to company
    convos_result = await db.execute(
        select(Conversation)
        .where(
            Conversation.company_id == company_id,
            Conversation.source != "simulator",  # T39: exclude simulated evidence
        )
        .order_by(Conversation.happened_at.desc().nullslast())
        .limit(limit)
    )

    events: list[dict[str, Any]] = []
    for convo in convos_result.scalars().all():
        events.append({
            "kind": "conversation",
            "timestamp": (convo.happened_at or convo.created_at).isoformat(),
            "conversation_id": convo.id,
            "title": convo.title,
            "status": convo.status,
        })

    if contact_ids:
        # Get highlights from all contact conversations (exclude simulated)
        convo_ids_q = (
            select(ConversationContact.conversation_id)
            .join(Conversation, Conversation.id == ConversationContact.conversation_id)
            .where(
                ConversationContact.contact_id.in_(contact_ids),
                Conversation.source != "simulator",  # T39: exclude simulated evidence
            )
        )
        convo_ids_result = await db.execute(convo_ids_q)
        convo_ids = list({r[0] for r in convo_ids_result.all()})

        if convo_ids:
            highlights_result = await db.execute(
                select(Highlight)
                .where(
                    Highlight.conversation_id.in_(convo_ids),
                    Highlight.status.in_(["accepted", "suggested"]),
                )
                .order_by(Highlight.created_at.desc())
                .limit(limit)
            )
            for h in highlights_result.scalars().all():
                events.append({
                    "kind": "highlight",
                    "timestamp": h.created_at.isoformat(),
                    "highlight_id": h.id,
                    "conversation_id": h.conversation_id,
                    "tag_key": h.tag_key,
                    "quote": h.quote,
                })

    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return events[:limit]


async def run_drift_check(
    db: AsyncSession,
    conversation_id: int,
    llm: Any,
) -> list[Drift]:
    """Check for contradictions/changes between prior and new statements for contacts.

    Skipped when the contact has no prior accepted highlights.
    """
    from app.llm.schemas import DriftOutput

    # Get contacts for this conversation
    convo_contacts_result = await db.execute(
        select(ConversationContact.contact_id)
        .where(ConversationContact.conversation_id == conversation_id)
    )
    contact_ids = [r[0] for r in convo_contacts_result.all()]

    if not contact_ids:
        return []

    # Get new highlights from this conversation
    new_highlights_result = await db.execute(
        select(Highlight)
        .where(
            Highlight.conversation_id == conversation_id,
            Highlight.status.in_(["accepted", "suggested"]),
        )
    )
    new_highlights = list(new_highlights_result.scalars().all())
    if not new_highlights:
        return []

    drifts_found: list[Drift] = []

    for contact_id in contact_ids:
        # Get prior conversations for this contact (excluding current)
        prior_convo_ids_result = await db.execute(
            select(ConversationContact.conversation_id)
            .where(
                ConversationContact.contact_id == contact_id,
                ConversationContact.conversation_id != conversation_id,
            )
        )
        prior_convo_ids = [r[0] for r in prior_convo_ids_result.all()]

        if not prior_convo_ids:
            continue  # No prior history — skip

        # Get prior accepted highlights
        prior_highlights_result = await db.execute(
            select(Highlight)
            .where(
                Highlight.conversation_id.in_(prior_convo_ids),
                Highlight.status == "accepted",
            )
            .order_by(Highlight.created_at.desc())
            .limit(20)
        )
        prior_highlights = list(prior_highlights_result.scalars().all())

        if not prior_highlights:
            continue  # No prior accepted evidence — skip

        # Call LLM to detect drifts
        prior_statements = [
            {"id": h.id, "quote": h.quote, "tag": h.tag_key}
            for h in prior_highlights
        ]
        new_statements = [
            {"id": h.id, "quote": h.quote, "tag": h.tag_key}
            for h in new_highlights
        ]

        prompt = (
            "Compare the earlier statements from this contact with their new statements. "
            "Identify any contradictions or meaningful changes in position.\n\n"
            f"EARLIER STATEMENTS:\n{prior_statements}\n\n"
            f"NEW STATEMENTS:\n{new_statements}\n\n"
            "Return only actual contradictions or changes, not restatements of the same thing."
        )

        result = await llm.generate(
            prompt=prompt,
            schema=DriftOutput,
            model="drift_checker",
        )

        if result and result.drifts:
            for d in result.drifts:
                # Validate IDs exist
                earlier_valid = any(h.id == d.earlier_highlight_id for h in prior_highlights)
                later_valid = any(h.id == d.later_highlight_id for h in new_highlights)

                if earlier_valid and later_valid:
                    # Check if this drift already exists (idempotent)
                    existing = await db.execute(
                        select(Drift).where(
                            Drift.contact_id == contact_id,
                            Drift.earlier_highlight_id == d.earlier_highlight_id,
                            Drift.later_highlight_id == d.later_highlight_id,
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none() is None:
                        drift = Drift(
                            contact_id=contact_id,
                            earlier_highlight_id=d.earlier_highlight_id,
                            later_highlight_id=d.later_highlight_id,
                            kind=d.kind if d.kind in ("contradiction", "change") else "change",
                            summary=d.summary,
                            status="open",
                        )
                        db.add(drift)
                        drifts_found.append(drift)

    await db.flush()
    return drifts_found


async def get_contact_drifts(
    db: AsyncSession,
    contact_id: int,
    *,
    include_dismissed: bool = False,
) -> list[Drift]:
    """Get drift alerts for a contact."""
    query = select(Drift).where(Drift.contact_id == contact_id)
    if not include_dismissed:
        query = query.where(Drift.status != "dismissed")
    query = query.order_by(Drift.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def dismiss_drift(db: AsyncSession, drift_id: int) -> Drift:
    """Dismiss a drift alert."""
    drift = await db.get(Drift, drift_id)
    if drift is None:
        raise ValueError(f"Drift {drift_id} not found")
    drift.status = "dismissed"
    await db.flush()
    return drift


async def confirm_drift(db: AsyncSession, drift_id: int) -> Drift:
    """Confirm a drift alert."""
    drift = await db.get(Drift, drift_id)
    if drift is None:
        raise ValueError(f"Drift {drift_id} not found")
    drift.status = "confirmed"
    await db.flush()
    return drift
