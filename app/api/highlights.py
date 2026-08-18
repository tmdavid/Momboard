"""Highlights API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import HighlightResponse, HighlightUpdate
from app.auth import get_current_user
from app.models import Highlight, User

router = APIRouter()


class BulkAcceptRequest(BaseModel):
    """Request body for bulk accept operations (#14)."""

    highlight_ids: list[int] = Field(default=[], description="Explicit IDs to accept")
    min_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Accept all suggested with confidence >= this"
    )
    tag_key: str | None = Field(
        default=None, description="Accept all suggested of this tag"
    )
    conversation_id: int | None = Field(
        default=None, description="Scope to a specific conversation"
    )


class BulkAcceptResponse(BaseModel):
    accepted_count: int
    accepted_ids: list[int]


@router.post("/bulk-accept", response_model=BulkAcceptResponse)
async def bulk_accept_highlights(
    body: BulkAcceptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Accept multiple highlights in one operation (#14).

    Supports:
    - Explicit list of IDs
    - All suggested >= min_confidence threshold
    - All suggested of a specific tag
    - Scoped to a conversation

    Atomic: either all succeed or the operation fails.
    """
    if body.highlight_ids:
        # Explicit IDs mode
        result = await db.execute(
            select(Highlight).where(
                Highlight.id.in_(body.highlight_ids),
                Highlight.status == "suggested",
            )
        )
        highlights = list(result.scalars().all())
        for h in highlights:
            h.status = "accepted"
        await db.commit()
        return BulkAcceptResponse(
            accepted_count=len(highlights),
            accepted_ids=[h.id for h in highlights],
        )

    # Filter-based mode
    query = select(Highlight).where(Highlight.status == "suggested")

    if body.conversation_id:
        query = query.where(Highlight.conversation_id == body.conversation_id)
    if body.min_confidence is not None:
        query = query.where(Highlight.confidence >= body.min_confidence)
    if body.tag_key:
        query = query.where(Highlight.tag_key == body.tag_key)

    # Must have at least one filter beyond status
    if body.min_confidence is None and body.tag_key is None and body.conversation_id is None:
        raise HTTPException(
            status_code=422,
            detail="Must specify highlight_ids, min_confidence, tag_key, or conversation_id",
        )

    result = await db.execute(query)
    highlights = list(result.scalars().all())
    for h in highlights:
        h.status = "accepted"
    await db.commit()

    return BulkAcceptResponse(
        accepted_count=len(highlights),
        accepted_ids=[h.id for h in highlights],
    )


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


@router.delete("/{highlight_id}", status_code=204)
async def delete_highlight(
    highlight_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a highlight.

    Returns 409 if the highlight is cited by any decision (evidence cannot be destroyed).
    """
    from app.services.decisions import check_highlight_cited

    highlight = await db.get(Highlight, highlight_id)
    if highlight is None:
        raise HTTPException(status_code=404, detail="Highlight not found")

    # Check if cited by decisions — block deletion (T40 requirement)
    citing_decisions = await check_highlight_cited(db, highlight_id)
    if citing_decisions:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Cannot delete highlight {highlight_id}: cited by decisions",
                "citing_decision_ids": citing_decisions,
            },
        )

    await db.delete(highlight)
    await db.flush()
