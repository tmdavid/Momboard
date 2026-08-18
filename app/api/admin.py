"""Admin API: tags, companies, and contacts management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    CompanyCreate,
    CompanyResponse,
    ContactCreate,
    ContactResponse,
    TagResponse,
    TagUpdate,
)
from app.auth import get_current_user, require_admin
from app.models import Company, Contact, Conversation, Tag, User

router = APIRouter()


# --- Tags ---


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all tags."""
    result = await db.execute(select(Tag).order_by(Tag.sort_order))
    return [TagResponse.model_validate(tag) for tag in result.scalars().all()]


@router.post("/tags", response_model=TagResponse, status_code=201)
async def create_tag(
    body: TagResponse,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Create a new tag (admin only)."""
    if await db.get(Tag, body.key) is not None:
        raise HTTPException(status_code=409, detail="Tag key already exists")
    tag = Tag(
        key=body.key,
        emoji=body.emoji,
        name=body.name,
        description=body.description,
        signal_strength=body.signal_strength,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(tag)
    await db.flush()
    return TagResponse.model_validate(tag)


@router.patch("/tags/{key}", response_model=TagResponse)
async def update_tag(
    key: str,
    body: TagUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Update a tag (admin only)."""
    tag = await db.get(Tag, key)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tag, field, value)
    await db.flush()
    return TagResponse.model_validate(tag)


# --- Companies ---


def _company_response(company: Company, conversation_count: int = 0) -> CompanyResponse:
    return CompanyResponse.model_validate(company).model_copy(
        update={"conversation_count": conversation_count}
    )


@router.get("/companies", response_model=list[CompanyResponse])
async def list_companies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    active_only: bool = False,
):
    """List companies with conversation counts, optionally active only."""
    counts = (
        select(
            Conversation.company_id.label("company_id"),
            func.count(Conversation.id).label("conversation_count"),
        )
        .where(Conversation.company_id.is_not(None))
        .group_by(Conversation.company_id)
        .subquery()
    )
    count_value = func.coalesce(counts.c.conversation_count, 0)
    query = (
        select(Company, count_value.label("conversation_count"))
        .outerjoin(counts, counts.c.company_id == Company.id)
        .order_by(Company.name)
    )
    if active_only:
        query = query.where(count_value > 0)

    result = await db.execute(query)
    return [
        _company_response(company, int(conversation_count))
        for company, conversation_count in result.all()
    ]


@router.post("/companies", response_model=CompanyResponse, status_code=201)
async def create_company(
    body: CompanyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a company for the directory."""
    existing = await db.execute(select(Company.id).where(Company.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Company name already exists")
    company = Company(name=body.name, domain=body.domain)
    db.add(company)
    await db.flush()
    return _company_response(company)


# --- Contacts ---


@router.get("/contacts", response_model=list[ContactResponse])
async def list_contacts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all contacts."""
    result = await db.execute(select(Contact).order_by(Contact.name))
    return [ContactResponse.model_validate(contact) for contact in result.scalars().all()]


@router.post("/contacts", response_model=ContactResponse, status_code=201)
async def create_contact(
    body: ContactCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a contact and preserve its selected company association."""
    if body.company_id is not None and await db.get(Company, body.company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")
    contact = Contact(
        name=body.name,
        role=body.role,
        email=body.email,
        company_id=body.company_id,
    )
    db.add(contact)
    await db.flush()
    return ContactResponse.model_validate(contact)
