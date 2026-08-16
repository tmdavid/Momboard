"""Syntheses API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import SynthesisCreate, SynthesisResponse
from app.auth import get_current_user
from app.models import Analysis, Job, User

router = APIRouter()


@router.post("", status_code=201, response_model=SynthesisResponse)
async def create_synthesis(
    body: SynthesisCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a synthesis request, enqueue the job."""
    analysis = Analysis(
        kind="synthesis",
        input_scope=body.filters,
    )
    db.add(analysis)
    await db.flush()

    job = Job(
        kind="synthesize",
        payload={"analysis_id": analysis.id, "filters": body.filters},
        status="queued",
    )
    db.add(job)
    await db.flush()

    return SynthesisResponse.model_validate(analysis)


@router.get("/{synthesis_id}", response_model=SynthesisResponse)
async def get_synthesis(
    synthesis_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a synthesis result."""
    analysis = await db.get(Analysis, synthesis_id)
    if analysis is None or analysis.kind != "synthesis":
        raise HTTPException(status_code=404, detail="Synthesis not found")
    return SynthesisResponse.model_validate(analysis)
