"""T34: Staging inbox service — pending_import/ignored/imported/parse_error lifecycle."""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Job,
    StagingInboxItem,
    utcnow,
)

logger = logging.getLogger(__name__)


class DuplicateSourceRefError(Exception):
    """Raised when a source_ref already exists in the inbox."""

    def __init__(self, source_ref: str, existing_id: int):
        self.source_ref = source_ref
        self.existing_id = existing_id
        super().__init__(f"source_ref '{source_ref}' already exists (id={existing_id})")


async def submit_to_inbox(
    db: AsyncSession,
    *,
    source: str,
    source_ref: str,
    title: str,
    raw_content: str,
    content_format: str | None = None,
    meta: dict | None = None,
    status: str = "pending_import",
    parse_error: str | None = None,
) -> StagingInboxItem:
    """Submit a new item to the staging inbox with source_ref dedupe.

    If the source_ref already exists, raises DuplicateSourceRefError.
    Handles both read-first dedupe and DB constraint violation (concurrent race).
    Items with parse errors are stored with status='parse_error'.
    """
    from sqlalchemy.exc import IntegrityError

    # Dedupe check (optimistic)
    existing = await db.execute(
        select(StagingInboxItem).where(StagingInboxItem.source_ref == source_ref).limit(1)
    )
    item = existing.scalar_one_or_none()
    if item is not None:
        raise DuplicateSourceRefError(source_ref, item.id)

    inbox_item = StagingInboxItem(
        source=source,
        source_ref=source_ref,
        title=title,
        raw_content=raw_content,
        content_format=content_format,
        meta=meta,
        status=status,
        parse_error=parse_error,
    )
    db.add(inbox_item)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        # Re-read after conflict
        existing2 = await db.execute(
            select(StagingInboxItem).where(StagingInboxItem.source_ref == source_ref).limit(1)
        )
        conflict_item = existing2.scalar_one_or_none()
        existing_id = conflict_item.id if conflict_item else 0
        raise DuplicateSourceRefError(source_ref, existing_id)

    return inbox_item


async def import_inbox_item(
    db: AsyncSession,
    item_id: int,
    *,
    interviewer: str | None = None,
    company_name: str | None = None,
    contact_names: list[str] | None = None,
    happened_at: datetime | None = None,
) -> StagingInboxItem:
    """Import an inbox item → create conversation + enqueue ingest pipeline.

    Only items in 'pending_import' or 'parse_error' status can be imported.
    """
    item = await db.get(StagingInboxItem, item_id)
    if item is None:
        raise ValueError(f"Inbox item {item_id} not found")

    if item.status not in ("pending_import", "parse_error"):
        raise ValueError(
            f"Cannot import item with status '{item.status}' (must be pending_import or parse_error)"
        )

    # Resolve or create company
    company_id = None
    if company_name:
        result = await db.execute(
            select(Company).where(Company.name == company_name).limit(1)
        )
        company = result.scalar_one_or_none()
        if company is None:
            company = Company(name=company_name)
            db.add(company)
            await db.flush()
        company_id = company.id

    # Create conversation
    convo = Conversation(
        title=item.title,
        company_id=company_id,
        happened_at=happened_at or (item.meta or {}).get("happened_at"),
        source=item.source,
        interviewer=interviewer,
        raw_transcript=item.raw_content,
        transcript_format=item.content_format,
        meta=item.meta,
        status="processing",
    )
    db.add(convo)
    await db.flush()

    # Resolve or create contacts
    if contact_names:
        for cname in contact_names:
            contact_result = await db.execute(
                select(Contact).where(Contact.name == cname).limit(1)
            )
            contact = contact_result.scalar_one_or_none()
            if contact is None:
                contact = Contact(name=cname, company_id=company_id)
                db.add(contact)
                await db.flush()
            db.add(
                ConversationContact(
                    conversation_id=convo.id, contact_id=contact.id
                )
            )
        await db.flush()

    # Enqueue ingest job
    job = Job(
        conversation_id=convo.id,
        kind="ingest",
        payload={"conversation_id": convo.id},
        status="queued",
    )
    db.add(job)

    # Update inbox item
    item.status = "imported"
    item.conversation_id = convo.id
    item.imported_at = utcnow()
    await db.flush()

    return item


async def ignore_inbox_item(db: AsyncSession, item_id: int) -> StagingInboxItem:
    """Mark an inbox item as ignored."""
    item = await db.get(StagingInboxItem, item_id)
    if item is None:
        raise ValueError(f"Inbox item {item_id} not found")
    if item.status not in ("pending_import", "parse_error"):
        raise ValueError(f"Cannot ignore item with status '{item.status}'")
    item.status = "ignored"
    await db.flush()
    return item


async def list_inbox_items(
    db: AsyncSession,
    *,
    status: str | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[StagingInboxItem], int]:
    """List inbox items with optional filtering. Returns (items, total)."""
    query = select(StagingInboxItem)
    count_query = select(StagingInboxItem.id)

    if status:
        query = query.where(StagingInboxItem.status == status)
        count_query = count_query.where(StagingInboxItem.status == status)
    if source:
        query = query.where(StagingInboxItem.source == source)
        count_query = count_query.where(StagingInboxItem.source == source)

    # Count
    count_result = await db.execute(count_query)
    total = len(count_result.all())

    # Fetch page
    query = query.order_by(StagingInboxItem.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total
