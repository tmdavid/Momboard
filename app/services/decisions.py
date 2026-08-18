"""T40: Decision log with evidence receipts — CRUD + integrity checks."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Decision,
    DecisionEvidence,
    Drift,
    Highlight,
    HypothesisLink,
    utcnow,
)

logger = logging.getLogger(__name__)


class HighlightCitedError(Exception):
    """Raised when trying to delete a highlight that is cited by decisions."""

    def __init__(self, highlight_id: int, decision_ids: list[int]):
        self.highlight_id = highlight_id
        self.decision_ids = decision_ids
        super().__init__(
            f"Highlight {highlight_id} is cited by decisions: {decision_ids}"
        )


async def create_decision(
    db: AsyncSession,
    *,
    title: str,
    rationale_md: str,
    evidence_highlight_ids: list[int],
    hypothesis_id: int | None = None,
    created_by: int | None = None,
) -> Decision:
    """Create a decision with at least one evidence link.

    Raises ValueError if zero evidence IDs provided.
    Validates that all highlight IDs exist.
    """
    if not evidence_highlight_ids:
        raise ValueError("A decision requires at least one evidence highlight")

    # Validate ALL highlight IDs exist — reject if ANY are invalid (no silent dropping)
    invalid_ids: list[int] = []
    for hid in evidence_highlight_ids:
        h = await db.get(Highlight, hid)
        if h is None:
            invalid_ids.append(hid)

    if invalid_ids:
        raise ValueError(
            f"Invalid evidence highlight IDs: {invalid_ids}. "
            "All evidence IDs must reference existing highlights."
        )

    decision = Decision(
        title=title,
        rationale_md=rationale_md,
        status="proposed",
        integrity="ok",
        integrity_reasons=None,
        hypothesis_id=hypothesis_id,
        created_by=created_by,
    )
    db.add(decision)
    await db.flush()

    # Create evidence links (all IDs validated above)
    for hid in evidence_highlight_ids:
        evidence = DecisionEvidence(
            decision_id=decision.id,
            highlight_id=hid,
        )
        db.add(evidence)

    await db.flush()
    return decision


async def get_decision(db: AsyncSession, decision_id: int) -> Decision | None:
    """Get a decision with its evidence loaded."""
    result = await db.execute(
        select(Decision).where(Decision.id == decision_id)
    )
    return result.scalar_one_or_none()


async def list_decisions(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Decision], int]:
    """List decisions with optional status filter."""
    query = select(Decision)
    count_query = select(Decision.id)

    if status:
        query = query.where(Decision.status == status)
        count_query = count_query.where(Decision.status == status)

    count_result = await db.execute(count_query)
    total = len(count_result.all())

    query = query.order_by(Decision.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def transition_decision(
    db: AsyncSession,
    decision_id: int,
    *,
    new_status: str,
    decided_by: int | None = None,
    superseded_by_id: int | None = None,
) -> Decision:
    """Transition decision status: proposed → decided → superseded.

    Records decided_at and decided_by when transitioning to 'decided'.
    """
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")

    valid_transitions = {
        "proposed": ["decided"],
        "decided": ["superseded"],
        "superseded": [],
    }

    allowed = valid_transitions.get(decision.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Cannot transition from '{decision.status}' to '{new_status}'. "
            f"Allowed: {allowed}"
        )

    decision.status = new_status

    if new_status == "decided":
        decision.decided_at = utcnow()
        decision.decided_by = decided_by
    elif new_status == "superseded":
        if not superseded_by_id:
            raise ValueError(
                "Superseding requires a valid successor decision ID (superseded_by_id)"
            )
        if superseded_by_id == decision_id:
            raise ValueError("A decision cannot supersede itself")
        # Validate successor exists and is a different decision
        successor = await db.get(Decision, superseded_by_id)
        if successor is None:
            raise ValueError(f"Successor decision {superseded_by_id} not found")
        # Direct cycle check: successor cannot already be superseded by this decision
        if successor.superseded_by == decision_id:
            raise ValueError(
                f"Direct cycle: decision {superseded_by_id} is already superseded by {decision_id}"
            )
        decision.superseded_by = superseded_by_id

    await db.flush()
    return decision


async def check_decision_integrity(
    db: AsyncSession,
    decision_id: int,
) -> dict[str, Any]:
    """Check whether a decision's evidence has been undermined.

    A decision is undermined when:
    - A confirmed hypothesis_link with stance='contradicts' exists on a hypothesis
      that the decision cites
    - A drift exists on a cited highlight's contact

    Returns dict with undermined status and reasons.
    Does NOT auto-change status (human decision).
    """
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")

    # Get all cited highlight IDs
    ev_result = await db.execute(
        select(DecisionEvidence.highlight_id)
        .where(DecisionEvidence.decision_id == decision_id)
    )
    cited_highlight_ids = [r[0] for r in ev_result.all()]

    reasons: list[dict[str, Any]] = []

    # Check 1: Contradicting hypothesis links on cited highlights
    if cited_highlight_ids:
        contra_result = await db.execute(
            select(HypothesisLink)
            .where(
                HypothesisLink.highlight_id.in_(cited_highlight_ids),
                HypothesisLink.stance == "contradicts",
                HypothesisLink.status == "confirmed",
            )
        )
        for link in contra_result.scalars().all():
            reasons.append({
                "reason": f"Confirmed contradicting evidence on highlight {link.highlight_id}",
                "source_type": "contradiction",
                "source_id": link.id,
            })

    # Check 2: Open drifts on cited highlights' contacts
    if cited_highlight_ids:
        # Get highlights with their conversations to find contacts
        for hid in cited_highlight_ids:
            drift_result = await db.execute(
                select(Drift)
                .where(
                    Drift.status == "open",
                    (Drift.earlier_highlight_id == hid) | (Drift.later_highlight_id == hid),
                )
            )
            for drift in drift_result.scalars().all():
                reasons.append({
                    "reason": f"Open drift ({drift.kind}) involving cited highlight {hid}",
                    "source_type": "drift",
                    "source_id": drift.id,
                })

    undermined = len(reasons) > 0

    # Update integrity status AND persist reasons
    if undermined:
        decision.integrity = "undermined"
        decision.integrity_reasons = {"reasons": reasons}  # type: ignore[assignment]
    else:
        decision.integrity = "ok"
        decision.integrity_reasons = None
    await db.flush()

    return {
        "decision_id": decision_id,
        "integrity": "undermined" if undermined else "ok",
        "reasons": reasons,
    }


async def check_highlight_cited(
    db: AsyncSession,
    highlight_id: int,
) -> list[int]:
    """Check if a highlight is cited by any decisions.

    Returns list of decision IDs that cite this highlight.
    Used to block deletion of cited highlights.
    """
    result = await db.execute(
        select(DecisionEvidence.decision_id)
        .where(DecisionEvidence.highlight_id == highlight_id)
    )
    return [r[0] for r in result.all()]


async def get_decision_evidence(
    db: AsyncSession,
    decision_id: int,
) -> list[dict[str, Any]]:
    """Get evidence highlights for a decision with full conversation context for UI."""
    from app.models import Conversation

    ev_result = await db.execute(
        select(DecisionEvidence)
        .where(DecisionEvidence.decision_id == decision_id)
    )
    evidence_items = list(ev_result.scalars().all())

    items = []
    for ev in evidence_items:
        highlight = await db.get(Highlight, ev.highlight_id)
        if highlight:
            convo = await db.get(Conversation, highlight.conversation_id)
            items.append({
                "highlight_id": highlight.id,
                "quote": highlight.quote,
                "tag_key": highlight.tag_key,
                "conversation_id": highlight.conversation_id,
                "conversation_title": convo.title if convo else None,
                "conversation_happened_at": (
                    convo.happened_at.isoformat() if convo and convo.happened_at else None
                ),
                "status": highlight.status,
            })
    return items
