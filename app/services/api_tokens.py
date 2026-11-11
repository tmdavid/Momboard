"""API tokens: generation, hashing, verification, expiry, revoke and limits.

A token is ``mb_`` plus 32 random bytes (base64url, 46 characters in all). Only its SHA-256 hash
and the first 8 characters (a visible prefix, so people can tell tokens apart) are stored; the
secret itself is returned once, at creation, and is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiToken, User

TOKEN_PREFIX = "mb_"
MAX_ACTIVE_PER_USER = 10
EXPIRY_CHOICES_DAYS = (30, 90, 365)
SCOPES = ("read", "write")
LAST_USED_RESOLUTION = timedelta(minutes=1)


class TokenError(ValueError):
    """The request to create a token was invalid."""


class TokenLimitError(TokenError):
    """The user already has the maximum number of active tokens."""


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; they were stored as UTC."""
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def token_status(token: ApiToken, now: datetime | None = None) -> str:
    """``revoked`` beats ``expired`` beats ``active``."""
    if token.revoked_at is not None:
        return "revoked"
    expires = _aware(token.expires_at)
    if expires is not None and expires <= (now or datetime.now(UTC)):
        return "expired"
    return "active"


def has_scope(token: ApiToken, scope: str) -> bool:
    scopes = set(token.scopes or [])
    return scope in scopes or (scope == "read" and "write" in scopes)  # write implies read


async def count_active(db: AsyncSession, user_id: int) -> int:
    now = datetime.now(UTC)
    rows = (await db.execute(select(ApiToken).where(ApiToken.user_id == user_id))).scalars().all()
    return sum(1 for t in rows if token_status(t, now) == "active")


async def create_token(
    db: AsyncSession, user: User, *, name: str, scope: str, expires_in_days: int | None
) -> tuple[ApiToken, str]:
    """Create a token for ``user``. Returns the row and the plaintext (the only time it exists)."""
    name = (name or "").strip()
    if not name:
        raise TokenError("Give the token a name.")
    if len(name) > 100:
        raise TokenError("The token name must be 100 characters or fewer.")
    if scope not in SCOPES:
        raise TokenError("Scope must be 'read' or 'write'.")
    if expires_in_days is not None and expires_in_days not in EXPIRY_CHOICES_DAYS:
        raise TokenError("Expiry must be 30, 90 or 365 days, or never.")
    if await count_active(db, user.id) >= MAX_ACTIVE_PER_USER:
        raise TokenLimitError(
            f"You already have {MAX_ACTIVE_PER_USER} active tokens. Revoke one before creating another."
        )

    plain = generate_token()
    row = ApiToken(
        user_id=user.id,
        name=name,
        prefix=plain[:8],
        token_hash=hash_token(plain),
        scopes=["read", "write"] if scope == "write" else ["read"],
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.add(row)
    await db.flush()
    return row, plain


@dataclass
class VerifiedToken:
    token: ApiToken
    user: User


async def verify_token(db: AsyncSession, presented: str | None) -> VerifiedToken | None:
    """Resolve a presented bearer token, or ``None`` for any reason it should not work.

    Looks the token up by its hash and compares in constant time. The caller must not reveal
    *why* it failed (unknown, revoked, expired and orphaned all look the same from outside).
    """
    if not presented or not presented.startswith(TOKEN_PREFIX) or len(presented) > 200:
        return None
    digest = hash_token(presented)
    token = (await db.execute(select(ApiToken).where(ApiToken.token_hash == digest))).scalar_one_or_none()
    if token is None or not hmac.compare_digest(token.token_hash, digest):
        return None
    if token_status(token) != "active":
        return None
    user = await db.get(User, token.user_id)  # the model has no "active" flag: a missing row is inactive
    if user is None:
        return None

    now = datetime.now(UTC)
    last = _aware(token.last_used_at)
    if last is None or now - last >= LAST_USED_RESOLUTION:
        token.last_used_at = now
    return VerifiedToken(token=token, user=user)


async def revoke_token(db: AsyncSession, token: ApiToken) -> None:
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        await db.flush()


async def list_tokens(db: AsyncSession, viewer: User) -> list[ApiToken]:
    """A member sees their own tokens; an admin sees everyone's."""
    stmt = select(ApiToken).order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
    if viewer.role != "admin":
        stmt = stmt.where(ApiToken.user_id == viewer.id)
    return list((await db.execute(stmt)).scalars().all())


async def count_all(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count(ApiToken.id)))).scalar_one())
