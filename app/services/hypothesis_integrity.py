"""Reactive integrity for hypothesis evidence.

When the human review step rejects a highlight's tag, the quote is no longer valid
evidence for anything. Hypothesis links to it are marked ``invalid`` so the band —
which is derived at read time from link statuses — re-computes without them.

Mirrors the Decisions receipt hook in ``app/services/decisions.py``. ``invalid`` is
distinct from ``rejected`` (a human judged the *match* wrong): an invalid link was
sound until its underlying tag was withdrawn, and it stays for audit.
"""

from collections.abc import Iterable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HypothesisLink

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
    result = await db.execute(
        update(HypothesisLink)
        .where(
            HypothesisLink.highlight_id.in_(ids),
            HypothesisLink.status.in_(_LIVE_STATUSES),
        )
        .values(status=LINK_INVALID)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
