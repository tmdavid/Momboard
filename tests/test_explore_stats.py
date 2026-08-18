"""T19: Cross-conversation highlights + stats endpoint tests."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Analysis, Company, Conversation, Highlight, Utterance
from app.seed import seed_tags


@pytest.fixture
async def seeded_explore_data(session_factory: async_sessionmaker[AsyncSession]):
    """Create a set of conversations with highlights and analyses for explore tests."""
    async with session_factory() as db:
        await seed_tags(db)

        company = Company(name="Explore Corp")
        db.add(company)
        await db.flush()

        convo1 = Conversation(
            title="Explore Call 1",
            company_id=company.id,
            interviewer="David",
            status="ready",
            happened_at=datetime(2026, 7, 15, tzinfo=UTC),
        )
        convo2 = Conversation(
            title="Explore Call 2",
            company_id=company.id,
            interviewer="David",
            status="ready",
            happened_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        db.add_all([convo1, convo2])
        await db.flush()

        # Add utterances
        db.add(Utterance(
            conversation_id=convo1.id, idx=0,
            speaker_label="Maria", speaker_side="them", text="Test utterance 1",
        ))
        db.add(Utterance(
            conversation_id=convo2.id, idx=0,
            speaker_label="Tom", speaker_side="them", text="Test utterance 2",
        ))
        await db.flush()

        # Add highlights
        h1 = Highlight(
            conversation_id=convo1.id, tag_key="pain",
            quote="it hurts", origin="ai", status="accepted", confidence=0.9,
        )
        h2 = Highlight(
            conversation_id=convo1.id, tag_key="workaround",
            quote="we use excel", origin="ai", status="suggested", confidence=0.85,
        )
        h3 = Highlight(
            conversation_id=convo2.id, tag_key="pain",
            quote="too slow", origin="ai", status="accepted", confidence=0.88,
        )
        h_rejected = Highlight(
            conversation_id=convo2.id, tag_key="compliment",
            quote="sounds great", origin="ai", status="rejected", confidence=0.6,
        )
        h_followup = Highlight(
            conversation_id=convo1.id, tag_key="followup",
            quote="send proposal", origin="human", status="accepted", confidence=1.0,
        )
        db.add_all([h1, h2, h3, h_rejected, h_followup])
        await db.flush()

        # Add analysis
        analysis = Analysis(
            conversation_id=convo1.id,
            kind="conversation",
            model="gpt-4o",
            prompt_version="analyst-v1",
            result={
                "summary": "Test summary",
                "top_pains": [],
                "commitments": [
                    {
                        "what": "Friday one-pager observation",
                        "actor": "Jonas",
                        "cost": "one hour on Friday",
                        "type": "time",
                        "next_step": "Sit in on the Friday one-pager session — the 28th",
                        "evidence_highlight_ids": [h_followup.id],
                    }
                ],
                "compliment_ratio": 0.2,
                "mom_test_critique": {"score": 7, "good_questions": [], "violations": []},
                "suggested_followups": [],
                "open_questions": [],
            },
        )
        db.add(analysis)
        await db.commit()

        return {
            "company": company,
            "convo1": convo1,
            "convo2": convo2,
            "highlight_ids": [h1.id, h2.id, h3.id, h_rejected.id, h_followup.id],
        }


@pytest.mark.asyncio
async def test_highlights_endpoint_returns_items_with_context(
    auth_client: AsyncClient, seeded_explore_data,
):
    """GET /api/highlights should return highlights with conversation context."""
    r = await auth_client.get("/api/highlights")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 4  # 3 non-rejected + 1 followup

    # Each item should have context
    item = body["items"][0]
    assert "conversation_title" in item
    assert "tag_key" in item
    assert "quote" in item


@pytest.mark.asyncio
async def test_highlights_default_excludes_rejected(
    auth_client: AsyncClient, seeded_explore_data,
):
    """Default filter should exclude rejected highlights."""
    r = await auth_client.get("/api/highlights")
    body = r.json()
    statuses = {item["status"] for item in body["items"]}
    assert "rejected" not in statuses


@pytest.mark.asyncio
async def test_highlights_filter_by_tag(
    auth_client: AsyncClient, seeded_explore_data,
):
    """Filter by tag should return only matching highlights."""
    r = await auth_client.get("/api/highlights", params={"tag": "pain"})
    assert r.status_code == 200
    body = r.json()
    assert all(item["tag_key"] == "pain" for item in body["items"])
    assert body["total"] >= 2


@pytest.mark.asyncio
async def test_highlights_filter_by_company(
    auth_client: AsyncClient, seeded_explore_data,
):
    """Filter by company_id should work."""
    data = seeded_explore_data
    r = await auth_client.get(
        "/api/highlights", params={"company_id": data["convo1"].company_id}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(item["company_name"] == "Explore Corp" for item in body["items"])


@pytest.mark.asyncio
async def test_highlights_filter_by_status_explicit(
    auth_client: AsyncClient, seeded_explore_data,
):
    """Explicit status filter can include rejected."""
    r = await auth_client.get("/api/highlights", params={"status": "rejected"})
    assert r.status_code == 200
    body = r.json()
    assert all(item["status"] == "rejected" for item in body["items"])


@pytest.mark.asyncio
async def test_stats_endpoint_returns_expected_shape(
    auth_client: AsyncClient, seeded_explore_data,
):
    """GET /api/stats should return tag_counts_by_month, critique_trend, etc."""
    r = await auth_client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert "tag_counts_by_month" in body
    assert "critique_trend" in body
    assert "compliment_ratio_trend" in body
    assert "open_followups" in body


@pytest.mark.asyncio
async def test_stats_tag_counts_by_month(
    auth_client: AsyncClient, seeded_explore_data,
):
    """tag_counts_by_month should aggregate highlights per tag per month."""
    r = await auth_client.get("/api/stats")
    body = r.json()
    tag_counts = body["tag_counts_by_month"]
    # Should have at least one month key
    assert len(tag_counts) >= 1
    # Each month should have tag counts
    for month, counts in tag_counts.items():
        assert isinstance(counts, dict)


@pytest.mark.asyncio
async def test_stats_critique_trend(auth_client: AsyncClient, seeded_explore_data):
    """critique_trend should include score and conversation_id."""
    r = await auth_client.get("/api/stats")
    body = r.json()
    trend = body["critique_trend"]
    assert len(trend) >= 1
    assert "score" in trend[0]
    assert "conversation_id" in trend[0]


@pytest.mark.asyncio
async def test_stats_open_followups(auth_client: AsyncClient, seeded_explore_data):
    """open_followups should list highlights with tag=followup."""
    r = await auth_client.get("/api/stats")
    body = r.json()
    followups = body["open_followups"]
    assert len(followups) >= 1
    assert "quote" in followups[0]
    assert followups[0]["quote"] == "send proposal"
    assert followups[0]["task"] == "Sit in on the Friday one-pager session — the 28th"
    assert "conversation_title" in followups[0]
