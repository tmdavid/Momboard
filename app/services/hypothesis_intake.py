"""T48: evidence-gated hypothesis intake — preview (read-only, saves nothing).

Given a typed belief, reuse the corpus retrieval (T42) to surface candidate
highlights, have the LLM score each candidate (supports/contradicts/unrelated)
over the provided candidates only, and return:

  - matches: scored, validated highlight candidates (ids checked against the set)
  - grounding_preview: the band the hypothesis *would* have if the human confirms
    the strong matches (computed with the shared T48 `_compute_grounding`)
  - suggested_questions: past-behavior Mom Test questions, generated when evidence
    is thin, so a no-match belief gets a validation plan rather than a blank save.

This NEVER writes a Hypothesis or HypothesisLink. Committing is a separate step.
"""

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.hypotheses import _compute_grounding
from app.llm.schemas import IntakeMatchOutput
from app.models import Highlight
from app.services.corpus_chat import _retrieve_candidates

logger = logging.getLogger(__name__)

# A match at or above this confidence is "strong" enough to count toward the
# grounding preview. Deliberately a module constant for now; promote to settings
# when tuning against real data (see T48 design — threshold calibration is empirical).
STRONG_CONFIDENCE = 0.6

_HYPOTHETICAL_RE = re.compile(r"\bwould you\b|\bwill you\b", re.IGNORECASE)


async def preview_intake(
    db: AsyncSession,
    statement: str,
    *,
    llm: Any,
    segment: str | None = None,
    filters: dict[str, Any] | None = None,
    min_confidence: float = 0.6,
) -> dict[str, Any]:
    """Preview evidence for a typed belief. Read-only; saves nothing.

    Matching rules (PRD P0): candidates are restricted to customer turns (our reps'
    speech and compliment-tagged highlights are excluded), each surviving match is
    enriched with its source (company/contact/date/utterance_id), and matches scored
    below `min_confidence` are dropped. A verification pass re-checks that each quote
    actually speaks to the belief.
    """
    # Stage 1: retrieve candidates (code, not LLM) — reuses the T42 retriever.
    candidates = await _retrieve_candidates(db, statement, filters=filters)
    # Restrict to customer turns: drop our-side utterances and compliment highlights,
    # which never constitute evidence for a belief about the customer.
    candidates = [h for h in candidates if await _is_customer_evidence(db, h)]
    candidate_by_id: dict[int, Highlight] = {h.id: h for h in candidates}

    if not candidates:
        # No corpus evidence at all → a hunch. Still generate validation questions.
        questions = await _suggest_questions(statement, segment, llm)
        return {
            "statement": statement,
            "segment": segment,
            "matches": [],
            "grounding_preview": "hunch",
            "suggested_questions": questions,
        }

    # Stage 2: LLM scores the provided candidates only.
    candidate_data = [
        {"id": h.id, "tag": h.tag_key, "quote": h.quote}
        for h in candidates[:30]
    ]
    prompt = (
        "A user proposes this belief about customers:\n"
        f'  "{statement}"\n\n'
        "Below are candidate evidence highlights from real calls. For EACH that is "
        "relevant, judge whether it SUPPORTS or CONTRADICTS the belief; ignore the rest.\n\n"
        "HARD RULES:\n"
        "- Only reference highlight IDs from the candidates below.\n"
        "- relation must be 'supports', 'contradicts', or 'unrelated'.\n"
        "- Do NOT invent evidence or sentiment beyond the quotes.\n"
        "- Also propose up to 3 PAST-BEHAVIOR questions to validate the belief "
        "(what they did/how they handle it today). Never use 'would you'/'will you'.\n\n"
        f"CANDIDATES:\n{candidate_data}"
    )
    result: IntakeMatchOutput = await llm.generate(
        prompt=prompt, schema=IntakeMatchOutput, model="corpus_chat"
    )

    # Validate: keep only relevant matches that reference real candidate IDs and
    # score at or above min_confidence.
    matches: list[dict[str, Any]] = []
    strong_supports = 0
    strong_contradicts = 0
    for m in result.matches:
        if m.relation == "unrelated":
            continue
        hl = candidate_by_id.get(m.highlight_id)
        if hl is None:
            logger.warning("Intake dropped match with invalid highlight_id=%s", m.highlight_id)
            continue
        if m.confidence < min_confidence:
            continue
        # Verification: re-check the quote actually speaks to the belief.
        if not await _verify_match(statement, hl.quote, m.relation, llm):
            logger.info("Intake verification dropped highlight_id=%s", hl.id)
            continue
        source = await _source_for(db, hl)
        matches.append({
            "highlight_id": hl.id,
            "quote": hl.quote,
            "tag_key": hl.tag_key,
            "conversation_id": hl.conversation_id,
            "utterance_id": hl.utterance_id,
            "company_name": source["company_name"],
            "contact_name": source["contact_name"],
            "conversation_date": source["conversation_date"],
            "relation": m.relation,
            "confidence": m.confidence,
            "rationale": m.rationale,
            "strong": m.confidence >= STRONG_CONFIDENCE,
        })
        if m.confidence >= STRONG_CONFIDENCE:
            if m.relation == "supports":
                strong_supports += 1
            else:
                strong_contradicts += 1

    # Grounding PREVIEW: the band the hypothesis would have if the human confirms the
    # strong matches. We feed strong counts as "confirmed" to the shared function;
    # weaker matches map to "suggested" so a no-strong case reads as `candidate`.
    weak = len(matches) - strong_supports - strong_contradicts
    grounding_preview = _compute_grounding(
        {"confirmed": strong_supports, "suggested": weak},
        {"confirmed": strong_contradicts, "suggested": 0},
    )

    # Questions: always generated by the model; apply the past-behavior post-validator.
    questions = _clean_questions(result.suggested_questions)
    # If there's no strong evidence, the questions matter most — ensure we have some.
    if not questions and strong_supports == 0 and strong_contradicts == 0:
        questions = await _suggest_questions(statement, segment, llm)

    return {
        "statement": statement,
        "segment": segment,
        "matches": matches,
        "grounding_preview": grounding_preview,
        "suggested_questions": questions,
    }


COMPLIMENT_TAGS = {"compliment"}


async def _is_customer_evidence(db: AsyncSession, h: Highlight) -> bool:
    """Keep only customer-turn, non-compliment highlights as candidate evidence.

    Our reps' speech and compliment-tagged highlights never evidence a belief about
    the customer. A highlight with no utterance (manual, no side) is kept.
    """
    if h.tag_key in COMPLIMENT_TAGS:
        return False
    if h.utterance_id is None:
        return True
    from app.models import Utterance
    utt = await db.get(Utterance, h.utterance_id)
    if utt is None:
        return True
    return utt.speaker_side != "us"


async def _source_for(db: AsyncSession, h: Highlight) -> dict[str, Any]:
    """Resolve company name, first contact name, and conversation date for a highlight."""
    from sqlalchemy import select as _select

    from app.models import Company, Contact, Conversation, ConversationContact

    convo = await db.get(Conversation, h.conversation_id)
    company_name = None
    conversation_date = None
    contact_name = None
    if convo:
        conversation_date = convo.happened_at.isoformat() if convo.happened_at else None
        if convo.company_id:
            company = await db.get(Company, convo.company_id)
            company_name = company.name if company else None
        row = (await db.execute(
            _select(Contact.name)
            .join(ConversationContact, ConversationContact.contact_id == Contact.id)
            .where(ConversationContact.conversation_id == convo.id)
            .order_by(Contact.id)
            .limit(1)
        )).first()
        contact_name = row[0] if row else None
    return {
        "company_name": company_name,
        "contact_name": contact_name,
        "conversation_date": conversation_date,
    }


async def _verify_match(statement: str, quote: str, relation: str, llm: Any) -> bool:
    """Second-pass check that a quote actually speaks to the belief.

    Fail-open: if the model can't give a clear yes/no (or errors), keep the match —
    the min_confidence floor already removed the weakest candidates, and we would
    rather show a borderline match (the human unticks it) than silently drop real
    evidence.
    """
    prompt = (
        "Does this customer quote genuinely "
        f"{'support' if relation == 'supports' else 'contradict'} the belief?\n"
        f'Belief: "{statement}"\n'
        f'Quote: "{quote}"\n'
        "Answer with a single match whose relation is 'supports' or 'contradicts' if "
        "the quote truly speaks to the belief, or 'unrelated' if it does not."
    )
    try:
        result: IntakeMatchOutput = await llm.generate(
            prompt=prompt, schema=IntakeMatchOutput, model="corpus_chat"
        )
    except Exception:  # noqa: BLE001 — verification is best-effort; fail open.
        return True
    if not result.matches:
        return True
    return result.matches[0].relation != "unrelated"


def _clean_questions(questions: list[str]) -> list[str]:
    """Reject hypothetical phrasing; keep past-behavior questions (T38 pattern)."""
    return [q for q in questions[:3] if q and not _HYPOTHETICAL_RE.search(q)]


async def _suggest_questions(statement: str, segment: str | None, llm: Any) -> list[str]:
    """Generate past-behavior validation questions for a thin/no-evidence belief."""
    prompt = (
        "A user believes the following about customers, but the call corpus has little "
        "or no evidence for it:\n"
        f'  "{statement}"\n'
        + (f"Segment: {segment}\n" if segment else "")
        + "\nPropose up to 3 PAST-BEHAVIOR questions to validate it in the next call. "
        "Ask what customers DID or how they handle it TODAY. "
        "Never use 'would you' or 'will you'. Return them in suggested_questions."
    )
    result: IntakeMatchOutput = await llm.generate(
        prompt=prompt, schema=IntakeMatchOutput, model="brief"
    )
    return _clean_questions(result.suggested_questions)
