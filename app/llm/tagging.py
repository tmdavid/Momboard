"""Tagging pipeline: run tagger LLM, validate quotes, persist highlights."""

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMClient, LLMEnvelope
from app.llm.schemas import TaggerHighlight, TaggerOutput
from app.models import Highlight, Tag, Utterance

logger = logging.getLogger(__name__)

CHUNK_SIZE = 80
CHUNK_OVERLAP = 10


def chunk_utterances(
    utterances: list[dict[str, Any]], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[list[dict[str, Any]]]:
    """Split utterances into chunks with overlap for long transcripts."""
    if len(utterances) <= chunk_size:
        return [utterances]

    chunks = []
    start = 0
    while start < len(utterances):
        end = min(start + chunk_size, len(utterances))
        chunks.append(utterances[start:end])
        if end >= len(utterances):
            break
        start = end - overlap
    return chunks


def validate_quote(quote: str, utterance_text: str) -> tuple[bool, str]:
    """Validate that a quote is a verbatim substring of the utterance.

    Returns (is_valid, cleaned_quote).
    Tries exact match first, then fuzzy match with normalized whitespace/quotes.
    """
    # Exact substring match
    if quote in utterance_text:
        return True, quote

    # Normalize: casefold + collapse whitespace + normalize quotes
    def _normalize(s: str) -> str:
        s = s.casefold()
        s = re.sub(r"[\u2018\u2019\u201C\u201D]", "'", s)  # curly quotes
        s = re.sub(r"\s+", " ", s).strip()
        return s

    norm_quote = _normalize(quote)
    norm_text = _normalize(utterance_text)

    if norm_quote in norm_text:
        return True, quote

    # Fuzzy match — check sequence ratio
    ratio = SequenceMatcher(None, norm_quote, norm_text).ratio()
    if ratio >= 0.9:
        return True, quote

    # Try finding best substring match
    if len(norm_quote) <= len(norm_text):
        best_ratio = 0.0
        for i in range(len(norm_text) - len(norm_quote) + 1):
            window = norm_text[i : i + len(norm_quote)]
            r = SequenceMatcher(None, norm_quote, window).ratio()
            if r > best_ratio:
                best_ratio = r
        if best_ratio >= 0.85:
            return True, quote

    return False, quote


def dedupe_highlights(highlights: list[TaggerHighlight]) -> list[TaggerHighlight]:
    """Deduplicate highlights by (utterance_idx, tag_key), keeping highest confidence."""
    seen: dict[tuple[int, str], TaggerHighlight] = {}
    for h in highlights:
        key = (h.utterance_idx, h.tag_key)
        if key not in seen or h.confidence > seen[key].confidence:
            seen[key] = h
    return list(seen.values())


async def run_tag(
    db: AsyncSession,
    conversation_id: int,
    llm: LLMClient,
) -> list[Highlight]:
    """Run the tagger agent on a conversation's utterances.

    Returns list of created Highlight rows.
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
        return []

    # Load active tags for taxonomy
    tags_result = await db.execute(select(Tag).where(Tag.is_active == True))  # noqa: E712
    tags = tags_result.scalars().all()
    taxonomy_str = "\n".join(
        f"- `{t.key}` {t.emoji} {t.name}: {t.description} (signal: {t.signal_strength})"
        for t in tags
    )

    # Build utterance dicts
    utt_dicts = [
        {"idx": u.idx, "speaker": u.speaker_label, "side": u.speaker_side, "text": u.text}
        for u in utterances
    ]

    # Map idx to utterance for validation
    utt_by_idx = {u.idx: u for u in utterances}

    # Get conversation metadata
    from app.models import Conversation

    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    interviewer = convo.interviewer or "Unknown"
    company_name = ""
    if convo.company_id:
        from app.models import Company

        company = await db.get(Company, convo.company_id)
        company_name = company.name if company else ""

    # Chunk and call
    chunks = chunk_utterances(utt_dicts)
    all_highlights: list[TaggerHighlight] = []
    envelope: LLMEnvelope | None = None

    for chunk in chunks:
        utterances_str = "\n".join(
            f"[{u['idx']}] {u['speaker']} ({u['side']}): {u['text']}" for u in chunk
        )

        input_data = {
            "taxonomy": taxonomy_str,
            "utterances": utterances_str,
            "interviewer": interviewer,
            "company": company_name,
        }

        tagger_output, env = await llm.structured("tagger", input_data, TaggerOutput)
        envelope = env
        all_highlights.extend(tagger_output.highlights)

    # Dedupe across chunks
    all_highlights = dedupe_highlights(all_highlights)

    # Validate and persist
    valid_tag_keys = {t.key for t in tags}
    created: list[Highlight] = []

    for h in all_highlights:
        # Check tag key exists
        if h.tag_key not in valid_tag_keys:
            logger.warning(
                f"Tagger returned unknown tag_key '{h.tag_key}' for utterance {h.utterance_idx} — skipping"
            )
            continue

        # Check utterance exists
        utt = utt_by_idx.get(h.utterance_idx)
        if utt is None:
            logger.warning(f"Tagger referenced non-existent utterance_idx {h.utterance_idx} — skipping")
            continue

        # Validate quote
        is_valid, cleaned_quote = validate_quote(h.quote, utt.text)
        if not is_valid:
            logger.warning(
                f"Fabricated quote for utterance {h.utterance_idx}: '{h.quote[:50]}...' — dropping"
            )
            continue

        highlight = Highlight(
            conversation_id=conversation_id,
            utterance_id=utt.id,
            tag_key=h.tag_key,
            quote=cleaned_quote,
            confidence=h.confidence,
            origin="ai",
            status="suggested",
            provenance={
                "response_id": envelope.response_id if envelope else "",
                "model": envelope.model if envelope else "",
                "prompt_version": envelope.prompt_version if envelope else "",
                "rationale": h.rationale,
            },
        )
        db.add(highlight)
        created.append(highlight)

    await db.flush()
    return created
