"""Hypothesis linker: propose evidence links between highlights and open hypotheses."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMClient
from app.llm.schemas import LinkerOutput
from app.models import Highlight, Hypothesis, HypothesisLink

logger = logging.getLogger(__name__)


async def run_hypothesis_link(
    db: AsyncSession,
    conversation_id: int,
    llm: LLMClient,
) -> None:
    """Run hypothesis linker: propose evidence links for open hypotheses.

    Only feeds open hypotheses and non-rejected highlights from the conversation
    to the LLM. Strips any links referencing invalid hypothesis_ids or highlight_ids.

    Args:
        db: Async database session.
        conversation_id: The conversation whose highlights to link.
        llm: LLM client implementing the structured protocol.
    """
    # Fetch open hypotheses only
    open_hyps_result = await db.execute(
        select(Hypothesis).where(Hypothesis.status == "open")
    )
    open_hypotheses = open_hyps_result.scalars().all()

    if not open_hypotheses:
        logger.info("No open hypotheses — skipping linker for conversation %d", conversation_id)
        return

    # Fetch non-rejected highlights for this conversation
    highlights_result = await db.execute(
        select(Highlight).where(
            Highlight.conversation_id == conversation_id,
            Highlight.status != "rejected",
        )
    )
    highlights = highlights_result.scalars().all()

    if not highlights:
        logger.info("No non-rejected highlights for conversation %d", conversation_id)
        return

    # Build input data for the LLM
    valid_hypothesis_ids = {h.id for h in open_hypotheses}
    # Valid highlight IDs = all highlights that exist in DB (for link validation)
    all_highlights_result = await db.execute(select(Highlight.id))
    valid_highlight_ids = {row[0] for row in all_highlights_result.all()}

    hypotheses_input = [
        {"id": h.id, "statement": h.statement, "segment": h.segment}
        for h in open_hypotheses
    ]
    highlights_input = [
        {
            "id": h.id,
            "tag_key": h.tag_key,
            "quote": h.quote,
            "confidence": h.confidence,
        }
        for h in highlights
    ]

    input_data: dict[str, Any] = {
        "hypotheses": hypotheses_input,
        "highlights": highlights_input,
    }

    # Call the LLM
    result, envelope = await llm.structured(
        prompt_name="hypothesis_linker",
        input_data=input_data,
        schema=LinkerOutput,
    )

    # Persist valid links, stripping any with invalid IDs
    for link_data in result.links:
        if link_data.hypothesis_id not in valid_hypothesis_ids:
            logger.warning(
                "Stripping link with invalid hypothesis_id=%d", link_data.hypothesis_id
            )
            continue
        if link_data.highlight_id not in valid_highlight_ids:
            logger.warning(
                "Stripping link with invalid highlight_id=%d", link_data.highlight_id
            )
            continue
        if link_data.stance not in ("supports", "contradicts"):
            logger.warning(
                "Stripping link with invalid stance=%r", link_data.stance
            )
            continue

        db_link = HypothesisLink(
            hypothesis_id=link_data.hypothesis_id,
            highlight_id=link_data.highlight_id,
            stance=link_data.stance,
            confidence=link_data.confidence,
            rationale=link_data.rationale,
            origin="ai",
            status="suggested",
        )
        db.add(db_link)

    await db.flush()
