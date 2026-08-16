"""Synthesizer pipeline: cross-conversation highlight synthesis."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMClient
from app.llm.schemas import SynthesizerOutput
from app.models import Analysis, Company, Conversation, Highlight

logger = logging.getLogger(__name__)


async def run_synthesize(
    db: AsyncSession,
    analysis_id: int,
    filters: dict[str, Any],
    llm: LLMClient,
) -> Analysis | None:
    """Run the synthesizer on filtered highlights.

    Args:
        analysis_id: The Analysis row to update with results
        filters: Filter dict (tag, company_id, date_from, date_to)
        llm: LLM client
    """
    # Build filtered query for highlights
    query = (
        select(Highlight, Conversation, Company)
        .join(Conversation, Highlight.conversation_id == Conversation.id)
        .outerjoin(Company, Conversation.company_id == Company.id)
        .where(Highlight.status.in_(["suggested", "accepted"]))
    )

    if "tag" in filters and filters["tag"]:
        query = query.where(Highlight.tag_key == filters["tag"])
    if "company_id" in filters and filters["company_id"]:
        query = query.where(Conversation.company_id == filters["company_id"])

    query = query.order_by(Highlight.created_at.desc()).limit(200)

    result = await db.execute(query)
    rows = result.all()

    if not rows:
        logger.warning(f"No highlights match synthesis filters: {filters}")
        return None

    valid_highlight_ids = {h.id for h, _, _ in rows}

    # Format highlights with context
    highlights_str = "\n".join(
        f"[id={h.id}] tag={h.tag_key} | company={c.name if c else 'N/A'} | "
        f"convo=\"{conv.title}\" ({conv.happened_at.strftime('%Y-%m-%d') if conv.happened_at else 'N/A'}) | "
        f"quote: \"{h.quote}\""
        for h, conv, c in rows
    )

    input_data = {"highlights": highlights_str}
    synth_output, envelope = await llm.structured("synthesizer", input_data, SynthesizerOutput)

    # Validate evidence IDs
    for theme in synth_output.themes:
        theme.evidence_highlight_ids = [
            hid for hid in theme.evidence_highlight_ids if hid in valid_highlight_ids
        ]

    # Update the analysis row
    analysis = await db.get(Analysis, analysis_id)
    if analysis:
        analysis.result = synth_output.model_dump()
        analysis.model = envelope.model
        analysis.prompt_version = envelope.prompt_version
        await db.flush()

    return analysis
