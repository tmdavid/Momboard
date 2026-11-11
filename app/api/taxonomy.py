"""Taxonomy versioning status (v0.5 D7): how many calls miss a tag, and rollout progress."""

import math
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user, require_admin
from app.models import Conversation, Job, User
from app.services.retag import count_eligible, retag_batch
from app.services.tag_snapshot import compare_to_snapshot, save_snapshot
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
    # Retag rollout (R1)
    eligible: int = 0                 # calls a retag would pick up now
    in_progress: int = 0              # calls currently being (re)processed
    seconds_per_call: float | None = None   # measured from finished tag+analyze jobs
    estimated_minutes: int | None = None    # eligible calls x seconds_per_call / workers


class RetagRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    dry_run: bool = False


class RetagResponse(BaseModel):
    queued: int
    would_queue: int
    remaining: int
    ids: list[int]
    protected_highlights: int  # suggestions kept because a decision or confirmed belief depends on them
    taxonomy_version: int


def _item(c) -> dict:
    return {
        "key": c.key, "name": c.name, "added_in_version": c.added_in_version,
        "total_calls": c.total_calls, "stale_calls": c.stale_calls,
    }


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


async def _seconds_per_call(db: AsyncSession) -> float | None:
    """Average wall time to tag + analyze one call, from recently finished jobs."""
    rows = await db.execute(
        select(Job.conversation_id, Job.kind, Job.started_at, Job.finished_at)
        .where(
            Job.kind.in_(["tag", "analyze"]),
            Job.status == "done",
            Job.started_at.is_not(None),
            Job.finished_at.is_not(None),
            Job.conversation_id.is_not(None),
        )
        .order_by(Job.finished_at.desc())
        .limit(600)
    )
    per_call: dict[int, dict[str, float]] = {}
    for conversation_id, kind, started, finished in rows.all():
        seconds = (_naive(finished) - _naive(started)).total_seconds()
        per_call.setdefault(conversation_id, {}).setdefault(kind, seconds)
    totals = [sum(v.values()) for v in per_call.values() if {"tag", "analyze"} <= v.keys()]
    return sum(totals) / len(totals) if totals else None


@router.get("/status", response_model=TaxonomyStatus)
async def taxonomy_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Taxonomy version, rollout progress ('312 of 1,000 calls are on the current taxonomy'), the
    tags some calls are missing, and a measured time estimate for the calls still to retag."""
    version, total, on_current = await current_progress(db)
    counts = await stale_call_counts(db)
    eligible = await count_eligible(db)
    in_progress = (
        await db.execute(
            select(func.count()).select_from(Conversation).where(
                Conversation.status == "processing", Conversation.source != "simulator"
            )
        )
    ).scalar_one()
    per_call = await _seconds_per_call(db)
    workers = max(1, int(getattr(request.app.state.settings, "worker_concurrency", 1) or 1))
    return {
        "version": version,
        "total_calls": total,
        "calls_on_current": on_current,
        "tags": [_item(c) for c in counts.values() if c.stale_calls > 0],
        "eligible": eligible,
        "in_progress": in_progress,
        "seconds_per_call": per_call,
        "estimated_minutes": math.ceil(eligible * per_call / workers / 60) if per_call and eligible else None,
    }


@router.post("/retag", response_model=RetagResponse)
async def retag(
    body: RetagRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Queue the next batch of calls for re-tagging, newest first (admin only).

    Resumable: only calls not yet on the current taxonomy are picked up, and a call already being
    processed is never queued twice, so running this again simply continues. Each call spends LLM
    tokens, so start with a small batch. ``dry_run`` reports what would be queued and changes nothing.
    """
    result = await retag_batch(db, body.limit, body.dry_run)
    return result.__dict__


@router.get("/stale", response_model=StaleResponse)
async def stale_for_tags(
    tag: list[str] = Query(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """For the tags currently filtered on, how many calls were tagged before they existed."""
    counts = await stale_call_counts(db, tag) if tag else {}
    return {"items": [_item(c) for c in counts.values()]}


class SnapshotRequest(BaseModel):
    label: str = Field(default="before retag", max_length=100)


class SnapshotResponse(BaseModel):
    label: str
    taken_at: str
    counts: dict[str, int]


class CompareRow(BaseModel):
    key: str
    name: str
    before: int
    after: int
    delta: int
    pct: int | None = None
    flag: str | None = None  # new | vanished | jumped | dropped


class CompareSnapshot(BaseModel):
    label: str | None = None
    taken_at: str | None = None


class CompareResponse(BaseModel):
    snapshot: CompareSnapshot | None = None
    rows: list[CompareRow] = Field(default_factory=list)
    flagged: int = 0


@router.post("/snapshot", response_model=SnapshotResponse)
async def take_snapshot(
    body: SnapshotRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Record today's tag counts (admin only) so they can be compared after a retag pilot."""
    return await save_snapshot(db, body.label)


@router.get("/compare", response_model=CompareResponse)
async def compare_snapshot(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Tag counts now vs the last snapshot. Flags tags that jumped, dropped, vanished or are new."""
    return await compare_to_snapshot(db)
