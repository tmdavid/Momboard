"""Admin API: tags, companies, contacts management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
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
from app.models import Company, Contact, Tag, User

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
    return [TagResponse.model_validate(t) for t in result.scalars().all()]


@router.post("/tags", status_code=201)
async def create_tag(
    body: TagResponse,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Create a new tag (admin only)."""
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


@router.patch("/tags/{key}")
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
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(tag, k, v)
    await db.flush()
    return TagResponse.model_validate(tag)


# --- Companies ---


@router.get("/companies", response_model=list[CompanyResponse])
async def list_companies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all companies."""
    result = await db.execute(select(Company).order_by(Company.name))
    return [CompanyResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/companies", status_code=201)
async def create_company(
    body: CompanyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a company."""
    company = Company(name=body.name, domain=body.domain)
    db.add(company)
    await db.flush()
    return CompanyResponse.model_validate(company)


# --- Contacts ---


@router.get("/contacts")
async def list_contacts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all contacts."""
    result = await db.execute(select(Contact).order_by(Contact.name))
    return [ContactResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/contacts", status_code=201)
async def create_contact(
    body: ContactCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a contact."""
    contact = Contact(name=body.name, role=body.role, email=body.email)
    db.add(contact)
    await db.flush()
    return ContactResponse.model_validate(contact)
