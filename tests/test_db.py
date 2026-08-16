"""T02: Database wiring and session tests."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

ALL_TABLES = {
    "companies", "contacts", "conversations", "conversation_contacts",
    "utterances", "tags", "highlights", "analyses", "notes", "users", "jobs",
}


@pytest.mark.asyncio
async def test_session_fixture_roundtrip(db_session: AsyncSession):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_all_tables_exist(engine: AsyncEngine):
    async with engine.connect() as conn:
        table_names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert ALL_TABLES <= table_names


@pytest.mark.asyncio
async def test_foreign_keys_enabled(db_session: AsyncSession):
    """SQLite foreign keys should be ON."""
    result = await db_session.execute(text("PRAGMA foreign_keys"))
    assert result.scalar_one() == 1
