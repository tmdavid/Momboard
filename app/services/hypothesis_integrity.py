"""Reactive integrity for hypothesis evidence.

When the human review step rejects a highlight's tag, the quote is no longer valid
evidence for anything. Hypothesis links to it are marked ``invalid`` so the band —
which is derived at read time from link statuses — re-computes without them.

Mirrors the Decisions receipt hook in ``app/services/decisions.py``. ``invalid`` is
distinct from ``rejected`` (a human judged the *match* wrong): an invalid link was
sound until its underlying tag was withdrawn, and it stays for audit.
"""

from collections.abc import Iterable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HypothesisLink
from app.services.hypothesis_history import current_band, record_band_change

LINK_INVALID = "invalid"
_LIVE_STATUSES = ("suggested", "confirmed")


async def invalidate_hypothesis_links_for_highlights(
    db: AsyncSession, highlight_ids: Iterable[int]
) -> int:
    """Mark live (suggested/confirmed) links to these highlights ``invalid``.

    Does not commit — the caller's transaction owns that. Returns the number of
    links changed.
    """
    ids = list(highlight_ids)
    if not ids:
        return 0

    # Which live links (and hypotheses) are about to change — to record band events.
    live = (
        await db.execute(
            select(HypothesisLink.id, HypothesisLink.hypothesis_id).where(
                HypothesisLink.highlight_id.in_(ids),
                HypothesisLink.status.in_(_LIVE_STATUSES),
            )
        )
    ).all()
    if not live:
        return 0
    cause_by_hyp: dict[int, int] = {}
    for link_id, hyp_id in live:
        cause_by_hyp.setdefault(hyp_id, link_id)
    before = {hyp_id: await current_band(db, hyp_id) for hyp_id in cause_by_hyp}

    result = await db.execute(
        update(HypothesisLink)
        .where(
            HypothesisLink.highlight_id.in_(ids),
            HypothesisLink.status.in_(_LIVE_STATUSES),
        )
        .values(status=LINK_INVALID)
    )
    for hyp_id, link_id in cause_by_hyp.items():
        await record_band_change(db, hyp_id, before[hyp_id], cause_link_id=link_id)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
