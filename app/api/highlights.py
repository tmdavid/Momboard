"""Highlights API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import HighlightResponse, HighlightUpdate
from app.auth import get_current_user
from app.models import Highlight, User

router = APIRouter()


@router.patch("/{highlight_id}", response_model=HighlightResponse)
async def update_highlight(
    highlight_id: int,
    body: HighlightUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a highlight: accept, reject, edit tag, edit quote."""
    highlight = await db.get(Highlight, highlight_id)
    if highlight is None:
        raise HTTPException(status_code=404, detail="Highlight not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(highlight, key, value)

    await db.flush()
    return HighlightResponse.model_validate(highlight)
