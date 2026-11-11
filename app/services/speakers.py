"""Decide which speakers are ours (v0.5 D1).

At import time only ONE named interviewer was treated as "us", so a second rep or a colleague
on the same call became "them" and their lines were tagged as customer evidence. Before every
tagging run we re-derive each speaker's side from everything we know:

  * the named interviewer (as at import),
  * Clari's list of internal speakers (``meta.clari_us_speakers``),
  * the seller's company name, aliases and email domains (Settings -> Your company),
  * Clari participant emails (``meta.clari_speaker_emails``) matched to those domains.

It only ever promotes a speaker to "us". It never demotes one, so a person's manual or
import-time decision is not undone by a guess.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.seller import SellerProfile, get_seller_profile, is_our_speaker
from app.models import Conversation, Utterance
from app.normalize import _assign_side


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def speaker_is_ours(
    label: str,
    *,
    interviewer: str | None,
    meta: dict[str, Any] | None,
    profile: SellerProfile | None = None,
) -> bool:
    meta = meta or {}
    if interviewer and _assign_side(label, interviewer) == "us":
        return True
    internal = meta.get("clari_us_speakers")
    if isinstance(internal, list) and _norm(label) in {_norm(n) for n in internal if isinstance(n, str)}:
        return True
    emails = meta.get("clari_speaker_emails")
    email = None
    if isinstance(emails, dict):
        wanted = _norm(label)
        email = next((e for n, e in emails.items() if isinstance(n, str) and _norm(n) == wanted), None)
    return is_our_speaker(label, email=email if isinstance(email, str) else None, profile=profile)


async def refresh_speaker_sides(
    db: AsyncSession, convo: Conversation, utterances: list[Utterance]
) -> int:
    """Promote speakers to 'us' on the given utterances. Returns how many utterances changed."""
    profile = get_seller_profile()
    verdicts: dict[str, bool] = {}
    changed = 0
    for utt in utterances:
        if utt.speaker_side == "us":
            continue
        label = utt.speaker_label or ""
        if label not in verdicts:
            verdicts[label] = speaker_is_ours(
                label, interviewer=convo.interviewer, meta=convo.meta, profile=profile
            )
        if verdicts[label]:
            utt.speaker_side = "us"
            changed += 1
    if changed:
        await db.flush()
    return changed
