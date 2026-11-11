"""Explore must never drag call transcripts through the database.

Regression: the per-call cap ranked a subquery that selected every column of every highlight's call,
including the full transcript. On a real corpus (25k highlights, ~20 KB per transcript) SQLite had to
sort hundreds of MB, spilled it into the container's 64 MB /tmp and failed with "database or disk is
full". Small test data cannot show that, so this inspects the SQL that is actually executed.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import event

from app.models import Company, Conversation, Highlight


@pytest_asyncio.fixture
async def corpus(session_factory):
    async with session_factory() as db:
        co = Company(name="Co")
        db.add(co)
        await db.flush()
        for n in range(3):
            c = Conversation(title=f"Call {n}", company_id=co.id, status="ready", source="upload",
                             happened_at=datetime(2026, 11, 1 + n, tzinfo=UTC), raw_transcript="x" * 50_000,
                             transcript_format="name_colon")
            db.add(c)
            await db.flush()
            for i in range(6):
                db.add(Highlight(conversation_id=c.id, tag_key="pain", quote=f"quote {n}-{i}", status="suggested",
                                 origin="ai", confidence=0.6 + i / 20))
        await db.commit()


@pytest.fixture
def executed(engine):
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", record)
    yield statements
    event.remove(sync_engine, "before_cursor_execute", record)


QUERY = {"tag": ["pain", "workaround"], "sort": "confidence", "floor": "true", "per_call_cap": 3, "limit": 200}


@pytest.mark.asyncio
async def test_the_explore_query_never_selects_a_transcript(auth_client, corpus, executed):
    r = await auth_client.get("/api/highlights", params=QUERY)
    assert r.status_code == 200
    heavy = [s for s in executed if "raw_transcript" in s and "highlights" in s]
    assert heavy == [], f"{len(heavy)} statement(s) pulled transcripts, e.g. {heavy[0][:200] if heavy else ''}"


@pytest.mark.asyncio
async def test_the_ranking_subquery_only_carries_the_columns_it_needs(auth_client, corpus, executed):
    await auth_client.get("/api/highlights", params=QUERY)
    ranking = [s for s in executed if "row_number()" in s.lower()]
    assert ranking, "expected the per-call cap to rank rows"
    for statement in ranking:
        inner = statement.lower().split("from", 1)[0]
        assert inner.count(",") <= 8, f"ranking selects too many columns: {inner[:300]}"


@pytest.mark.asyncio
async def test_results_are_still_correct_with_the_cap(auth_client, corpus):
    r = await auth_client.get("/api/highlights", params=QUERY)
    body = r.json()
    assert body["total"] == 9                                   # 3 calls x top 3
    per_call = {}
    for item in body["items"]:
        per_call.setdefault(item["conversation_id"], []).append(item["quote"])
    assert all(len(v) == 3 for v in per_call.values())
    assert all(q.endswith(("-5", "-4", "-3")) for v in per_call.values() for q in v)      # the strongest three
    confidences = [i["confidence"] for i in body["items"]]
    assert confidences == sorted(confidences, reverse=True)


@pytest.mark.asyncio
async def test_listing_without_the_cap_is_also_light(auth_client, corpus, executed):
    await auth_client.get("/api/highlights", params={"limit": 50})
    assert [s for s in executed if "raw_transcript" in s and "highlights" in s] == []
