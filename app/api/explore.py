"""Explore API: cross-conversation highlights + stats."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
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

router = APIRouter()


@router.get("/highlights", response_model=HighlightsListResponse)
async def list_highlights(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tag: list[str] = Query(default=[]),
    company_id: int | None = None,
    status: str | None = None,
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
    if company_id:
        query = query.where(Conversation.company_id == company_id)
    if date_from:
        query = query.where(Conversation.happened_at >= date_from)
    if date_to:
        query = query.where(Conversation.happened_at <= date_to)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    query = query.order_by(Highlight.created_at.desc()).offset(offset).limit(limit)
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
    highlights_result = await db.execute(
        select(Highlight.tag_key, Highlight.created_at).where(
            Highlight.status.in_(["suggested", "accepted"])
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

    # Critique score trend
    analyses_result = await db.execute(
        select(Analysis.result, Analysis.created_at, Analysis.conversation_id)
        .where(Analysis.kind == "conversation")
        .order_by(Analysis.created_at)
    )
    analyses_rows = analyses_result.all()

    critique_trend: list[dict[str, Any]] = []
    compliment_ratio_trend: list[dict[str, Any]] = []
    for result_data, created_at, convo_id in analyses_rows:
        if result_data and isinstance(result_data, dict):
            critique = result_data.get("mom_test_critique", {})
            if isinstance(critique, dict) and "score" in critique:
                critique_trend.append({
                    "date": created_at.isoformat() if created_at else None,
                    "score": critique["score"],
                    "conversation_id": convo_id,
                })
            ratio = result_data.get("compliment_ratio")
            if ratio is not None:
                compliment_ratio_trend.append({
                    "date": created_at.isoformat() if created_at else None,
                    "ratio": ratio,
                    "conversation_id": convo_id,
                })

    # Open follow-ups
    followups_result = await db.execute(
        select(Highlight, Conversation)
        .join(Conversation, Highlight.conversation_id == Conversation.id)
        .where(
            Highlight.tag_key == "followup",
            Highlight.status.in_(["suggested", "accepted"]),
        )
        .order_by(Highlight.created_at.desc())
    )
    followups: list[dict[str, Any]] = [
        {
            "id": h.id,
            "quote": h.quote,
            "conversation_id": c.id,
            "conversation_title": c.title,
            "happened_at": c.happened_at.isoformat() if c.happened_at else None,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h, c in followups_result.all()
    ]

    return StatsResponse(
        tag_counts_by_month=tag_counts_by_month,
        critique_trend=critique_trend,
        compliment_ratio_trend=compliment_ratio_trend,
        open_followups=followups,
    )
