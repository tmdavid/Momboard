"""Explore API: cross-conversation highlights + stats."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import HighlightsListResponse, HighlightWithContext, StatsResponse
from app.auth import get_current_user
from app.models import (
    Analysis,
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Highlight,
    User,
)
from app.services.confidence_floor import passes_floor

router = APIRouter()


@router.get("/highlights", response_model=HighlightsListResponse)
async def list_highlights(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tag: list[str] = Query(default=[]),
    company_id: int | None = None,
    status: str | None = None,
    q: str | None = Query(default=None, description="Case-insensitive text search in the quote"),
    floor: bool = Query(
        default=False,
        description="Hide suggestions below their tag's confidence floor (accepted ones always show)",
    ),
    sort: str = Query(
        default="recent",
        pattern="^(recent|confidence)$",
        description="recent (default) or confidence (strongest first)",
    ),
    per_call_cap: int = Query(
        default=0,
        ge=0,
        le=50,
        description="Show at most this many highlights per call per tag (0 = no cap)",
    ),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List highlights across all conversations with context.

    The `tag` parameter supports repeated query params:
    ?tag=pain&tag=workaround returns highlights matching ANY of the given tags (OR).
    """
    query = (
        select(Highlight, Conversation, Company)
        .join(Conversation, Highlight.conversation_id == Conversation.id)
        .outerjoin(Company, Conversation.company_id == Company.id)
        .where(Conversation.source != "simulator")  # T39: exclude simulated
    )

    # Default: exclude rejected
    if status:
        query = query.where(Highlight.status == status)
    else:
        query = query.where(Highlight.status.in_(["suggested", "accepted"]))

    if tag:
        # Flatten any comma-separated values
        tag_keys: list[str] = []
        for t in tag:
            tag_keys.extend(part.strip() for part in t.split(",") if part.strip())
        # OR logic: highlight must belong to one of the requested tags
        query = query.where(Highlight.tag_key.in_(tag_keys))
    if q and q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Highlight.quote.ilike(f"%{needle}%", escape="\\"))
    if company_id:
        query = query.where(Conversation.company_id == company_id)
    if date_from:
        query = query.where(Conversation.happened_at >= date_from)
    if date_to:
        query = query.where(Conversation.happened_at <= date_to)

    if floor:
        query = query.where(passes_floor())

    order: list[ColumnElement[Any]]
    if sort == "confidence":
        # Strongest first; nulls last, then newest, so the order is stable for paging.
        order = [
            Highlight.confidence.desc().nullslast(),
            Highlight.created_at.desc(),
            Highlight.id.desc(),
        ]
    else:
        order = [Highlight.created_at.desc(), Highlight.id.desc()]

    if per_call_cap:
        # Rank each highlight within its (call, tag) group and keep the top N, so one long call
        # cannot fill the first screen. Done before counting/paging so both reflect the cap.
        rank = (
            func.row_number()
            .over(
                partition_by=(Highlight.conversation_id, Highlight.tag_key),
                order_by=(
                    Highlight.confidence.desc().nullslast(),
                    Highlight.created_at.desc(),
                    Highlight.id.desc(),
                ),
            )
            .label("rank_in_call")
        )
        ranked = query.add_columns(rank).subquery()
        keep = select(ranked.c.id).where(ranked.c.rank_in_call <= per_call_cap)
        # `query` selects Highlight first, so its first column is the highlight id.
        query = query.where(Highlight.id.in_(keep))

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(*order).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    items = []
    for highlight, convo, company in rows:
        # Get contact names for this conversation
        contacts_result = await db.execute(
            select(Contact.name)
            .join(ConversationContact, Contact.id == ConversationContact.contact_id)
            .where(ConversationContact.conversation_id == convo.id)
        )
        contact_names = [r[0] for r in contacts_result.all()]

        items.append(
            HighlightWithContext(
                id=highlight.id,
                conversation_id=highlight.conversation_id,
                utterance_id=highlight.utterance_id,
                tag_key=highlight.tag_key,
                quote=highlight.quote,
                confidence=highlight.confidence,
                status=highlight.status,
                origin=highlight.origin,
                conversation_title=convo.title,
                conversation_happened_at=convo.happened_at,
                company_name=company.name if company else None,
                contact_names=contact_names,
            )
        )

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get aggregated stats: tag counts by month, critique trend, etc."""
    # Tag counts by month — dialect-portable, done in Python
    # T39: exclude simulated conversations from corpus-level stats
    highlights_result = await db.execute(
        select(Highlight.tag_key, Highlight.created_at)
        .join(Conversation, Highlight.conversation_id == Conversation.id)
        .where(
            Highlight.status.in_(["suggested", "accepted"]),
            Conversation.source != "simulator",
            passes_floor(),  # v0.5 D4
        )
    )
    highlights_rows = highlights_result.all()

    tag_counts_by_month: dict[str, dict[str, int]] = {}
    for tag_key, created_at in highlights_rows:
        if created_at:
            month_key = created_at.strftime("%Y-%m")
            if month_key not in tag_counts_by_month:
                tag_counts_by_month[month_key] = {}
            tag_counts_by_month[month_key][tag_key] = (
                tag_counts_by_month[month_key].get(tag_key, 0) + 1
            )

    # Critique score trend (exclude simulated)
    analyses_result = await db.execute(
        select(Analysis.result, Analysis.created_at, Analysis.conversation_id)
        .join(Conversation, Analysis.conversation_id == Conversation.id)
        .where(
            Analysis.kind == "conversation",
            Conversation.source != "simulator",
        )
        .order_by(Analysis.created_at)
    )
    analyses_rows = analyses_result.all()

    critique_trend: list[dict[str, Any]] = []
    compliment_ratio_trend: list[dict[str, Any]] = []
    followup_tasks: dict[int, str] = {}
    # #2: aggregate trends by month (avg per month) instead of one point per
    # conversation — otherwise N conversations in the same month render as N
    # points all labelled the same month.
    _critique_by_month: dict[str, list[float]] = {}
    _compliment_by_month: dict[str, list[float]] = {}
    for result_data, created_at, convo_id in analyses_rows:
        if result_data and isinstance(result_data, dict):
            month_key = created_at.strftime("%Y-%m") if created_at else None
            critique = result_data.get("mom_test_critique", {})
            if isinstance(critique, dict) and "score" in critique and month_key:
                _critique_by_month.setdefault(month_key, []).append(float(critique["score"]))
            ratio = result_data.get("compliment_ratio")
            if ratio is not None and month_key:
                _compliment_by_month.setdefault(month_key, []).append(float(ratio))
            commitments = result_data.get("commitments", [])
            if isinstance(commitments, list):
                for commitment in commitments:
                    if not isinstance(commitment, dict):
                        continue
                    task = commitment.get("next_step") or commitment.get("what")
                    evidence_ids = commitment.get("evidence_highlight_ids", [])
                    if not isinstance(task, str) or not task.strip() or not isinstance(evidence_ids, list):
                        continue
                    for highlight_id in evidence_ids:
                        if isinstance(highlight_id, int):
                            followup_tasks[highlight_id] = task.strip()

    # Open follow-ups (exclude simulated). Keep the verbatim quote as evidence,
    # but prefer the analyst's evidence-linked actionable task for display.
    followups_result = await db.execute(
        select(Highlight, Conversation)
        .join(Conversation, Highlight.conversation_id == Conversation.id)
        .where(
            Highlight.tag_key == "followup",
            Highlight.status.in_(["suggested", "accepted"]),
            Conversation.source != "simulator",
        )
        .order_by(Highlight.created_at.desc())
    )
    followups: list[dict[str, Any]] = [
        {
            "id": h.id,
            "task": followup_tasks.get(h.id, h.quote),
            "quote": h.quote,
            "conversation_id": c.id,
            "conversation_title": c.title,
            "happened_at": c.happened_at.isoformat() if c.happened_at else None,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h, c in followups_result.all()
    ]

    # Materialize month-averaged trends, chronologically ordered. `date` is
    # "YYYY-MM"; the frontend slices to the month for the axis label.
    for month in sorted(_critique_by_month):
        scores = _critique_by_month[month]
        critique_trend.append({
            "date": month,
            "score": round(sum(scores) / len(scores), 1),
        })
    for month in sorted(_compliment_by_month):
        ratios = _compliment_by_month[month]
        compliment_ratio_trend.append({
            "date": month,
            "ratio": sum(ratios) / len(ratios),
        })

    # #1: a real conversation count (non-simulated). The frontend previously
    # derived this from the number of *months*, which read as "1".
    total_conversations = (
        await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.source != "simulator")
        )
    ).scalar_one()

    return StatsResponse(
        total_conversations=total_conversations,
        tag_counts_by_month=tag_counts_by_month,
        critique_trend=critique_trend,
        compliment_ratio_trend=compliment_ratio_trend,
        open_followups=followups,
        stale_hypotheses=await _count_stale_hypotheses(db),
    )


async def _count_stale_hypotheses(db: AsyncSession) -> int:
    """Count open hypotheses with stale evidence (T41)."""
    from app.services.staleness import get_stale_hypotheses

    stale = await get_stale_hypotheses(db)
    return len(stale)
