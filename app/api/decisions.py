"""T40: Decision log API routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import User

router = APIRouter()


class DecisionCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    rationale_md: str = Field(min_length=1)
    evidence: list[int] = Field(min_length=1)
    hypothesis_id: int | None = None


class DecisionTransitionRequest(BaseModel):
    status: str  # decided|superseded
    superseded_by_id: int | None = None


@router.post("", status_code=201)
async def create_decision(
    body: DecisionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a decision with evidence links. Requires at least one evidence highlight."""
    from app.services.decisions import create_decision as _create

    try:
        decision = await _create(
            db,
            title=body.title,
            rationale_md=body.rationale_md,
            evidence_highlight_ids=body.evidence,
            hypothesis_id=body.hypothesis_id,
            created_by=user.id,
        )
        await db.commit()
        return {
            "id": decision.id,
            "title": decision.title,
            "status": decision.status,
            "integrity": decision.integrity,
            "created_at": decision.created_at.isoformat() if decision.created_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("")
async def list_decisions(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List decisions with optional status filter."""
    from app.services.decisions import list_decisions as _list

    items, total = await _list(db, status=status, limit=limit, offset=offset)
    return {
        "items": [
            {
                "id": d.id,
                "title": d.title,
                "status": d.status,
                "integrity": d.integrity,
                "decided_at": d.decided_at.isoformat() if d.decided_at else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in items
        ],
        "total": total,
    }


@router.get("/{decision_id}")
async def get_decision(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a decision with its evidence."""
    from app.services.decisions import get_decision as _get
    from app.services.decisions import get_decision_evidence

    decision = await _get(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    evidence = await get_decision_evidence(db, decision_id)

    return {
        "id": decision.id,
        "title": decision.title,
        "rationale_md": decision.rationale_md,
        "status": decision.status,
        "integrity": decision.integrity,
        "integrity_reasons": (decision.integrity_reasons or {}).get("reasons") if isinstance(decision.integrity_reasons, dict) else decision.integrity_reasons,
        "hypothesis_id": decision.hypothesis_id,
        "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
        "decided_by": decision.decided_by,
        "superseded_by": decision.superseded_by,
        "evidence": evidence,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


@router.patch("/{decision_id}/status")
async def transition_decision(
    decision_id: int,
    body: DecisionTransitionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Transition decision status: proposed → decided → superseded."""
    from app.services.decisions import transition_decision as _transition

    try:
        decision = await _transition(
            db,
            decision_id,
            new_status=body.status,
            decided_by=user.id,
            superseded_by_id=body.superseded_by_id,
        )
        await db.commit()
        return {
            "id": decision.id,
            "status": decision.status,
            "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{decision_id}/integrity")
async def check_integrity(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check decision integrity (undermined by new contradicting evidence or drifts)."""
    from app.services.decisions import check_decision_integrity

    try:
        result = await check_decision_integrity(db, decision_id)
        await db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
