"""T31: Digest preview + settings API."""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user

router = APIRouter()


class DigestPreviewResponse(BaseModel):
    markdown: str
    week_of: str


@router.get("/preview", response_model=DigestPreviewResponse)
async def digest_preview(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Preview the digest for the current week (no delivery, no persistence)."""
    from app.config import get_settings
    from app.llm.factory import create_llm_client
    from app.services.digest import build_digest, gather_digest_snapshot

    settings = get_settings()
    llm = create_llm_client(settings, agent="digest")
    try:
        week_of = date.today()
        snapshot = await gather_digest_snapshot(db, week_of, llm=llm)
        md = build_digest(snapshot, week_of)
    finally:
        await llm.close()

    return DigestPreviewResponse(
        markdown=md or "(Empty digest — no notable activity this week.)",
        week_of=week_of.isoformat(),
    )
