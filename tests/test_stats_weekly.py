"""v0.5 U8: the Insights trends are weekly and follow when the call happened."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.models import Analysis, Conversation


def analysis(score, ratio):
    return {"summary": "s", "mom_test_critique": {"score": score, "good_questions": [], "violations": []},
            "compliment_ratio": ratio, "top_pains": [], "commitments": []}


async def add_call(db, happened_at, score, ratio, *, created_at=None, source="upload"):
    c = Conversation(title="c", status="ready", source=source, happened_at=happened_at,
                     raw_transcript="x", transcript_format="name_colon")
    db.add(c)
    await db.flush()
    a = Analysis(conversation_id=c.id, kind="conversation", result=analysis(score, ratio))
    if created_at:
        a.created_at = created_at
    db.add(a)
    await db.flush()
    return c


@pytest.mark.asyncio
async def test_trends_are_bucketed_by_week_starting_monday(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        # Mon 2 Nov, Wed 4 Nov (same week); Tue 10 Nov (next week)
        await add_call(db, datetime(2026, 11, 2, tzinfo=UTC), 6, 0.2)
        await add_call(db, datetime(2026, 11, 4, tzinfo=UTC), 8, 0.4)
        await add_call(db, datetime(2026, 11, 10, tzinfo=UTC), 5, 0.1)
        await db.commit()
    body = (await auth_client.get("/api/stats")).json()
    assert body["critique_trend"] == [{"date": "2026-11-02", "score": 7.0}, {"date": "2026-11-09", "score": 5.0}]
    ratios = body["compliment_ratio_trend"]
    assert [p["date"] for p in ratios] == ["2026-11-02", "2026-11-09"]
    assert ratios[0]["ratio"] == pytest.approx(0.3) and ratios[1]["ratio"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_trend_follows_the_call_date_not_the_day_the_analysis_was_rebuilt(auth_client: AsyncClient, session_factory):
    """A retag/backfill recreates every analysis on one day; that must not collapse the trend."""
    rebuilt = datetime(2026, 12, 1, tzinfo=UTC)
    async with session_factory() as db:
        await add_call(db, datetime(2026, 10, 5, tzinfo=UTC), 4, 0.5, created_at=rebuilt)
        await add_call(db, datetime(2026, 10, 19, tzinfo=UTC), 6, 0.3, created_at=rebuilt)
        await db.commit()
    body = (await auth_client.get("/api/stats")).json()
    assert [p["date"] for p in body["critique_trend"]] == ["2026-10-05", "2026-10-19"]


@pytest.mark.asyncio
async def test_a_call_without_a_date_falls_back_to_when_it_was_analysed(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        await add_call(db, None, 6, 0.2, created_at=datetime(2026, 11, 12, tzinfo=UTC))   # Thursday
        await db.commit()
    body = (await auth_client.get("/api/stats")).json()
    assert [p["date"] for p in body["critique_trend"]] == ["2026-11-09"]


@pytest.mark.asyncio
async def test_overall_averages_cover_every_call_not_just_the_latest_week(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        await add_call(db, datetime(2026, 11, 2, tzinfo=UTC), 4, 0.5)
        await add_call(db, datetime(2026, 11, 3, tzinfo=UTC), 6, 0.3)
        await add_call(db, datetime(2026, 11, 10, tzinfo=UTC), 8, 0.1)
        await db.commit()
    body = (await auth_client.get("/api/stats")).json()
    assert body["avg_critique_score"] == 6.0
    assert body["avg_compliment_ratio"] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_simulated_calls_never_enter_trends_or_averages(auth_client: AsyncClient, session_factory):
    async with session_factory() as db:
        await add_call(db, datetime(2026, 11, 2, tzinfo=UTC), 9, 0.0, source="simulator")
        await db.commit()
    body = (await auth_client.get("/api/stats")).json()
    assert body["critique_trend"] == [] and body["compliment_ratio_trend"] == []
    assert body["avg_critique_score"] is None and body["avg_compliment_ratio"] is None


@pytest.mark.asyncio
async def test_no_data_gives_empty_trends_and_null_averages(auth_client: AsyncClient):
    body = (await auth_client.get("/api/stats")).json()
    assert body["critique_trend"] == [] and body["avg_critique_score"] is None
