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
    owner_id: int | None = None,
    area: str | None = None,
    status: str = "proposed",
) -> Decision:
    """Create a decision with evidence links.

    Draft decisions may be created with zero evidence (assembled incrementally);
    any other status requires at least one evidence highlight. Validates IDs exist.
    """
    if status != "draft" and not evidence_highlight_ids:
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
        status=status,
        integrity="ok",
        integrity_reasons=None,
        hypothesis_id=hypothesis_id,
        created_by=created_by,
        owner_id=owner_id,
        area=area,
    )
    db.add(decision)
    await db.flush()

    for hid in evidence_highlight_ids:
        await _build_evidence(db, decision.id, hid)

    await db.flush()
    return decision


async def _build_evidence(db: AsyncSession, decision_id: int, highlight_id: int) -> "DecisionEvidence":
    """Create a DecisionEvidence receipt with a citation-time snapshot."""
    from app.models import Company, Conversation

    h = await db.get(Highlight, highlight_id)
    convo = await db.get(Conversation, h.conversation_id) if h else None
    company = None
    if convo and convo.company_id:
        company = await db.get(Company, convo.company_id)
    ev = DecisionEvidence(
        decision_id=decision_id,
        highlight_id=highlight_id,
        quote_snapshot=h.quote if h else None,
        company_name=company.name if company else None,
        conversation_id=convo.id if convo else None,
        conversation_date=convo.happened_at if convo else None,
    )
    db.add(ev)
    await db.flush()
    return ev


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
        "draft": ["proposed"],
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

    # Load the full evidence rows so we can read invalidation flags.
    ev_result = await db.execute(
        select(DecisionEvidence)
        .where(DecisionEvidence.decision_id == decision_id)
    )
    evidence_rows = list(ev_result.scalars().all())
    cited_highlight_ids = [e.highlight_id for e in evidence_rows if e.highlight_id is not None]

    reasons: list[dict[str, Any]] = []

    # Check 0: receipts invalidated by a reactive change (tag rejected, highlight or
    # conversation deleted). These are set by invalidate_decision_evidence().
    reason_text = {
        "tag_rejected": "A cited highlight's tag was rejected in review",
        "highlight_deleted": "A cited highlight was deleted",
        "conversation_deleted": "A cited conversation was deleted",
    }
    for e in evidence_rows:
        if e.invalid_reason:
            reasons.append({
                "reason": reason_text.get(e.invalid_reason, e.invalid_reason),
                "source_type": e.invalid_reason,
                "source_id": e.id,
            })

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

    # Update integrity status AND persist reasons + checked timestamp
    if undermined:
        decision.integrity = "undermined"
        decision.integrity_reasons = {"reasons": reasons}  # type: ignore[assignment]
    else:
        decision.integrity = "ok"
        decision.integrity_reasons = None
    decision.integrity_checked_at = utcnow()
    await db.flush()

    return {
        "decision_id": decision_id,
        "integrity": "undermined" if undermined else "ok",
        "integrity_checked_at": decision.integrity_checked_at.isoformat(),
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
    """Get a decision's evidence receipts.

    Served from the citation-time snapshot so a receipt survives a Retag that
    replaced the live highlight. Falls back to the live highlight for pre-snapshot
    rows. The live highlight (when it still exists) supplies the current status and
    the deep-link; `invalid_reason` flags a receipt the integrity hook has broken.
    """
    from app.models import Conversation

    ev_result = await db.execute(
        select(DecisionEvidence)
        .where(DecisionEvidence.decision_id == decision_id)
    )
    evidence_items = list(ev_result.scalars().all())

    items = []
    for ev in evidence_items:
        highlight = await db.get(Highlight, ev.highlight_id) if ev.highlight_id else None
        # Prefer the snapshot; fall back to the live highlight for legacy rows.
        quote = ev.quote_snapshot if ev.quote_snapshot is not None else (highlight.quote if highlight else None)
        conv_id = ev.conversation_id if ev.conversation_id is not None else (highlight.conversation_id if highlight else None)
        company_name = ev.company_name
        conv_date = ev.conversation_date.isoformat() if ev.conversation_date else None
        conv_title = None
        if conv_id is not None:
            convo = await db.get(Conversation, conv_id)
            if convo:
                conv_title = convo.title
                if conv_date is None and convo.happened_at:
                    conv_date = convo.happened_at.isoformat()
        items.append({
            "highlight_id": ev.highlight_id,
            "quote": quote,
            "tag_key": highlight.tag_key if highlight else None,
            "company_name": company_name,
            "conversation_id": conv_id,
            "conversation_title": conv_title,
            "conversation_happened_at": conv_date,
            # Live highlight status when present; the receipt's own validity flag.
            "status": highlight.status if highlight else "deleted",
            "invalid_reason": ev.invalid_reason,
        })
    return items


# --- Reactive integrity hook (Decisions PRD P0 slice 2) ---------------------
#
# When a cited highlight's tag is rejected, the highlight is deleted, or its
# conversation is deleted/retagged, the decision receipts that cite it are
# flagged invalid and the owning decisions' integrity is recomputed. Built as
# plain helpers so the hypotheses board can reuse the same pattern later
# (PRD: "build it once for both").

INVALID_TAG_REJECTED = "tag_rejected"
INVALID_HIGHLIGHT_DELETED = "highlight_deleted"
INVALID_CONVERSATION_DELETED = "conversation_deleted"


async def _recompute_decisions(db: AsyncSession, decision_ids: set[int]) -> None:
    for did in decision_ids:
        await check_decision_integrity(db, did)


async def invalidate_decision_evidence_for_highlights(
    db: AsyncSession,
    highlight_ids: list[int],
    *,
    reason: str,
) -> set[int]:
    """Flag receipts citing the given highlights invalid, recompute integrity.

    Returns the set of affected decision IDs. Idempotent: re-flagging with the
    same reason is a no-op. Does not change decision status (human decision).
    """
    if not highlight_ids:
        return set()
    result = await db.execute(
        select(DecisionEvidence).where(DecisionEvidence.highlight_id.in_(highlight_ids))
    )
    rows = list(result.scalars().all())
    affected: set[int] = set()
    for ev in rows:
        if ev.invalid_reason != reason:
            ev.invalid_reason = reason
        affected.add(ev.decision_id)
    await db.flush()
    await _recompute_decisions(db, affected)
    return affected


async def invalidate_decision_evidence_for_conversation(
    db: AsyncSession,
    conversation_id: int,
    *,
    reason: str = INVALID_CONVERSATION_DELETED,
) -> set[int]:
    """Flag receipts whose snapshot points at the conversation, recompute integrity.

    Uses the receipt's snapshot `conversation_id` so it still works after the
    conversation (and its highlights) are gone.
    """
    result = await db.execute(
        select(DecisionEvidence).where(DecisionEvidence.conversation_id == conversation_id)
    )
    rows = list(result.scalars().all())
    affected: set[int] = set()
    for ev in rows:
        if ev.invalid_reason != reason:
            ev.invalid_reason = reason
        affected.add(ev.decision_id)
    await db.flush()
    await _recompute_decisions(db, affected)
    return affected


# --- P1: edit, evidence add/remove, detail enrichment ----------------------


async def update_decision(
    db: AsyncSession,
    decision_id: int,
    *,
    title: str | None = None,
    rationale_md: str | None = None,
    owner_id: int | None = None,
    area: str | None = None,
) -> Decision:
    """Edit a decision's title, rationale, owner or area. Only provided fields change."""
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")
    if title is not None:
        if not title.strip():
            raise ValueError("Title cannot be empty")
        decision.title = title
    if rationale_md is not None:
        decision.rationale_md = rationale_md
    if owner_id is not None:
        decision.owner_id = owner_id
    if area is not None:
        decision.area = area
    await db.flush()
    return decision


async def add_evidence(db: AsyncSession, decision_id: int, highlight_id: int) -> DecisionEvidence:
    """Cite an existing highlight on a decision, snapshotting it. Idempotent."""
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")
    h = await db.get(Highlight, highlight_id)
    if h is None:
        raise ValueError(f"Highlight {highlight_id} not found")
    existing = await db.execute(
        select(DecisionEvidence).where(
            DecisionEvidence.decision_id == decision_id,
            DecisionEvidence.highlight_id == highlight_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row
    ev = await _build_evidence(db, decision_id, highlight_id)
    # New supporting evidence can clear an undermined flag; recompute.
    await check_decision_integrity(db, decision_id)
    return ev


async def remove_evidence(db: AsyncSession, decision_id: int, highlight_id: int) -> None:
    """Un-cite a highlight from a decision.

    A non-draft decision must keep at least one receipt (a decision rests on
    evidence); removing the last one from a non-draft decision is rejected.
    """
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")
    result = await db.execute(
        select(DecisionEvidence).where(DecisionEvidence.decision_id == decision_id)
    )
    rows = list(result.scalars().all())
    target = next((r for r in rows if r.highlight_id == highlight_id), None)
    if target is None:
        raise ValueError(f"Highlight {highlight_id} is not cited by decision {decision_id}")
    if decision.status != "draft" and len(rows) <= 1:
        raise ValueError("A decision must cite at least one piece of evidence")
    await db.delete(target)
    await db.flush()
    await check_decision_integrity(db, decision_id)


async def get_hypothesis_summary(db: AsyncSession, hypothesis_id: int) -> dict[str, Any] | None:
    """Return the linked hypothesis's statement + computed grounding band for the detail view."""
    from app.api.hypotheses import _compute_grounding
    from app.models import Hypothesis

    hyp = await db.get(Hypothesis, hypothesis_id)
    if hyp is None:
        return None
    link_result = await db.execute(
        select(HypothesisLink).where(HypothesisLink.hypothesis_id == hypothesis_id)
    )
    supports = {"confirmed": 0, "suggested": 0}
    contradicts = {"confirmed": 0, "suggested": 0}
    for link in link_result.scalars().all():
        bucket = supports if link.stance == "supports" else contradicts
        if link.status == "confirmed":
            bucket["confirmed"] += 1
        elif link.status == "suggested":
            bucket["suggested"] += 1
    return {
        "id": hyp.id,
        "statement": hyp.statement,
        "band": _compute_grounding(supports, contradicts),
    }


async def get_superseded_by_title(db: AsyncSession, superseded_by_id: int | None) -> str | None:
    """Return the title of the decision that supersedes this one, if any."""
    if superseded_by_id is None:
        return None
    successor = await db.get(Decision, superseded_by_id)
    return successor.title if successor else None
