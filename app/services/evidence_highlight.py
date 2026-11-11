"""Turn confirmed customer speech into a highlight a hypothesis can cite (v0.5 D8).

Matching now searches every customer utterance, so a quote a person confirms as evidence may never
have been tagged. Everything downstream (links, decision receipts, integrity checks, Explore) is
keyed on highlights, so confirming such a quote records it as an *accepted* highlight tagged
``context`` - a person has judged it, which is what "accepted" means. If the utterance already
has a live highlight, that one is reused, so confirming never creates duplicates.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Highlight, Tag, Utterance

FALLBACK_TAG = "context"
MAX_QUOTE_CHARS = 300


class EvidenceError(ValueError):
    """The utterance cannot be used as evidence (reason is safe to show the user)."""


class UtteranceNotFoundError(LookupError):
    pass


def _excerpt(text: str, preferred: str | None) -> str:
    """A verbatim stretch of the utterance: the excerpt the preview showed if it really is one,
    otherwise the start of the utterance trimmed on a word boundary."""
    text = text.strip()
    if preferred and preferred.strip() and preferred.strip() in text:
        return preferred.strip()
    if len(text) <= MAX_QUOTE_CHARS:
        return text
    cut = text[:MAX_QUOTE_CHARS]
    return cut[: cut.rfind(" ")] if " " in cut else cut


async def highlight_for_utterance(
    db: AsyncSession, utterance_id: int, preferred_quote: str | None = None
) -> Highlight:
    utt = await db.get(Utterance, utterance_id)
    if utt is None:
        raise UtteranceNotFoundError(f"Utterance {utterance_id} not found")
    if utt.speaker_side == "us":
        raise EvidenceError("That line was spoken by our own team, so it is not customer evidence")

    existing = (
        await db.execute(
            select(Highlight)
            .where(Highlight.utterance_id == utterance_id, Highlight.status.in_(["accepted", "suggested"]))
            .order_by(Highlight.id)
        )
    ).scalars().all()
    if existing:
        return sorted(existing, key=lambda h: (h.status != "accepted", -(h.confidence or 0.0), h.id))[0]

    tag = await db.get(Tag, FALLBACK_TAG)
    if tag is None:
        raise EvidenceError(f"The '{FALLBACK_TAG}' tag is missing, so this quote cannot be recorded")
    highlight = Highlight(
        conversation_id=utt.conversation_id,
        utterance_id=utt.id,
        tag_key=FALLBACK_TAG,
        quote=_excerpt(utt.text, preferred_quote),
        confidence=None,
        status="accepted",
        origin="human",
    )
    db.add(highlight)
    await db.flush()
    return highlight
