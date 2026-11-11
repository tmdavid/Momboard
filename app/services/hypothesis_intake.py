"""T48 / v0.5 D8: evidence-gated hypothesis intake - preview (read-only, saves nothing).

Matching is two stages (the first version was too strict: it found 1 quote in 1,000 calls):

  1. FIND broadly (``evidence_search``): the belief is widened into search terms and every
     customer utterance is scanned, so untagged speech counts. Up to 50 candidates.
  2. JUDGE strictly (here): the model labels each candidate supports / contradicts / unrelated
     with a one-line reason; a verification pass re-checks the survivors. We keep the strongest,
     at most 2 per call and 10 overall.

Returns the matches, a ``grounding_preview`` (the band the belief would have if the human confirms
the strong matches, using the shared ``compute_band`` rules) and past-behaviour Mom Test questions
for thin evidence. This NEVER writes a Hypothesis or a HypothesisLink; committing is separate.
"""

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.schemas import IntakeMatchOutput
from app.models import Highlight
from app.services.evidence_search import Candidate, find_candidates
from app.services.hypothesis_grounding import compute_band

logger = logging.getLogger(__name__)

# A match at or above this confidence is "strong" enough to count toward the
# grounding preview. Deliberately a module constant for now; promote to settings
# when tuning against real data (see T48 design - threshold calibration is empirical).
STRONG_CONFIDENCE = 0.6
CANDIDATE_LIMIT = 50
MAX_MATCHES = 10
MAX_PER_CALL = 2

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
    """Preview evidence for a typed belief. Read-only; saves nothing."""
    # Stage 1: find candidates broadly (code + search terms, over all customer speech).
    candidates = await find_candidates(
        db, statement, segment=segment, llm=llm, limit=CANDIDATE_LIMIT, filters=filters
    )
    by_prompt_id: dict[int, Candidate] = {c.prompt_id: c for c in candidates}

    if not candidates:
        # No corpus evidence at all -> a hunch. Still generate validation questions.
        questions = await _suggest_questions(statement, segment, llm)
        return {
            "statement": statement,
            "segment": segment,
            "matches": [],
            "grounding_preview": "hunch",
            "suggested_questions": questions,
        }

    # Stage 2: the model judges the candidates, strictly. Untagged speech has a negative id.
    lines = []
    for c in candidates:
        parts = [f"id={c.prompt_id}", f"company={c.company_name or 'unknown'}"]
        if segment and c.company_notes:
            parts.append(f"notes={c.company_notes}")
        lines.append(" | ".join(parts) + f' | "{c.quote}"')
    segment_rule = (
        f"- The belief targets the segment '{segment}'. For each match set in_segment to 'yes' "
        "if the quote's company clearly belongs to that segment, 'no' if it clearly does not, "
        "and 'unknown' if the company info doesn't say. Do not guess.\n"
        if segment
        else ""
    )
    prompt = (
        "A user proposes this belief about customers:\n"
        f'  "{statement}"\n\n'
        "Below are candidate quotes from real calls (customer speech only). Judge EACH one "
        "STRICTLY: it SUPPORTS the belief only if it states or clearly implies it, CONTRADICTS "
        "only if it clearly says the opposite, otherwise it is 'unrelated'. Do not stretch a quote "
        "to fit. Give a one-line reason for each match in rationale.\n\n"
        "HARD RULES:\n"
        "- Only reference ids from the candidates below (copy the number exactly, including a minus sign).\n"
        "- relation must be 'supports', 'contradicts', or 'unrelated'.\n"
        "- Do NOT invent evidence or sentiment beyond the quotes.\n"
        "- Also propose up to 3 PAST-BEHAVIOR questions to validate the belief "
        "(what they did/how they handle it today). Never use 'would you'/'will you'.\n"
        f"{segment_rule}\n"
        "CANDIDATES:\n" + "\n".join(lines)
    )
    result: IntakeMatchOutput = await llm.generate(
        prompt=prompt, schema=IntakeMatchOutput, model="corpus_chat"
    )

    # Validate: keep only relevant matches that reference real candidates and score at or
    # above min_confidence.
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in result.matches:
        if m.relation == "unrelated":
            continue
        cand = by_prompt_id.get(m.highlight_id)
        if cand is None:
            logger.warning("Intake dropped match with invalid id=%s", m.highlight_id)
            continue
        if cand.key in seen or m.confidence < min_confidence:
            continue
        # Verification: re-check the quote actually speaks to the belief.
        if not await _verify_match(statement, cand.quote, m.relation, llm):
            logger.info("Intake verification dropped %s", cand.key)
            continue
        seen.add(cand.key)
        in_segment = (m.in_segment or "unknown") if segment else None
        rationale = m.rationale
        if in_segment == "no":
            rationale = f"{rationale} Outside the {segment} segment.".strip()
        matches.append({
            "key": cand.key,
            "tagged": cand.highlight_id is not None,
            "highlight_id": cand.highlight_id,
            "quote": cand.quote,
            "tag_key": cand.tag_key,
            "conversation_id": cand.conversation_id,
            "utterance_id": cand.utterance_id,
            "company_name": cand.company_name,
            "contact_name": cand.contact_name,
            "conversation_date": cand.conversation_date,
            "in_segment": in_segment,
            "relation": m.relation,
            "confidence": m.confidence,
            "rationale": rationale,
            # Strong = direct, confident, and not known to be outside the named segment.
            "strong": m.confidence >= STRONG_CONFIDENCE and in_segment != "no",
        })

    matches = _cap_per_call(matches, MAX_PER_CALL)
    matches.sort(key=lambda x: (_SEGMENT_RANK.get(x["in_segment"] or "", 0), -x["confidence"]))
    matches = matches[:MAX_MATCHES]

    strong_supports = sum(1 for x in matches if x["strong"] and x["relation"] == "supports")
    strong_contradicts = sum(1 for x in matches if x["strong"] and x["relation"] == "contradicts")

    # Grounding PREVIEW: the band the hypothesis would have if the human confirms the
    # strong matches. Weaker matches don't count (suggested evidence never moves a band).
    strong_support_companies = {
        x["company_name"]
        for x in matches
        if x["strong"] and x["relation"] == "supports" and x.get("company_name")
    }
    grounding_preview = compute_band(
        {"confirmed": strong_supports},
        {"confirmed": strong_contradicts},
        len(strong_support_companies),
    )

    # Questions: always generated by the model; apply the past-behavior post-validator.
    questions = _clean_questions(result.suggested_questions)
    # If there's no strong evidence, the questions matter most - ensure we have some.
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


# Segment ranking: in-segment first, then unknown, then known-outside (stable on confidence).
_SEGMENT_RANK = {"yes": 0, "unknown": 1, "no": 2}


def _cap_per_call(matches: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """At most ``limit`` matches per conversation, strongest first.

    When a call has more than the cap, prefer variety of stance: after its strongest match, take
    the strongest one that says the OPPOSITE (the same customer pulling both ways is the
    interesting case) before taking a second one that agrees.
    """
    by_call: dict[int, list[dict[str, Any]]] = {}
    for m in sorted(matches, key=lambda x: -x["confidence"]):
        by_call.setdefault(m["conversation_id"], []).append(m)
    kept: list[dict[str, Any]] = []
    for group in by_call.values():
        chosen = [group[0]]
        rest = group[1:]
        while rest and len(chosen) < limit:
            opposite = next((m for m in rest if m["relation"] != chosen[0]["relation"]), None)
            pick = opposite if opposite is not None else rest[0]
            chosen.append(pick)
            rest.remove(pick)
        kept.extend(chosen)
    return kept


async def _company_info(db: AsyncSession, h: Highlight) -> dict[str, str | None]:
    """Company name + notes for a highlight's conversation (for segment judgement)."""
    from app.models import Company, Conversation

    convo = await db.get(Conversation, h.conversation_id)
    company = await db.get(Company, convo.company_id) if convo and convo.company_id else None
    return {
        "name": company.name if company else "(unknown company)",
        "notes": (company.notes or "")[:300] if company else None,
    }


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
