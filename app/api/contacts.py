"""T29/T30: Contact and company timeline + drift API endpoints."""


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import (
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Highlight,
)
from app.services.contacts import (
    confirm_drift,
    dismiss_drift,
    get_contact_drifts,
    get_contact_timeline,
)

router = APIRouter()


# --- Schemas ---


class ContactDetailResponse(BaseModel):
    id: int
    name: str
    role: str | None = None
    email: str | None = None
    company_id: int | None = None
    company_name: str | None = None
    conversation_count: int = 0
    open_followups: int = 0
    last_talked: str | None = None

    model_config = {"from_attributes": True}


class TimelineEvent(BaseModel):
    kind: str
    timestamp: str
    conversation_id: int | None = None
    highlight_id: int | None = None
    title: str | None = None
    tag_key: str | None = None
    tag_emoji: str | None = None
    quote: str | None = None
    status: str | None = None


class TimelineResponse(BaseModel):
    events: list[TimelineEvent]


class DriftResponse(BaseModel):
    id: int
    contact_id: int
    earlier_highlight_id: int
    later_highlight_id: int
    kind: str
    summary: str | None = None
    status: str
    created_at: str

    model_config = {"from_attributes": True}


class DriftActionResponse(BaseModel):
    id: int
    status: str


# --- Contact endpoints ---


@router.get("/{contact_id}", response_model=ContactDetailResponse)
async def get_contact_detail(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get contact detail with stats."""
    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Get stats
    convo_ids_result = await db.execute(
        select(ConversationContact.conversation_id)
        .where(ConversationContact.contact_id == contact_id)
    )
    convo_ids = [r[0] for r in convo_ids_result.all()]
    conversation_count = len(convo_ids)

    # Open follow-ups
    open_followups = 0
    last_talked = None
    if convo_ids:
        followups_result = await db.execute(
            select(func.count(Highlight.id))
            .where(
                Highlight.conversation_id.in_(convo_ids),
                Highlight.tag_key == "followup",
                Highlight.status.in_(["accepted", "suggested"]),
            )
        )
        open_followups = followups_result.scalar() or 0

        last_convo_result = await db.execute(
            select(Conversation.happened_at)
            .where(Conversation.id.in_(convo_ids))
            .order_by(Conversation.happened_at.desc().nullslast())
            .limit(1)
        )
        last_row = last_convo_result.scalar_one_or_none()
        if last_row:
            last_talked = last_row.isoformat()

    # Company name
    company_name = None
    if contact.company_id:
        company = await db.get(Company, contact.company_id)
        if company:
            company_name = company.name

    return ContactDetailResponse(
        id=contact.id,
        name=contact.name,
        role=contact.role,
        email=contact.email,
        company_id=contact.company_id,
        company_name=company_name,
        conversation_count=conversation_count,
        open_followups=open_followups,
        last_talked=last_talked,
    )


@router.get("/{contact_id}/timeline", response_model=TimelineResponse)
async def contact_timeline(
    contact_id: int,
    kind: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get chronological timeline for a contact."""
    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    events = await get_contact_timeline(db, contact_id, kind_filter=kind, limit=limit)
    return TimelineResponse(events=events)


@router.get("/{contact_id}/drifts", response_model=list[DriftResponse])
async def contact_drifts(
    contact_id: int,
    include_dismissed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Get drift alerts for a contact."""
    contact = await db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    drifts = await get_contact_drifts(db, contact_id, include_dismissed=include_dismissed)
    return [
        DriftResponse(
            id=d.id,
            contact_id=d.contact_id,
            earlier_highlight_id=d.earlier_highlight_id,
            later_highlight_id=d.later_highlight_id,
            kind=d.kind,
            summary=d.summary,
            status=d.status,
            created_at=d.created_at.isoformat(),
        )
        for d in drifts
    ]


# --- Drift action endpoints ---


@router.post("/drifts/{drift_id}/dismiss", response_model=DriftActionResponse)
async def dismiss_drift_endpoint(
    drift_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a drift alert."""
    try:
        drift = await dismiss_drift(db, drift_id)
        await db.commit()
        return DriftActionResponse(id=drift.id, status=drift.status)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/drifts/{drift_id}/confirm", response_model=DriftActionResponse)
async def confirm_drift_endpoint(
    drift_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Confirm a drift alert."""
    try:
        drift = await confirm_drift(db, drift_id)
        await db.commit()
        return DriftActionResponse(id=drift.id, status=drift.status)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
