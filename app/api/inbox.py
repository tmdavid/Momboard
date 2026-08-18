"""T34: Staging inbox API — list, import, ignore."""


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth import get_current_user

router = APIRouter()


class InboxItemResponse(BaseModel):
    id: int
    source: str
    source_ref: str
    title: str
    status: str
    parse_error: str | None = None
    conversation_id: int | None = None
    created_at: str

    model_config = {"from_attributes": True}


class InboxListResponse(BaseModel):
    items: list[InboxItemResponse]
    total: int


class ImportRequest(BaseModel):
    interviewer: str | None = None
    company_name: str | None = None
    contact_names: list[str] | None = None
    happened_at: str | None = None


class SubmitRequest(BaseModel):
    source: str
    source_ref: str
    title: str
    raw_content: str
    content_format: str | None = None
    meta: dict | None = None


@router.post("", response_model=InboxItemResponse, status_code=201)
async def submit_inbox_item(
    body: SubmitRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Submit a new item to the staging inbox."""
    from app.services import DuplicateSourceRefError, submit_to_inbox

    try:
        item = await submit_to_inbox(
            db,
            source=body.source,
            source_ref=body.source_ref,
            title=body.title,
            raw_content=body.raw_content,
            content_format=body.content_format,
            meta=body.meta,
        )
        await db.commit()
    except DuplicateSourceRefError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return InboxItemResponse(
        id=item.id,
        source=item.source,
        source_ref=item.source_ref,
        title=item.title,
        status=item.status,
        parse_error=item.parse_error,
        conversation_id=item.conversation_id,
        created_at=item.created_at.isoformat(),
    )


@router.get("", response_model=InboxListResponse)
async def list_inbox(
    status: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List inbox items with optional status/source filter."""
    from app.services import list_inbox_items

    items, total = await list_inbox_items(db, status=status, source=source, limit=limit, offset=offset)
    return InboxListResponse(
        items=[
            InboxItemResponse(
                id=item.id,
                source=item.source,
                source_ref=item.source_ref,
                title=item.title,
                status=item.status,
                parse_error=item.parse_error,
                conversation_id=item.conversation_id,
                created_at=item.created_at.isoformat(),
            )
            for item in items
        ],
        total=total,
    )


@router.post("/{item_id}/import", response_model=InboxItemResponse)
async def import_item(
    item_id: int,
    body: ImportRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Import an inbox item → create conversation + pipeline job."""
    from datetime import datetime

    from app.services import import_inbox_item

    happened_at = None
    if body.happened_at:
        try:
            happened_at = datetime.fromisoformat(body.happened_at)
        except ValueError:
            pass

    try:
        item = await import_inbox_item(
            db,
            item_id,
            interviewer=body.interviewer,
            company_name=body.company_name,
            contact_names=body.contact_names,
            happened_at=happened_at,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return InboxItemResponse(
        id=item.id,
        source=item.source,
        source_ref=item.source_ref,
        title=item.title,
        status=item.status,
        parse_error=item.parse_error,
        conversation_id=item.conversation_id,
        created_at=item.created_at.isoformat(),
    )


@router.post("/{item_id}/ignore", response_model=InboxItemResponse)
async def ignore_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Mark an inbox item as ignored."""
    from app.services import ignore_inbox_item

    try:
        item = await ignore_inbox_item(db, item_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return InboxItemResponse(
        id=item.id,
        source=item.source,
        source_ref=item.source_ref,
        title=item.title,
        status=item.status,
        parse_error=item.parse_error,
        conversation_id=item.conversation_id,
        created_at=item.created_at.isoformat(),
    )
