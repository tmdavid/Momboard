"""Explore API: cross-conversation highlights + stats."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import HighlightsListResponse, HighlightWithContext, StatsResponse
from app.auth import get_current_user
from app.llm.tag_rules import EITHER_SIDE_TAGS
from app.models import (
    Analysis,
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Highlight,
    User,
    Utterance,
)
from app.services.confidence_floor import passes_floor
from app.services.text_filters import like_contains

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
    company: str | None = Query(default=None, description="Company name contains this text (case-insensitive)"),
    min_confidence: float | None = Query(
        default=None, ge=0.0, le=1.0, description="At least this confidence (accepted/manual highlights always pass)"
    ),
    customer_only: bool = Query(
        default=False,
        description="Drop highlights spoken by our side, except follow-up and commitment (which may be either)",
    ),
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
    if company and company.strip():
        query = query.where(Company.name.ilike(like_contains(company), escape="\\"))
    if date_from:
        query = query.where(Conversation.happened_at >= date_from)
    if date_to:
        query = query.where(Conversation.happened_at <= date_to)
    if min_confidence is not None:
        query = query.where(or_(Highlight.confidence.is_(None), Highlight.confidence >= min_confidence))
    if customer_only:
        query = query.where(_customer_only_clause())

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
    for highlight, convo, company_row in rows:
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
                company_name=company_row.name if company_row else None,
                contact_names=contact_names,
            )
        )

    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _customer_only_clause() -> ColumnElement[bool]:
    """Keep highlights that are not spoken by our side (follow-up and commitment may be either side)."""
    our_side = select(Utterance.id).where(Utterance.speaker_side == "us")
    return or_(
        Highlight.utterance_id.is_(None),
        Highlight.utterance_id.not_in(our_side),
        Highlight.tag_key.in_(tuple(EITHER_SIDE_TAGS)),
    )


def _since_clause(since: datetime | None) -> list[ColumnElement[bool]]:
    """Restrict stats to calls on or after ``since``: the call date, or when it was added if undated."""
    if since is None:
        return []
    return [func.coalesce(Conversation.happened_at, Conversation.created_at) >= since]


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    since: datetime | None = Query(
        default=None, description="Only calls on or after this date (by when the call happened)"
    ),
    customer_only: bool = Query(
        default=False, description="Count only highlights not spoken by our side (as the MCP tools do)"
    ),
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
            *_since_clause(since),
            *([_customer_only_clause()] if customer_only else []),
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
        select(
            Analysis.result,
            # v0.5 U8: trends follow when the call happened. A retag recreates every
            # analysis on one day, so the analysis date alone would flatten the trend.
            func.coalesce(Conversation.happened_at, Analysis.created_at),
            Analysis.conversation_id,
        )
        .join(Conversation, Analysis.conversation_id == Conversation.id)
        .where(
            Analysis.kind == "conversation",
            Conversation.source != "simulator",
            *_since_clause(since),
        )
        .order_by(Analysis.created_at)
    )
    analyses_rows = analyses_result.all()

    critique_trend: list[dict[str, Any]] = []
    compliment_ratio_trend: list[dict[str, Any]] = []
    followup_tasks: dict[int, str] = {}
    # Trends are averaged per week (v0.5 U8), one point per week rather than per call.
    _critique_by_week: dict[str, list[float]] = {}
    _compliment_by_week: dict[str, list[float]] = {}
    for result_data, created_at, convo_id in analyses_rows:
        if result_data and isinstance(result_data, dict):
            week_key = _week_start(created_at)
            critique = result_data.get("mom_test_critique", {})
            if isinstance(critique, dict) and "score" in critique and week_key:
                _critique_by_week.setdefault(week_key, []).append(float(critique["score"]))
            ratio = result_data.get("compliment_ratio")
            if ratio is not None and week_key:
                _compliment_by_week.setdefault(week_key, []).append(float(ratio))
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

    # Weekly trends, chronological. `date` is the Monday of the week (YYYY-MM-DD).
    for week in sorted(_critique_by_week):
        scores = _critique_by_week[week]
        critique_trend.append({
            "date": week,
            "score": round(sum(scores) / len(scores), 1),
        })
    for week in sorted(_compliment_by_week):
        ratios = _compliment_by_week[week]
        compliment_ratio_trend.append({
            "date": week,
            "ratio": sum(ratios) / len(ratios),
        })
    # Overall averages over every call, so a headline number never depends on which week is newest.
    all_scores = [s for week in _critique_by_week.values() for s in week]
    all_ratios = [r for week in _compliment_by_week.values() for r in week]

    # #1: a real conversation count (non-simulated). The frontend previously
    # derived this from the number of *months*, which read as "1".
    total_conversations = (
        await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.source != "simulator", *_since_clause(since))
        )
    ).scalar_one()

    return StatsResponse(
        total_conversations=total_conversations,
        tag_counts_by_month=tag_counts_by_month,
        critique_trend=critique_trend,
        compliment_ratio_trend=compliment_ratio_trend,
        avg_critique_score=round(sum(all_scores) / len(all_scores), 1) if all_scores else None,
        avg_compliment_ratio=(sum(all_ratios) / len(all_ratios)) if all_ratios else None,
        open_followups=followups,
        stale_hypotheses=await _count_stale_hypotheses(db),
    )


def _week_start(moment: datetime | None) -> str | None:
    """The Monday (YYYY-MM-DD) of the week containing ``moment``."""
    if moment is None:
        return None
    day = moment.date() if isinstance(moment, datetime) else moment
    return (day - timedelta(days=day.weekday())).isoformat()


async def _count_stale_hypotheses(db: AsyncSession) -> int:
    """Count open hypotheses with stale evidence (T41)."""
    from app.services.staleness import get_stale_hypotheses

    stale = await get_stale_hypotheses(db)
    return len(stale)
