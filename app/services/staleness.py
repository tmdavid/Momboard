"""T41: Evidence freshness/staleness — computed read-time, integrated into hypotheses/stats/digest/briefs."""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    Highlight,
    Hypothesis,
    HypothesisLink,
    utcnow,
)


def _get_thresholds() -> tuple[int, int]:
    """Get staleness thresholds from settings (lazy import to avoid circular)."""
    try:
        from app.config import get_settings

        settings = get_settings()
        return settings.staleness_fresh_days, settings.staleness_aging_days
    except Exception:
        return 90, 180


def compute_freshness_band(newest_evidence_at: Any, now: Any = None) -> str:
    """Pure function: compute freshness band from newest confirming evidence date.

    Returns: 'fresh' (<fresh_days), 'aging' (<aging_days), or 'stale' (>=aging_days).
    """
    if newest_evidence_at is None:
        return "stale"

    if now is None:
        now = utcnow()

    fresh_days, aging_days = _get_thresholds()
    age = now - newest_evidence_at
    if age < timedelta(days=fresh_days):
        return "fresh"
    elif age < timedelta(days=aging_days):
        return "aging"
    else:
        return "stale"


async def get_hypothesis_freshness(
    db: AsyncSession,
    hypothesis_id: int,
) -> dict[str, Any]:
    """Compute freshness for a hypothesis based on newest confirmed supporting evidence.

    Returns dict with freshness_band and newest_evidence_at.
    """
    # Get newest confirmed supporting highlight's conversation.happened_at
    result = await db.execute(
        select(func.max(Conversation.happened_at))
        .join(Highlight, Highlight.conversation_id == Conversation.id)
        .join(HypothesisLink, HypothesisLink.highlight_id == Highlight.id)
        .where(
            HypothesisLink.hypothesis_id == hypothesis_id,
            HypothesisLink.stance == "supports",
            HypothesisLink.status == "confirmed",
            Conversation.source != "simulator",  # T39: exclude simulated evidence
        )
    )
    newest = result.scalar_one_or_none()
    band = compute_freshness_band(newest)

    return {
        "freshness": band,
        "newest_evidence_at": newest.isoformat() if newest else None,
    }


async def get_stale_hypotheses(
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Get all open hypotheses that are stale (supported only by old evidence).

    Used by digest and stats endpoints.
    """
    now = utcnow()
    _fresh_days, aging_days = _get_thresholds()
    stale_cutoff = now - timedelta(days=aging_days)

    # All open hypotheses
    hyp_result = await db.execute(
        select(Hypothesis).where(Hypothesis.status == "open")
    )
    hypotheses = list(hyp_result.scalars().all())

    stale_items = []
    for hyp in hypotheses:
        # Get newest confirmed supporting evidence date
        result = await db.execute(
            select(func.max(Conversation.happened_at))
            .join(Highlight, Highlight.conversation_id == Conversation.id)
            .join(HypothesisLink, HypothesisLink.highlight_id == Highlight.id)
            .where(
                HypothesisLink.hypothesis_id == hyp.id,
                HypothesisLink.stance == "supports",
                HypothesisLink.status == "confirmed",
                Conversation.source != "simulator",  # T39: exclude simulated evidence
            )
        )
        newest = result.scalar_one_or_none()

        if newest is None or newest < stale_cutoff:
            stale_items.append({
                "id": hyp.id,
                "statement": hyp.statement,
                "freshness": "stale",
                "newest_evidence_at": newest.isoformat() if newest else None,
            })

    return stale_items
