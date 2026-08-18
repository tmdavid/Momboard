"""T43: Segment lenses API routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import User

router = APIRouter()


class LensCreateRequest(BaseModel):
    a: dict = Field(description="Filter set for side A")
    b: dict = Field(description="Filter set for side B")
    label_a: str = "Side A"
    label_b: str = "Side B"


@router.post("", status_code=201)
async def create_lens(
    body: LensCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a segment lens comparing two filter sets.

    Returns 422 if either side has <5 highlights.
    """
    from app.llm.factory import create_llm_client
    from app.services.lenses import InsufficientEvidenceError
    from app.services.lenses import build_lens as _build_lens

    settings = request.app.state.settings
    llm = create_llm_client(settings)

    try:
        analysis = await _build_lens(
            db,
            filters_a=body.a,
            filters_b=body.b,
            label_a=body.label_a,
            label_b=body.label_b,
            llm=llm,
        )
        await db.commit()
        return {
            "id": analysis.id,
            "kind": analysis.kind,
            "input_scope": analysis.input_scope,
            "result": analysis.result,
        }
    except InsufficientEvidenceError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        await llm.close()


@router.get("/{lens_id}")
async def get_lens(
    lens_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a lens analysis by ID."""
    from sqlalchemy import select

    from app.models import Analysis

    result = await db.execute(
        select(Analysis).where(Analysis.id == lens_id, Analysis.kind == "lens")
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Lens not found")

    return {
        "id": analysis.id,
        "kind": analysis.kind,
        "input_scope": analysis.input_scope,
        "result": analysis.result,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }
