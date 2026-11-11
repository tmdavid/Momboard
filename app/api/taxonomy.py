"""Taxonomy versioning status (v0.5 D7): how many calls miss a tag, and rollout progress."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import User
from app.services.taxonomy_version import current_progress, stale_call_counts

router = APIRouter()


class StaleTag(BaseModel):
    key: str
    name: str
    added_in_version: int
    total_calls: int
    stale_calls: int


class StaleResponse(BaseModel):
    items: list[StaleTag]


class TaxonomyStatus(BaseModel):
    version: int
    total_calls: int
    calls_on_current: int
    tags: list[StaleTag]  # only tags some calls are missing


def _item(c) -> dict:
    return {
        "key": c.key, "name": c.name, "added_in_version": c.added_in_version,
        "total_calls": c.total_calls, "stale_calls": c.stale_calls,
    }


@router.get("/status", response_model=TaxonomyStatus)
async def taxonomy_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Taxonomy version, how many finished calls were tagged under it, and the tags some
    calls are missing (so Settings can say '312 of 1,000 calls are on the current taxonomy')."""
    version, total, on_current = await current_progress(db)
    counts = await stale_call_counts(db)
    return {
        "version": version,
        "total_calls": total,
        "calls_on_current": on_current,
        "tags": [_item(c) for c in counts.values() if c.stale_calls > 0],
    }


@router.get("/stale", response_model=StaleResponse)
async def stale_for_tags(
    tag: list[str] = Query(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """For the tags currently filtered on, how many calls were tagged before they existed."""
    counts = await stale_call_counts(db, tag) if tag else {}
    return {"items": [_item(c) for c in counts.values()]}
