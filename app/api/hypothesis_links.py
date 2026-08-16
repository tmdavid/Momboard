"""Hypothesis link management endpoints (separate path: /api/hypothesis-links)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas import HypothesisLinkResponse, HypothesisLinkUpdate
from app.auth import get_current_user
from app.models import HypothesisLink, User

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_LINK_STATUSES = {"confirmed", "rejected"}


@router.patch("/{link_id}", response_model=HypothesisLinkResponse)
async def update_hypothesis_link(
    link_id: int,
    body: HypothesisLinkUpdate,
    request: Request,
    user: User = Depends(get_current_user),
) -> HypothesisLink:
    """Accept or reject a hypothesis link."""
    if body.status not in VALID_LINK_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid link status: {body.status}. Must be 'confirmed' or 'rejected'.",
        )

    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        link: HypothesisLink | None = await db.get(HypothesisLink, link_id)
        if link is None:
            raise HTTPException(status_code=404, detail="Hypothesis link not found")

        link.status = body.status
        await db.commit()
        await db.refresh(link)
        return link
