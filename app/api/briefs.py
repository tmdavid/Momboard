"""T38: Pre-call briefs API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import Contact

router = APIRouter()


class BriefResponse(BaseModel):
    id: int
    contact_id: int
    is_first_call: bool = False
    known_facts: list[dict[str, Any]] = []
    suggested_questions: list[str] = []
    watch_out: str | None = None
    open_followups: list[dict[str, Any]] = []
    open_drifts: list[dict[str, Any]] = []
    stale_hypotheses: list[dict[str, Any]] = []

    model_config = {"from_attributes": True}


@router.get("/{contact_id}/brief", response_model=BriefResponse)
async def get_contact_brief(
    contact_id: int,
    request: Request,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get or generate a pre-call brief for a contact."""
    from app.config import get_settings
    from app.llm.factory import create_llm_client
    from app.services.briefs import build_brief

    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    settings = get_settings()
    llm = create_llm_client(settings, agent="brief")
    try:
        analysis = await build_brief(db, contact_id, llm=llm, force_refresh=refresh)
        await db.commit()
    finally:
        if hasattr(llm, "close"):
            await llm.close()

    result = analysis.result or {}
    return BriefResponse(
        id=analysis.id,
        contact_id=contact_id,
        is_first_call=result.get("is_first_call", False),
        known_facts=result.get("known_facts", []),
        suggested_questions=result.get("suggested_questions", []),
        watch_out=result.get("watch_out"),
        open_followups=result.get("open_followups", []),
        open_drifts=result.get("open_drifts", []),
        stale_hypotheses=result.get("stale_hypotheses", []),
    )
