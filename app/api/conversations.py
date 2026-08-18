"""Conversations API endpoints."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_db
from app.api.schemas import (
    AnalysisResponse,
    CompanyResponse,
    ContactResponse,
    ConversationCreate,
    ConversationCreateResponse,
    ConversationDetail,
    ConversationListItem,
    ConversationListResponse,
    ConversationStatusResponse,
    ConversationUpdate,
    HighlightResponse,
    UtteranceResponse,
)
from app.auth import get_current_user
from app.models import (
    Analysis,
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Highlight,
    Job,
    User,
)

router = APIRouter()


async def _get_or_create_company(db: AsyncSession, name: str, domain: str | None = None) -> Company:
    """Get or create a company by name (case-insensitive)."""
    result = await db.execute(select(Company).where(func.lower(Company.name) == name.lower()))
    company = result.scalar_one_or_none()
    if company is None:
        company = Company(name=name, domain=domain)
        db.add(company)
        await db.flush()
    return company


async def _get_or_create_contact(
    db: AsyncSession, name: str, role: str | None = None, company_id: int | None = None
) -> Contact:
    """Get or create a contact by name."""
    result = await db.execute(select(Contact).where(Contact.name == name))
    contact = result.scalar_one_or_none()
    if contact is None:
        contact = Contact(name=name, role=role, company_id=company_id)
        db.add(contact)
        await db.flush()
    return contact


@router.post("", status_code=201, response_model=ConversationCreateResponse)
async def create_conversation(
    body: ConversationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a conversation and enqueue ingest pipeline."""
    company_id = None
    if body.company:
        company = await _get_or_create_company(db, body.company.name, body.company.domain)
        company_id = company.id

    convo = Conversation(
        title=body.title,
        happened_at=body.happened_at,
        interviewer=body.interviewer,
        company_id=company_id,
        raw_transcript=body.transcript,
        transcript_format=body.transcript_format or "auto",
        meta=body.meta,
        status="processing",
        source="upload",
    )
    db.add(convo)
    await db.flush()

    # Link contacts
    for c in body.contacts:
        contact = await _get_or_create_contact(db, c.name, c.role, company_id)
        db.add(ConversationContact(conversation_id=convo.id, contact_id=contact.id))

    # Enqueue ingest job
    job = Job(
        conversation_id=convo.id,
        kind="ingest",
        payload={"conversation_id": convo.id},
        status="queued",
    )
    db.add(job)
    await db.flush()

    return {
        "id": convo.id,
        "title": convo.title,
        "status": convo.status,
        "created_at": convo.created_at.isoformat() if convo.created_at else None,
    }


@router.post("/upload", status_code=201)
async def upload_audio(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    file: UploadFile = File(...),
    title: str = Form(...),
    interviewer: str | None = Form(default=None),
    language: str | None = Form(default=None),
):
    """Upload an audio/video file, transcribe via Whisper, and create a conversation."""
    from app.transcribe import (
        MAX_FILE_SIZE,
        SUPPORTED_EXTENSIONS,
        TranscriptionError,
        transcribe_audio,
    )

    # Validate file extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Accepted: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"File exceeds {MAX_FILE_SIZE // (1024 * 1024)} MB limit",
        )

    # Transcribe
    try:
        transcript = await transcribe_audio(
            file_content=content,
            filename=file.filename or "audio.mp3",
            content_type=file.content_type or "application/octet-stream",
            language=language,
        )
    except TranscriptionError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Create conversation with the transcribed text
    convo = Conversation(
        title=title,
        interviewer=interviewer,
        raw_transcript=transcript,
        transcript_format="vtt",
        meta={"source_filename": file.filename, "language": language},
        status="processing",
        source="audio_upload",
    )
    db.add(convo)
    await db.flush()

    # Enqueue ingest job
    job = Job(
        conversation_id=convo.id,
        kind="ingest",
        payload={"conversation_id": convo.id},
        status="queued",
    )
    db.add(job)
    await db.flush()

    return {
        "id": convo.id,
        "title": convo.title,
        "status": convo.status,
        "created_at": convo.created_at.isoformat() if convo.created_at else None,
        "transcript_preview": transcript[:500],
    }


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    company_id: int | None = None,
    status: str | None = None,
    tag: list[str] = Query(default=[]),
    q: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    deal_stage: str | None = None,
):
    """List conversations with filtering.

    The `tag` parameter supports repeated query params for AND filtering:
    ?tag=pain&tag=workaround returns conversations having BOTH tags.
    """
    query = select(Conversation).options(
        selectinload(Conversation.company),
        selectinload(Conversation.contacts),
    )

    # T39: Library list excludes simulated conversations (direct detail still allowed)
    query = query.where(Conversation.source != "simulator")

    # Apply filters
    if company_id:
        query = query.where(Conversation.company_id == company_id)
    if status:
        query = query.where(Conversation.status == status)
    if date_from:
        query = query.where(Conversation.happened_at >= date_from)
    if date_to:
        query = query.where(Conversation.happened_at <= date_to)
    if q:
        like_q = f"%{q}%"
        query = query.where(
            Conversation.title.ilike(like_q) | Conversation.raw_transcript.ilike(like_q)
        )
    if deal_stage:
        # Filter by meta.deal_stage JSON path — portable across SQLite/Postgres
        query = query.where(Conversation.meta["deal_stage"].as_string() == deal_stage)
    if tag:
        # Flatten any comma-separated values and apply AND logic:
        # conversation must have highlights for ALL specified tags
        tag_keys: list[str] = []
        for t in tag:
            tag_keys.extend(part.strip() for part in t.split(",") if part.strip())
        for tag_key in tag_keys:
            query = query.where(
                Conversation.id.in_(
                    select(Highlight.conversation_id).where(
                        Highlight.tag_key == tag_key,
                        Highlight.status.in_(["suggested", "accepted"]),
                    )
                )
            )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    # Paginate and order
    query = query.order_by(Conversation.happened_at.desc().nullslast()).offset(offset).limit(limit)
    result = await db.execute(query)
    conversations = result.scalars().all()

    # Build response with tag counts and critique scores
    items = []
    for convo in conversations:
        # Get tag counts for this conversation
        tag_counts_result = await db.execute(
            select(Highlight.tag_key, func.count(Highlight.id))
            .where(
                Highlight.conversation_id == convo.id,
                Highlight.status.in_(["suggested", "accepted"]),
            )
            .group_by(Highlight.tag_key)
        )
        tag_counts: dict[str, int] = {row[0]: row[1] for row in tag_counts_result.all()}

        # Get critique score
        critique_score = None
        analysis_result = await db.execute(
            select(Analysis.result)
            .where(Analysis.conversation_id == convo.id, Analysis.kind == "conversation")
            .order_by(Analysis.created_at.desc())
            .limit(1)
        )
        analysis_row = analysis_result.scalar_one_or_none()
        if analysis_row and isinstance(analysis_row, dict):
            critique = analysis_row.get("mom_test_critique", {})
            if isinstance(critique, dict):
                critique_score = critique.get("score")

        items.append(
            ConversationListItem(
                id=convo.id,
                title=convo.title,
                happened_at=convo.happened_at,
                status=convo.status,
                interviewer=convo.interviewer,
                company=CompanyResponse.model_validate(convo.company) if convo.company else None,
                contacts=[ContactResponse.model_validate(c) for c in convo.contacts],
                meta=convo.meta,
                created_at=convo.created_at,
                tag_counts=tag_counts,
                critique_score=critique_score,
            )
        )

    return ConversationListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get full conversation detail."""
    result = await db.execute(
        select(Conversation)
        .options(
            selectinload(Conversation.company),
            selectinload(Conversation.contacts),
            selectinload(Conversation.utterances),
            selectinload(Conversation.highlights),
            selectinload(Conversation.analyses),
        )
        .where(Conversation.id == conversation_id)
    )
    convo = result.scalar_one_or_none()
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetail(
        id=convo.id,
        title=convo.title,
        happened_at=convo.happened_at,
        status=convo.status,
        source=convo.source,
        interviewer=convo.interviewer,
        company=CompanyResponse.model_validate(convo.company) if convo.company else None,
        contacts=[ContactResponse.model_validate(c) for c in convo.contacts],
        meta=convo.meta,
        created_at=convo.created_at,
        utterances=sorted(
            [UtteranceResponse.model_validate(u) for u in convo.utterances], key=lambda u: u.idx
        ),
        highlights=[HighlightResponse.model_validate(h) for h in convo.highlights],
        analyses=[AnalysisResponse.model_validate(a) for a in convo.analyses],
    )


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    body: ConversationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update conversation metadata."""
    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(convo, key, value)

    await db.flush()
    return {"id": convo.id, "status": "updated"}


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a conversation and all related data (cascades)."""
    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(convo)
    await db.flush()


@router.post("/{conversation_id}/reprocess", response_model=ConversationStatusResponse)
async def reprocess_conversation(
    conversation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-run tag + analyze pipeline. Preserves accepted/rejected highlights."""
    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Delete only AI-suggested (not accepted/rejected by human)
    await db.execute(
        delete(Highlight).where(
            Highlight.conversation_id == conversation_id,
            Highlight.origin == "ai",
            Highlight.status == "suggested",
        )
    )

    # Enqueue tag job (will chain to analyze)
    job = Job(
        conversation_id=conversation_id,
        kind="tag",
        payload={"conversation_id": conversation_id},
        status="queued",
    )
    db.add(job)
    await db.flush()

    convo.status = "processing"
    return {"id": convo.id, "status": "processing"}


@router.post("/{conversation_id}/highlights", status_code=201, response_model=HighlightResponse)
async def create_highlight(
    conversation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a manual highlight."""
    from app.api.schemas import HighlightCreate

    body = HighlightCreate(**(await request.json()))

    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    highlight = Highlight(
        conversation_id=conversation_id,
        utterance_id=body.utterance_id,
        tag_key=body.tag_key,
        quote=body.quote,
        note=body.note,
        confidence=body.confidence or 1.0,
        origin="human",
        status="accepted",
        created_by=user.id,
    )
    db.add(highlight)
    await db.flush()
    return HighlightResponse.model_validate(highlight)


@router.get("/{conversation_id}/events")
async def conversation_events(
    conversation_id: int,
    request: Request,
    user: User = Depends(get_current_user),
):
    """SSE stream of job state transitions for a conversation.

    Only emits each transition once (transition-only). Terminates with a 'done'
    event when the conversation reaches a terminal state (ready/failed/partial).
    """

    async def event_generator():
        session_factory = request.app.state.session_factory
        emitted: set[str] = set()  # Track already-sent event keys

        while True:
            if await request.is_disconnected():
                return
            async with session_factory() as db:
                result = await db.execute(
                    select(Job)
                    .where(Job.conversation_id == conversation_id)
                    .order_by(Job.created_at)
                )
                jobs = result.scalars().all()

                convo = await db.get(Conversation, conversation_id)
                current_status = convo.status if convo else "unknown"

                # Emit only NEW transitions
                for job in jobs:
                    event_key = f"{job.kind}.{job.status}"
                    if event_key not in emitted:
                        emitted.add(event_key)
                        event_data = json.dumps({"kind": job.kind, "status": job.status})
                        yield {"event": event_key, "data": event_data}

                # Terminal states
                if current_status in ("ready", "failed", "partial"):
                    done_key = "done"
                    if done_key not in emitted:
                        emitted.add(done_key)
                        yield {
                            "event": "done",
                            "data": json.dumps({"status": current_status}),
                        }
                    return

            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
