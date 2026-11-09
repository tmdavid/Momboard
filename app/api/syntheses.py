"""Syntheses API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    SynthesisCreate,
    SynthesisListResponse,
    SynthesisResponse,
    SynthesisSaveUpdate,
)
from app.auth import get_current_user
from app.models import Analysis, Job, User

router = APIRouter()


def _response_for(analysis: Analysis, job: Job | None = None) -> SynthesisResponse:
    response = SynthesisResponse.model_validate(analysis)
    if analysis.result is not None:
        response.status = "done"
    elif job is not None:
        response.status = job.status
        if job.status == "error":
            response.error = "Synthesis failed. Please retry."
    return response


async def _latest_job_for(db: AsyncSession, synthesis_id: int) -> Job | None:
    job_result = await db.execute(
        select(Job)
        .where(
            Job.kind == "synthesize",
            Job.payload["analysis_id"].as_integer() == synthesis_id,
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return job_result.scalar_one_or_none()


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

    return _response_for(analysis, job)


@router.get("", response_model=SynthesisListResponse)
async def list_syntheses(
    request: Request,
    saved: bool | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List syntheses, newest first. Optionally filter by saved flag."""
    query = select(Analysis).where(Analysis.kind == "synthesis")
    if saved is not None:
        query = query.where(Analysis.saved == saved)
    query = query.order_by(Analysis.created_at.desc())

    result = await db.execute(query)
    analyses = result.scalars().all()

    # Batch-fetch the latest synthesize job per analysis to avoid N+1 lookups
    # while still deriving accurate queued/running/error status for pending rows.
    pending_ids = [a.id for a in analyses if a.result is None]
    latest_job_by_analysis: dict[int, Job] = {}
    if pending_ids:
        job_rows = await db.execute(
            select(Job).where(
                Job.kind == "synthesize",
                Job.payload["analysis_id"].as_integer().in_(pending_ids),
            )
        )
        for job in job_rows.scalars().all():
            aid = (job.payload or {}).get("analysis_id")
            if aid is None:
                continue
            existing = latest_job_by_analysis.get(aid)
            if existing is None or job.created_at > existing.created_at:
                latest_job_by_analysis[aid] = job

    items = [
        _response_for(a, None if a.result is not None else latest_job_by_analysis.get(a.id))
        for a in analyses
    ]
    return SynthesisListResponse(items=items, total=len(items))


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

    job = await _latest_job_for(db, synthesis_id)
    return _response_for(analysis, job)


@router.patch("/{synthesis_id}", response_model=SynthesisResponse)
async def update_synthesis(
    synthesis_id: int,
    body: SynthesisSaveUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save or unsave a synthesis (keep the ones you like)."""
    analysis = await db.get(Analysis, synthesis_id)
    if analysis is None or analysis.kind != "synthesis":
        raise HTTPException(status_code=404, detail="Synthesis not found")

    analysis.saved = body.saved
    await db.flush()

    job = await _latest_job_for(db, synthesis_id)
    return _response_for(analysis, job)


@router.delete("/{synthesis_id}", status_code=204)
async def delete_synthesis(
    synthesis_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Discard a synthesis and its associated synthesize jobs."""
    analysis = await db.get(Analysis, synthesis_id)
    if analysis is None or analysis.kind != "synthesis":
        raise HTTPException(status_code=404, detail="Synthesis not found")

    # Remove associated synthesize jobs so a discarded summary leaves no orphans.
    job_rows = await db.execute(
        select(Job).where(
            Job.kind == "synthesize",
            Job.payload["analysis_id"].as_integer() == synthesis_id,
        )
    )
    for job in job_rows.scalars().all():
        await db.delete(job)

    await db.delete(analysis)
    await db.flush()
    return None
