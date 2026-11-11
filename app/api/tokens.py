"""API token management: create, list and revoke. Sign-in required; API tokens themselves cannot use these."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.auth import get_current_user
from app.models import ApiToken, User
from app.services import api_tokens as svc

router = APIRouter()


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["read", "write"] = "read"
    expires_in_days: Literal[30, 90, 365] | None = 90  # null means it never expires


class TokenResponse(BaseModel):
    id: int
    name: str
    prefix: str
    scope: Literal["read", "write"]
    status: Literal["active", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    owner_id: int
    owner_name: str | None = None


class TokenCreated(TokenResponse):
    token: str  # the secret: returned this once, never stored or shown again


class TokenListResponse(BaseModel):
    items: list[TokenResponse]


def _aware(moment: datetime | None) -> datetime | None:
    return svc._aware(moment)


def _view(token: ApiToken, owner: User | None = None) -> dict:
    owner = owner or token.user
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.prefix,
        "scope": "write" if "write" in (token.scopes or []) else "read",
        "status": svc.token_status(token),
        "created_at": _aware(token.created_at),
        "expires_at": _aware(token.expires_at),
        "last_used_at": _aware(token.last_used_at),
        "revoked_at": _aware(token.revoked_at),
        "owner_id": token.user_id,
        "owner_name": (owner.name or owner.email) if owner else None,
    }


@router.post("", response_model=TokenCreated, status_code=201)
async def create_token(
    body: TokenCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a token for yourself. The secret is in this response only."""
    try:
        token, plain = await svc.create_token(
            db, user, name=body.name, scope=body.scope, expires_in_days=body.expires_in_days
        )
    except svc.TokenLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except svc.TokenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return {**_view(token, user), "token": plain}


@router.get("", response_model=TokenListResponse)
async def list_tokens(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Your tokens (an admin sees everyone's). Never includes a secret."""
    return {"items": [_view(t) for t in await svc.list_tokens(db, user)]}


@router.post("/{token_id}/revoke", response_model=TokenResponse)
async def revoke_token(token_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Revoke a token. It stops working on its next request. The row is kept for the audit trail."""
    from sqlalchemy import select

    token = (
        await db.execute(select(ApiToken).options(selectinload(ApiToken.user)).where(ApiToken.id == token_id))
    ).scalar_one_or_none()
    # Someone else's token is a 404, so a member cannot learn that it exists.
    if token is None or (user.role != "admin" and token.user_id != user.id):
        raise HTTPException(status_code=404, detail="Token not found")
    await svc.revoke_token(db, token)
    return _view(token)
