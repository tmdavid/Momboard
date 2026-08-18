"""T38: Pre-call briefs — compile history, suggest questions, cache as analysis."""

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    Contact,
    Conversation,
    ConversationContact,
    Drift,
    Highlight,
    Hypothesis,
    utcnow,
)

logger = logging.getLogger(__name__)

BRIEF_CACHE_HOURS = 1


async def build_brief(
    db: AsyncSession,
    contact_id: int,
    *,
    llm: Any,
    force_refresh: bool = False,
) -> Analysis:
    """Build or return cached pre-call brief for a contact.

    Sections:
    - known_facts (LLM-summarized from accepted highlights)
    - open_followups (SQL)
    - open_drifts (SQL)
    - suggested_questions (LLM, past-behavior phrased)
    - stale hypotheses needing revalidation (SQL join)
    """
    from app.llm.schemas import BriefOutput

    # Check cache (analyses with kind='brief' and contact_id in input_scope)
    if not force_refresh:
        cache_cutoff = utcnow() - timedelta(hours=BRIEF_CACHE_HOURS)
        cached_result = await db.execute(
            select(Analysis)
            .where(
                Analysis.kind == "brief",
                Analysis.created_at >= cache_cutoff,
            )
            .order_by(Analysis.created_at.desc())
            .limit(10)
        )
        for cached in cached_result.scalars().all():
            if cached.input_scope and cached.input_scope.get("contact_id") == contact_id:
                return cached

    # Gather data
    convo_ids_result = await db.execute(
        select(ConversationContact.conversation_id)
        .join(Conversation, Conversation.id == ConversationContact.conversation_id)
        .where(
            ConversationContact.contact_id == contact_id,
            Conversation.source != "simulator",  # T39: exclude simulated evidence
        )
    )
    convo_ids = [r[0] for r in convo_ids_result.all()]

    # Accepted highlights for this contact
    prior_highlights: list[Highlight] = []
    if convo_ids:
        h_result = await db.execute(
            select(Highlight)
            .where(
                Highlight.conversation_id.in_(convo_ids),
                Highlight.status == "accepted",
            )
            .order_by(Highlight.created_at.desc())
            .limit(30)
        )
        prior_highlights = list(h_result.scalars().all())

    # Open follow-ups
    open_followups: list[dict] = []
    if convo_ids:
        fu_result = await db.execute(
            select(Highlight)
            .where(
                Highlight.conversation_id.in_(convo_ids),
                Highlight.tag_key == "followup",
                Highlight.status.in_(["accepted", "suggested"]),
            )
        )
        open_followups = [
            {"id": h.id, "quote": h.quote}
            for h in fu_result.scalars().all()
        ]

    # Drifts (open only)
    drifts_result = await db.execute(
        select(Drift)
        .where(Drift.contact_id == contact_id, Drift.status == "open")
    )
    open_drifts = [
        {"id": d.id, "summary": d.summary, "kind": d.kind}
        for d in drifts_result.scalars().all()
    ]

    # Stale hypotheses (open, needing revalidation from this segment)
    contact = await db.get(Contact, contact_id)
    stale_hypotheses: list[dict] = []
    if contact and contact.company_id:
        hyp_result = await db.execute(
            select(Hypothesis)
            .where(Hypothesis.status == "open")
            .limit(10)
        )
        for hyp in hyp_result.scalars().all():
            stale_hypotheses.append({"id": hyp.id, "statement": hyp.statement})

    # Build LLM input (only for known_facts + suggested_questions)
    is_first_call = len(prior_highlights) == 0

    if is_first_call:
        # Degrade gracefully: no LLM call needed
        brief_output = BriefOutput(
            known_facts=[],
            suggested_questions=[
                h["statement"] for h in stale_hypotheses[:3]
            ] if stale_hypotheses else [],
            watch_out="First conversation — no prior history.",
        )
    else:
        highlight_data = [
            {"id": h.id, "tag": h.tag_key, "quote": h.quote}
            for h in prior_highlights
        ]
        prompt = (
            "You are preparing a pre-call brief. Given the prior evidence from this contact, "
            "produce:\n"
            "1. known_facts: key things we know (each citing highlight IDs)\n"
            "2. suggested_questions: exactly 3 past-behavior questions to ask\n"
            "3. watch_out: one sentence on what to be careful about\n\n"
            "Rules:\n"
            "- Questions MUST be past-behavior phrased (what did, how do, when was)\n"
            "- NEVER use 'would you' or 'will you' phrasing\n"
            "- Each known_fact must cite at least one highlight ID\n\n"
            f"EVIDENCE:\n{highlight_data}\n"
            f"OPEN FOLLOW-UPS: {open_followups}\n"
            f"OPEN DRIFTS: {open_drifts}\n"
            f"HYPOTHESES TO VALIDATE: {stale_hypotheses}\n"
        )

        brief_output = await llm.generate(
            prompt=prompt,
            schema=BriefOutput,
            model="brief",
        )

        # Validate highlight IDs in known_facts
        valid_ids = {h.id for h in prior_highlights}
        for fact in brief_output.known_facts:
            fact.evidence_highlight_ids = [
                hid for hid in fact.evidence_highlight_ids if hid in valid_ids
            ]

        # Validate questions are past-behavior phrased (reject 'would/will you')
        import re
        clean_questions = []
        for q in brief_output.suggested_questions[:3]:
            if not re.search(r"\bwould you\b|\bwill you\b", q, re.IGNORECASE):
                clean_questions.append(q)
        brief_output.suggested_questions = clean_questions

    # Store as analysis
    result_dict = brief_output.model_dump()
    result_dict["open_followups"] = open_followups
    result_dict["open_drifts"] = open_drifts
    result_dict["stale_hypotheses"] = stale_hypotheses
    result_dict["is_first_call"] = is_first_call

    analysis = Analysis(
        conversation_id=None,
        kind="brief",
        input_scope={"contact_id": contact_id},
        result=result_dict,
        model=getattr(llm, "model_name", None),
        prompt_version="brief_v1",
    )
    db.add(analysis)
    await db.flush()
    return analysis
