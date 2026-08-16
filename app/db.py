"""Async database engine and session setup."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def _set_sqlite_pragmas(dbapi_conn: Any, _connection_record: Any) -> None:
    """Set SQLite pragmas for WAL mode, foreign keys, and busy timeout."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine(settings: Settings) -> AsyncEngine:
    """Create async engine from settings, applying dialect-specific hooks."""
    url = settings.database_url
    kwargs: dict[str, Any] = {}

    if "sqlite" in url:
        # aiosqlite needs check_same_thread=False
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_async_engine(url, echo=(settings.env == "development"), **kwargs)

    # Apply SQLite pragmas via connection event hook
    if "sqlite" in url:

        @event.listens_for(engine.sync_engine, "connect")
        def on_connect(dbapi_conn: Any, _rec: Any) -> None:
            _set_sqlite_pragmas(dbapi_conn, _rec)

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session, rolling back on error."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
