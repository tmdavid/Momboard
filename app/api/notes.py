"""Notes API endpoints."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import NoteResponse, NoteUpdate
from app.auth import get_current_user
from app.models import Conversation, Note, User, utcnow

router = APIRouter()


@router.get("/conversations/{conversation_id}/note")
async def get_note(
    conversation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get or create the note for a conversation."""
    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await db.execute(
        select(Note).where(Note.conversation_id == conversation_id)
    )
    note = result.scalar_one_or_none()

    if note is None:
        note = Note(conversation_id=conversation_id, body_md="", updated_by=user.id)
        db.add(note)
        await db.flush()

    return NoteResponse.model_validate(note)


@router.put("/conversations/{conversation_id}/note")
async def put_note(
    conversation_id: int,
    body: NoteUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the note with optimistic concurrency."""
    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await db.execute(
        select(Note).where(Note.conversation_id == conversation_id)
    )
    note = result.scalar_one_or_none()

    if note is None:
        note = Note(
            conversation_id=conversation_id,
            body_md=body.body_md,
            updated_by=user.id,
        )
        db.add(note)
        await db.flush()
        return NoteResponse.model_validate(note)

    # Optimistic concurrency check
    if note.updated_at and body.updated_at:
        # Ensure both are timezone-aware for comparison
        note_ts = note.updated_at
        body_ts = body.updated_at
        if note_ts.tzinfo is None:
            note_ts = note_ts.replace(tzinfo=UTC)
        if body_ts.tzinfo is None:
            body_ts = body_ts.replace(tzinfo=UTC)
        diff = abs((note_ts - body_ts).total_seconds())
        if diff > 1:
            raise HTTPException(
                status_code=409,
                detail="Note was modified by another user. Reload to see changes.",
            )

    note.body_md = body.body_md
    note.updated_by = user.id
    note.updated_at = utcnow()
    await db.flush()
    return NoteResponse.model_validate(note)
