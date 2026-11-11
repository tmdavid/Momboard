"""Tiny key/value helpers over the ``app_settings`` table (settings edited in the UI)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, utcnow


async def _row(db: AsyncSession, key: str) -> AppSetting | None:
    return (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await _row(db, key)
    return default if row is None or row.value is None else row.value


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Insert or update a setting. Does not commit — the caller's transaction owns that."""
    row = await _row(db, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    await db.flush()
