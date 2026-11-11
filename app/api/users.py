"""Teammate names for pickers (e.g. decision owner). Deliberately exposes only id + name."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import User

router = APIRouter()


class TeamUser(BaseModel):
    id: int
    name: str


class TeamUsersResponse(BaseModel):
    items: list[TeamUser]


@router.get("", response_model=TeamUsersResponse)
async def list_team_users(db: AsyncSession = Depends(get_db)) -> dict:
    """Display names for owner pickers. Never returns emails or credentials; a user with no
    name set is shown by the local part of their email."""
    rows = (await db.execute(select(User).order_by(User.name, User.id))).scalars().all()
    return {
        "items": [
            {"id": u.id, "name": (u.name or u.email.split("@", 1)[0]).strip()} for u in rows
        ]
    }
