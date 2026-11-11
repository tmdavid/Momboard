"""Stage 1 of hypothesis matching (v0.5 D8): find candidate evidence broadly.

The old retrieval only looked at quotes that had already been tagged, used the first five words
of the belief, and ordered by recency. A belief like "Law firms won't buy an annual plan without a
pilot first" therefore never saw the call that says exactly that. This stage instead:

  1. widens the belief into search terms (its own words plus synonyms/phrases the model proposes),
  2. scans EVERY customer utterance for them (so untagged evidence counts too),
  3. ranks by how many terms hit, lifts companies that match the segment, and keeps at most a few
     per call so one long call cannot crowd out the rest,
  4. hands back a bounded list (default 50) for the strict judge in stage 2.

There is no embedding model in MomBoard, so this is keyword retrieval widened by the model. It is
deliberately recall-oriented: stage 2 decides what is actually evidence.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.schemas import SearchTerms
from app.llm.tag_rules import MIN_WORDS
from app.models import Company, Contact, Conversation, ConversationContact, Highlight, Utterance
from app.services.confidence_floor import passes_floor

logger = logging.getLogger(__name__)

COMPLIMENT_TAGS = {"compliment"}
MAX_TERMS = 24
MAX_PER_CALL = 3
FETCH_ROWS = 1500          # utterance rows pulled from SQL before ranking in Python
EXCERPT_MAX_CHARS = 300
SEGMENT_BOOST = 2.0

STOPWORDS = frozenset(
    """a an the and or but if so of to in on at by for with without from into onto over under about
    as is are was were be been being am do does did done have has had having will would can could
    should shall may might must it its this that these those there their they them we us our you
    your i me my he she his her him not no than then too very just more most some any each every
    also only own same such what which who whom whose when where why how all both few other because
    while until up down out off again further once here won t s d ll re ve don didn doesn isn aren
    wasn weren hasn haven hadn wouldn couldn shouldn""".split()
)


def _stem(word: str) -> str:
    """A light suffix strip so 'exports' finds 'export'. Terms are matched as substrings, so a
    stem finds its own inflections ('handl' matches 'handle', 'handles', 'handling')."""
    w = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*", text)


async def search_terms_for(statement: str, segment: str | None, llm: Any) -> list[str]:
    """The belief's own content words plus the model's synonyms and phrases, de-duplicated and
    capped. If the model fails the belief's own words still work."""
    own = [_stem(w) for w in _words(statement) if w.lower() not in STOPWORDS and len(w) >= 3]
    proposed: list[str] = []
    prompt = (
        "A user proposes this belief about customers:\n"
        f'  "{statement}"\n'
        + (f"Segment: {segment}\n" if segment else "")
        + "\nList words and short phrases a CUSTOMER might use when talking about this, in ordinary "
        "speech: synonyms, related behaviours, and the specific things the belief hinges on "
        "(for example a belief about 'a pilot' should also list 'trial', 'proof of concept', 'test run'). "
        "Return 8 to 20 single words or short phrases, most important first. Do not repeat the belief."
    )
    try:
        result = await llm.generate(prompt=prompt, schema=SearchTerms, model="corpus_chat")
        if isinstance(result, SearchTerms):
            proposed = [t.strip().lower() for t in result.terms if isinstance(t, str)]
    except Exception:  # noqa: BLE001 - search must degrade to the belief's own words, never fail
        logger.warning("Search-term expansion failed; using the belief's own words", exc_info=True)

    terms: list[str] = []
    for term in [*own, *proposed]:
        cleaned = " ".join(term.split())
        if " " not in cleaned:
            cleaned = _stem(cleaned)
        if len(cleaned) >= 3 and cleaned not in STOPWORDS and cleaned not in terms:
            terms.append(cleaned)
    return terms[:MAX_TERMS]


def best_excerpt(text: str, terms: list[str], max_chars: int = EXCERPT_MAX_CHARS) -> str:
    """The most relevant stretch of an utterance, always a verbatim substring of it.

    Picks the sentence holding the most search terms; if that sentence is itself too long it is
    trimmed to a window around the first hit, on word boundaries.
    """
    text = text.strip()
    sentences = [m for m in re.finditer(r"[^.!?]+[.!?]*", text) if m.group().strip()]
    if not sentences:
        return text[:max_chars]

    def hits(span: str) -> int:
        low = span.lower()
        return sum(1 for t in terms if t in low)

    best = max(sentences, key=lambda m: (hits(m.group()), -m.start()))
    start, end = best.start(), best.end()
    while start < end and text[start].isspace():
        start += 1
    excerpt = text[start:end].rstrip()
    if len(excerpt) <= max_chars:
        return excerpt

    low = excerpt.lower()
    first = min((low.find(t) for t in terms if t in low), default=0)
    lo = max(0, first - max_chars // 3)
    hi = min(len(excerpt), lo + max_chars)
    while lo > 0 and not excerpt[lo - 1].isspace():
        lo += 1
    while hi < len(excerpt) and not excerpt[hi].isspace() and hi > lo:
        hi -= 1
    return excerpt[lo:hi].strip() or excerpt[:max_chars]


@dataclass
class Candidate:
    """A quote that might be evidence. ``highlight_id`` is None when the utterance was never tagged."""

    conversation_id: int
    utterance_id: int | None
    highlight_id: int | None
    tag_key: str | None
    quote: str
    company_name: str | None
    contact_name: str | None
    conversation_date: str | None
    score: float = 0.0
    company_notes: str | None = None

    @property
    def key(self) -> str:
        return f"h{self.highlight_id}" if self.highlight_id is not None else f"u{self.utterance_id}"

    @property
    def prompt_id(self) -> int:
        """The id the judge sees: the highlight id, or minus the utterance id for untagged speech."""
        return self.highlight_id if self.highlight_id is not None else -(self.utterance_id or 0)


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _segment_tokens(segment: str | None) -> list[str]:
    return [_stem(w) for w in _words(segment or "") if w.lower() not in STOPWORDS and len(w) >= 3]


async def find_candidates(
    db: AsyncSession,
    statement: str,
    *,
    segment: str | None,
    llm: Any,
    limit: int = 50,
    filters: dict[str, Any] | None = None,
) -> list[Candidate]:
    terms = await search_terms_for(statement, segment, llm)
    if not terms:
        return []
    likes = [Utterance.text.ilike(f"%{_like_escape(t)}%", escape="\\") for t in terms]

    query = (
        select(Utterance, Conversation, Company)
        .join(Conversation, Conversation.id == Utterance.conversation_id)
        .outerjoin(Company, Company.id == Conversation.company_id)
        .where(
            or_(*likes),
            Utterance.speaker_side != "us",
            Conversation.source != "simulator",
        )
        .order_by(Utterance.id.desc())
        .limit(FETCH_ROWS)
    )
    if filters:
        if "company_id" in filters:
            query = query.where(Conversation.company_id == filters["company_id"])
        if "date_from" in filters:
            query = query.where(Conversation.happened_at >= filters["date_from"])
        if "date_to" in filters:
            query = query.where(Conversation.happened_at <= filters["date_to"])
    rows = (await db.execute(query)).all()

    seg = _segment_tokens(segment)
    scored: list[tuple[float, Utterance, Conversation, Company | None]] = []
    for utt, convo, company in rows:
        low = (utt.text or "").lower()
        if len(low.split()) < MIN_WORDS:
            continue  # "Okay." / "Yes." never evidence
        score = sum(2.0 if " " in t else 1.0 for t in terms if t in low)
        if score <= 0:
            continue
        if seg and company is not None:
            about = f"{company.name} {company.notes or ''}".lower()
            if sum(1 for tok in seg if tok in about) >= max(1, len(seg) // 2):
                score += SEGMENT_BOOST
        scored.append((score, utt, convo, company))
    scored.sort(key=lambda r: (-r[0], -r[1].id))

    # Keep a few per call so one long call cannot fill the list.
    per_call: dict[int, int] = {}
    kept: list[tuple[float, Utterance, Conversation, Company | None]] = []
    for row in scored:
        n = per_call.get(row[2].id, 0)
        if n >= MAX_PER_CALL:
            continue
        per_call[row[2].id] = n + 1
        kept.append(row)
        if len(kept) >= limit:
            break

    # Reuse the best existing highlight on each utterance (accepted first, then most confident).
    utt_ids = [u.id for _, u, _, _ in kept]
    existing: dict[int, Highlight] = {}
    if utt_ids:
        hl_rows = (
            await db.execute(
                select(Highlight).where(
                    Highlight.utterance_id.in_(utt_ids),
                    Highlight.status.in_(["accepted", "suggested"]),
                    passes_floor(),
                )
            )
        ).scalars().all()
        for h in hl_rows:
            if h.utterance_id is None:
                continue
            current = existing.get(h.utterance_id)
            rank = (h.status == "accepted", h.confidence or 0.0)
            if current is None or rank > (current.status == "accepted", current.confidence or 0.0):
                existing[h.utterance_id] = h

    contacts = await _first_contacts(db, {c.id for _, _, c, _ in kept})
    out: list[Candidate] = []
    for score, utt, convo, company in kept:
        stored = existing.get(utt.id)
        if stored is not None and stored.tag_key in COMPLIMENT_TAGS:
            continue
        out.append(Candidate(
            conversation_id=convo.id,
            utterance_id=utt.id,
            highlight_id=stored.id if stored else None,
            tag_key=stored.tag_key if stored else None,
            quote=stored.quote if stored else best_excerpt(utt.text, terms),
            company_name=company.name if company else None,
            contact_name=contacts.get(convo.id),
            conversation_date=convo.happened_at.date().isoformat() if convo.happened_at else None,
            score=score,
            company_notes=(company.notes or "")[:200] if company and company.notes else None,
        ))

    # Quotes someone typed in by hand have no utterance; they are evidence too.
    manual = (
        await db.execute(
            select(Highlight, Conversation, Company)
            .join(Conversation, Conversation.id == Highlight.conversation_id)
            .outerjoin(Company, Company.id == Conversation.company_id)
            .where(
                Highlight.utterance_id.is_(None),
                Highlight.status.in_(["accepted", "suggested"]),
                Conversation.source != "simulator",
                or_(*[Highlight.quote.ilike(f"%{_like_escape(t)}%", escape="\\") for t in terms]),
                passes_floor(),
            )
            .limit(20)
        )
    ).all()
    for h, convo, company in manual:
        if h.tag_key in COMPLIMENT_TAGS:
            continue
        out.append(Candidate(convo.id, None, h.id, h.tag_key, h.quote, company.name if company else None,
                             None, convo.happened_at.date().isoformat() if convo.happened_at else None, 1.0))
    return out[:limit]


async def _first_contacts(db: AsyncSession, conversation_ids: set[int]) -> dict[int, str]:
    if not conversation_ids:
        return {}
    rows = await db.execute(
        select(ConversationContact.conversation_id, Contact.name)
        .join(Contact, Contact.id == ConversationContact.contact_id)
        .where(ConversationContact.conversation_id.in_(conversation_ids))
        .order_by(ConversationContact.conversation_id, Contact.id)
    )
    first: dict[int, str] = {}
    for conversation_id, name in rows.all():
        first.setdefault(conversation_id, name)
    return first
