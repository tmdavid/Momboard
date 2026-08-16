"""Analyst pipeline: run analyst LLM, validate evidence, persist analysis."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMClient
from app.llm.schemas import AnalystOutput
from app.models import Analysis, Highlight, Utterance

logger = logging.getLogger(__name__)


async def run_analyze(
    db: AsyncSession,
    conversation_id: int,
    llm: LLMClient,
) -> Analysis | None:
    """Run the analyst agent on a conversation.

    Inputs: utterances + non-rejected highlights.
    Returns the created Analysis row.
    """
    # Load utterances
    result = await db.execute(
        select(Utterance)
        .where(Utterance.conversation_id == conversation_id)
        .order_by(Utterance.idx)
    )
    utterances = result.scalars().all()
    if not utterances:
        logger.warning(f"No utterances for conversation {conversation_id}")
        return None

    # Load non-rejected highlights
    hl_result = await db.execute(
        select(Highlight)
        .where(
            Highlight.conversation_id == conversation_id,
            Highlight.status.in_(["suggested", "accepted"]),
        )
        .order_by(Highlight.id)
    )
    highlights = hl_result.scalars().all()
    valid_highlight_ids = {h.id for h in highlights}

    # Format inputs
    utterances_str = "\n".join(
        f"[{u.idx}] {u.speaker_label} ({u.speaker_side}): {u.text}" for u in utterances
    )
    highlights_str = "\n".join(
        f"  [id={h.id}] {h.tag_key}: \"{h.quote}\"" for h in highlights
    )

    input_data = {
        "utterances": utterances_str,
        "highlights": highlights_str,
    }

    analyst_output, envelope = await llm.structured("analyst", input_data, AnalystOutput)

    # Validate evidence_highlight_ids — strip non-existent ones
    for pain in analyst_output.top_pains:
        pain.evidence_highlight_ids = [
            hid for hid in pain.evidence_highlight_ids if hid in valid_highlight_ids
        ]
        if not pain.evidence_highlight_ids:
            logger.warning(f"Pain '{pain.pain}' has no valid evidence IDs after filtering")

    # Store analysis
    analysis = Analysis(
        conversation_id=conversation_id,
        kind="conversation",
        model=envelope.model,
        prompt_version=envelope.prompt_version,
        result=analyst_output.model_dump(),
    )
    db.add(analysis)
    await db.flush()

    return analysis
