"""T03: Schema, seed, and integrity tests."""

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Conversation, Highlight, Tag
from app.seed import seed_tags


@pytest.mark.asyncio
async def test_tag_seed_is_idempotent(db_session: AsyncSession):
    await seed_tags(db_session)
    await db_session.commit()
    await seed_tags(db_session)
    await db_session.commit()

    keys = {t.key for t in (await db_session.execute(select(Tag))).scalars()}
    expected = {
        "pain", "obstacle", "workaround", "emotion_pos", "emotion_neg",
        "context", "feature_request", "money", "person", "followup",
        "commitment", "compliment",
    }
    assert expected <= keys
    count = (await db_session.execute(select(func.count(Tag.key)))).scalar_one()
    assert count == 12


@pytest.mark.asyncio
async def test_tags_have_correct_fields(db_session: AsyncSession):
    await seed_tags(db_session)
    await db_session.commit()

    pain = await db_session.get(Tag, "pain")
    assert pain is not None
    assert pain.emoji == "⚡"
    assert pain.name == "Pain / problem"
    assert pain.signal_strength == "strong"
    assert pain.sort_order == 1
    assert pain.is_active is True


@pytest.mark.asyncio
async def test_highlight_requires_valid_tag_key(db_session: AsyncSession):
    """FK enforced: can't insert highlight with non-existent tag_key."""
    await seed_tags(db_session)

    convo = Conversation(title="test", status="processing")
    db_session.add(convo)
    await db_session.flush()

    highlight = Highlight(
        conversation_id=convo.id,
        tag_key="nonexistent_tag",
        quote="test quote",
        origin="ai",
        status="suggested",
    )
    db_session.add(highlight)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_pks_are_integer_except_tags(engine: AsyncEngine):
    """Every table's PK is INTEGER except tags.key (VARCHAR)."""
    async with engine.connect() as conn:
        def check_pks(connection):
            insp = inspect(connection)
            for table_name in insp.get_table_names():
                pk_cols = insp.get_pk_constraint(table_name)["constrained_columns"]
                columns = {c["name"]: c for c in insp.get_columns(table_name)}
                for pk_col in pk_cols:
                    col = columns[pk_col]
                    if table_name == "tags" and pk_col == "key":
                        assert "VARCHAR" in str(col["type"]).upper() or "CHAR" in str(col["type"]).upper()
                    elif table_name == "conversation_contacts":
                        # Composite PK, both integers
                        assert "INTEGER" in str(col["type"]).upper()
                    else:
                        assert "INTEGER" in str(col["type"]).upper(), (
                            f"Table {table_name}.{pk_col} should be INTEGER, got {col['type']}"
                        )

        await conn.run_sync(check_pks)
