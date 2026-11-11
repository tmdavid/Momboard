"""Band-change history for hypotheses.

The grounding band is derived at read time (never stored), so history is recorded as
events: every code path that can change a hypothesis's links calls
``current_band`` before and ``record_band_change`` after. An event is written only
when the band actually changed.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HypothesisBandEvent


async def current_band(db: AsyncSession, hypothesis_id: int) -> str:
    """The band a hypothesis would show right now (flushes pending changes first)."""
    from app.api.hypotheses import _build_rollup
    from app.services.hypothesis_grounding import compute_band

    await db.flush()
    supports, contradicts, companies_supporting, *_ = await _build_rollup(db, hypothesis_id)
    return compute_band(supports, contradicts, companies_supporting)


async def record_band_change(
    db: AsyncSession,
    hypothesis_id: int,
    before: str | None,
    cause_link_id: int | None = None,
) -> HypothesisBandEvent | None:
    """Write a band event if the band differs from ``before`` (``None`` = creation)."""
    after = await current_band(db, hypothesis_id)
    if after == before:
        return None
    event = HypothesisBandEvent(
        hypothesis_id=hypothesis_id,
        from_band=before,
        to_band=after,
        cause_link_id=cause_link_id,
    )
    db.add(event)
    await db.flush()
    return event


async def list_band_events(db: AsyncSession, hypothesis_id: int) -> list[HypothesisBandEvent]:
    result = await db.execute(
        select(HypothesisBandEvent)
        .where(HypothesisBandEvent.hypothesis_id == hypothesis_id)
        .order_by(HypothesisBandEvent.created_at.desc(), HypothesisBandEvent.id.desc())
    )
    return list(result.scalars().all())
