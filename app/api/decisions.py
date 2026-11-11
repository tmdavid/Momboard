"""T40: Decision log API routes."""

from datetime import datetime
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import User

router = APIRouter()


class DecisionStatus(StrEnum):
    draft = "draft"
    proposed = "proposed"
    decided = "decided"
    superseded = "superseded"


class DecisionCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    rationale_md: str = Field(min_length=1)
    evidence: list[int] = Field(default_factory=list)
    hypothesis_id: int | None = None
    owner_id: int | None = None
    area: str | None = None
    status: DecisionStatus = DecisionStatus.proposed


class DecisionUpdateRequest(BaseModel):
    title: str | None = None
    rationale_md: str | None = None
    owner_id: int | None = None
    area: str | None = None


class DecisionTransitionRequest(BaseModel):
    status: DecisionStatus
    superseded_by_id: int | None = None


class IntegrityReason(BaseModel):
    reason: str
    source_type: str
    source_id: int


class DecisionListItem(BaseModel):
    id: int
    title: str
    status: DecisionStatus
    integrity: str
    integrity_checked_at: datetime | None = None
    owner_id: int | None = None
    area: str | None = None
    decided_at: datetime | None = None
    created_at: datetime | None = None


class DecisionListResponse(BaseModel):
    items: list[DecisionListItem]
    total: int


class DecisionEvidenceReceipt(BaseModel):
    highlight_id: int | None = None
    quote: str | None = None
    tag_key: str | None = None
    company_name: str | None = None
    conversation_id: int | None = None
    conversation_title: str | None = None
    conversation_happened_at: str | None = None
    status: str
    invalid_reason: str | None = None


class LinkedHypothesis(BaseModel):
    id: int
    statement: str
    band: str


class DecisionDetailResponse(BaseModel):
    id: int
    title: str
    rationale_md: str
    status: DecisionStatus
    integrity: str
    integrity_reasons: list[IntegrityReason] | None = None
    integrity_checked_at: datetime | None = None
    hypothesis_id: int | None = None
    hypothesis: LinkedHypothesis | None = None
    owner_id: int | None = None
    area: str | None = None
    decided_at: datetime | None = None
    decided_by: int | None = None
    superseded_by: int | None = None
    superseded_by_title: str | None = None
    evidence: list[DecisionEvidenceReceipt]
    created_at: datetime | None = None


class DecisionCreatedResponse(BaseModel):
    id: int
    title: str
    status: DecisionStatus
    integrity: str
    created_at: datetime | None = None


class DecisionTransitionResponse(BaseModel):
    id: int
    status: DecisionStatus
    decided_at: datetime | None = None


class IntegrityCheckResponse(BaseModel):
    decision_id: int
    integrity: str
    integrity_checked_at: datetime | None = None
    reasons: list[IntegrityReason]


@router.post("", status_code=201, response_model=DecisionCreatedResponse)
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
            owner_id=body.owner_id,
            area=body.area,
            status=body.status.value,
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


@router.get("", response_model=DecisionListResponse)
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
                "integrity_checked_at": d.integrity_checked_at.isoformat() if d.integrity_checked_at else None,
                "owner_id": d.owner_id,
                "area": d.area,
                "decided_at": d.decided_at.isoformat() if d.decided_at else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in items
        ],
        "total": total,
    }


@router.get("/{decision_id}", response_model=DecisionDetailResponse)
async def get_decision(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a decision with its evidence receipts, linked hypothesis and successor title."""
    from app.services.decisions import (
        get_decision as _get,
    )
    from app.services.decisions import (
        get_decision_evidence,
        get_hypothesis_summary,
        get_superseded_by_title,
    )

    decision = await _get(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    evidence = await get_decision_evidence(db, decision_id)
    hypothesis = await get_hypothesis_summary(db, decision.hypothesis_id) if decision.hypothesis_id else None
    superseded_by_title = await get_superseded_by_title(db, decision.superseded_by)

    return {
        "id": decision.id,
        "title": decision.title,
        "rationale_md": decision.rationale_md,
        "status": decision.status,
        "integrity": decision.integrity,
        "integrity_reasons": (decision.integrity_reasons or {}).get("reasons") if isinstance(decision.integrity_reasons, dict) else decision.integrity_reasons,
        "integrity_checked_at": decision.integrity_checked_at.isoformat() if decision.integrity_checked_at else None,
        "hypothesis_id": decision.hypothesis_id,
        "hypothesis": hypothesis,
        "owner_id": decision.owner_id,
        "area": decision.area,
        "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
        "decided_by": decision.decided_by,
        "superseded_by": decision.superseded_by,
        "superseded_by_title": superseded_by_title,
        "evidence": evidence,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


@router.patch("/{decision_id}", response_model=DecisionDetailResponse)
async def update_decision(
    decision_id: int,
    body: DecisionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit a decision's title, rationale, owner or area."""
    from app.services.decisions import update_decision as _update

    try:
        await _update(
            db, decision_id,
            title=body.title, rationale_md=body.rationale_md,
            owner_id=body.owner_id, area=body.area,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await get_decision(decision_id, db, user)


@router.post("/{decision_id}/evidence/{highlight_id}", response_model=DecisionDetailResponse, status_code=201)
async def add_decision_evidence(
    decision_id: int,
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cite an existing highlight on a decision (e.g. from Explore or Hypotheses)."""
    from app.services.decisions import add_evidence

    try:
        await add_evidence(db, decision_id, highlight_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await get_decision(decision_id, db, user)


@router.delete("/{decision_id}/evidence/{highlight_id}", response_model=DecisionDetailResponse)
async def remove_decision_evidence(
    decision_id: int,
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Un-cite a highlight from a decision (non-draft decisions must keep >=1)."""
    from app.services.decisions import remove_evidence

    try:
        await remove_evidence(db, decision_id, highlight_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await get_decision(decision_id, db, user)


@router.patch("/{decision_id}/status", response_model=DecisionTransitionResponse)
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
            new_status=body.status.value,
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


@router.get("/{decision_id}/integrity", response_model=IntegrityCheckResponse)
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
