"""T05 RED: Complete conversation filtering tests.

Tests that are NOT yet implemented in the API:
- Filtering by meta.deal_stage (JSON path filter)
- Filtering by multiple tags simultaneously (AND logic)
- Filtering by repeated/multiple tags
- Combined filter interactions
- Cascade assertions for delete
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Analysis,
    Highlight,
    Job,
    Note,
    Utterance,
)
from app.seed import seed_tags


@pytest.mark.asyncio
async def test_filter_by_meta_deal_stage(auth_client: AsyncClient):
    """Filtering conversations by meta.deal_stage should work via a `deal_stage` query param."""
    # Create conversations with different deal stages
    await auth_client.post(
        "/api/conversations",
        json={
            "title": "Discovery Call",
            "transcript": "David: hi\nAlice: hey",
            "transcript_format": "name_colon",
            "meta": {"deal_stage": "discovery"},
        },
    )
    await auth_client.post(
        "/api/conversations",
        json={
            "title": "Negotiation Call",
            "transcript": "David: price\nBob: ok",
            "transcript_format": "name_colon",
            "meta": {"deal_stage": "negotiation"},
        },
    )

    # Filter by deal_stage=discovery should only return discovery conversations
    r = await auth_client.get("/api/conversations", params={"deal_stage": "discovery"})
    assert r.status_code == 200
    body = r.json()
    # Must have at least 1 result
    assert body["total"] >= 1, "deal_stage filter should find at least 1 conversation"
    # All returned items must have deal_stage=discovery in meta
    for item in body["items"]:
        meta = item.get("meta") or {}
        assert (
            meta.get("deal_stage") == "discovery"
        ), f"Expected all results to have deal_stage='discovery', got meta={meta}"


@pytest.mark.asyncio
async def test_filter_by_multiple_tags(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """Filtering by multiple tags should return conversations with ALL specified tags."""
    # Create conversation and manually add highlights with different tags
    r = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Multi-tag call",
            "transcript": "David: test\nBob: answer",
            "transcript_format": "name_colon",
        },
    )
    convo_id = r.json()["id"]

    # Manually seed highlights with tags (bypassing pipeline)
    async with session_factory() as session:
        await seed_tags(session)
        session.add(
            Highlight(
                conversation_id=convo_id,
                tag_key="pain",
                quote="test",
                origin="ai",
                status="suggested",
            )
        )
        session.add(
            Highlight(
                conversation_id=convo_id,
                tag_key="workaround",
                quote="answer",
                origin="ai",
                status="suggested",
            )
        )
        await session.commit()

    # Filter by multiple tags (comma-separated)
    r = await auth_client.get("/api/conversations", params={"tag": "pain,workaround"})
    assert r.status_code == 200
    body = r.json()
    # Should find the conversation since it has BOTH tags
    assert body["total"] >= 1
    assert any(item["id"] == convo_id for item in body["items"])


@pytest.mark.asyncio
async def test_filter_by_repeated_tag_does_not_duplicate(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """When a conversation has multiple highlights of the same tag, it should appear only once in results."""
    r = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Repeated tag call",
            "transcript": "David: pain1\nBob: pain2",
            "transcript_format": "name_colon",
        },
    )
    convo_id = r.json()["id"]

    async with session_factory() as session:
        await seed_tags(session)
        # Add two highlights with same tag
        session.add(
            Highlight(
                conversation_id=convo_id,
                tag_key="pain",
                quote="pain1",
                origin="ai",
                status="suggested",
            )
        )
        session.add(
            Highlight(
                conversation_id=convo_id,
                tag_key="pain",
                quote="pain2",
                origin="ai",
                status="suggested",
            )
        )
        await session.commit()

    r = await auth_client.get("/api/conversations", params={"tag": "pain"})
    assert r.status_code == 200
    body = r.json()
    # Conversation should appear exactly once
    ids = [item["id"] for item in body["items"]]
    assert ids.count(convo_id) == 1


@pytest.mark.asyncio
async def test_filter_by_date_range(auth_client: AsyncClient):
    """Date range filter should be inclusive on both ends."""
    await auth_client.post(
        "/api/conversations",
        json={
            "title": "January call",
            "happened_at": "2026-01-15T10:00:00Z",
            "transcript": "David: hi\nAlice: hey",
            "transcript_format": "name_colon",
        },
    )
    await auth_client.post(
        "/api/conversations",
        json={
            "title": "August call",
            "happened_at": "2026-08-15T10:00:00Z",
            "transcript": "David: hi\nBob: hey",
            "transcript_format": "name_colon",
        },
    )

    r = await auth_client.get(
        "/api/conversations",
        params={"date_from": "2026-08-01T00:00:00Z", "date_to": "2026-08-31T23:59:59Z"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(
        "August" in item["title"] or "august" in item["title"].lower() for item in body["items"]
    )


@pytest.mark.asyncio
async def test_delete_cascades_all_related_data(
    session_factory: async_sessionmaker[AsyncSession], auth_client: AsyncClient
):
    """Deleting a conversation should cascade delete utterances, highlights, analyses, notes, jobs."""
    # Create conversation
    r = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Cascade Test",
            "transcript": "David: test\nMaria: data",
            "transcript_format": "name_colon",
        },
    )
    convo_id = r.json()["id"]

    # Add related data manually
    async with session_factory() as session:
        await seed_tags(session)
        session.add(
            Utterance(
                conversation_id=convo_id,
                idx=0,
                speaker_label="David",
                speaker_side="us",
                text="test",
            )
        )
        session.add(
            Highlight(
                conversation_id=convo_id,
                tag_key="pain",
                quote="test",
                origin="ai",
                status="suggested",
            )
        )
        session.add(Analysis(conversation_id=convo_id, kind="conversation", result={}))
        session.add(Note(conversation_id=convo_id, body_md="note"))
        await session.commit()

    # Delete the conversation
    r = await auth_client.delete(f"/api/conversations/{convo_id}")
    assert r.status_code == 204

    # Verify everything is gone
    async with session_factory() as session:
        assert (
            await session.execute(select(Utterance).where(Utterance.conversation_id == convo_id))
        ).scalars().all() == []
        assert (
            await session.execute(select(Highlight).where(Highlight.conversation_id == convo_id))
        ).scalars().all() == []
        assert (
            await session.execute(select(Analysis).where(Analysis.conversation_id == convo_id))
        ).scalars().all() == []
        assert (
            await session.execute(select(Note).where(Note.conversation_id == convo_id))
        ).scalars().all() == []
        assert (
            await session.execute(select(Job).where(Job.conversation_id == convo_id))
        ).scalars().all() == []


@pytest.mark.asyncio
async def test_filter_by_repeated_tag_params_and_logic(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """Repeated ?tag=pain&tag=workaround should AND-filter (only convos with BOTH tags)."""
    # Create two conversations:
    # convo_both has pain + workaround highlights
    # convo_single has only pain highlight
    r1 = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Both tags call",
            "transcript": "David: test\nBob: answer",
            "transcript_format": "name_colon",
        },
    )
    convo_both_id = r1.json()["id"]

    r2 = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Single tag call",
            "transcript": "David: hello\nAlice: hi",
            "transcript_format": "name_colon",
        },
    )
    convo_single_id = r2.json()["id"]

    async with session_factory() as session:
        await seed_tags(session)
        # convo_both gets both tags
        session.add(
            Highlight(
                conversation_id=convo_both_id,
                tag_key="pain",
                quote="test",
                origin="ai",
                status="suggested",
            )
        )
        session.add(
            Highlight(
                conversation_id=convo_both_id,
                tag_key="workaround",
                quote="answer",
                origin="ai",
                status="suggested",
            )
        )
        # convo_single gets only pain
        session.add(
            Highlight(
                conversation_id=convo_single_id,
                tag_key="pain",
                quote="hello",
                origin="ai",
                status="suggested",
            )
        )
        await session.commit()

    # Repeated tag params: ?tag=pain&tag=workaround (AND logic)
    r = await auth_client.get(
        "/api/conversations",
        params=[("tag", "pain"), ("tag", "workaround")],
    )
    assert r.status_code == 200
    body = r.json()
    result_ids = [item["id"] for item in body["items"]]
    assert convo_both_id in result_ids, "Conversation with both tags should appear"
    assert convo_single_id not in result_ids, "Conversation with only one tag should NOT appear"


@pytest.mark.asyncio
async def test_highlights_filter_by_repeated_tag_params(
    auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """Repeated ?tag=pain&tag=workaround on highlights endpoint should OR-filter (any tag match)."""
    r = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Highlights multi-tag",
            "transcript": "David: test\nBob: answer",
            "transcript_format": "name_colon",
        },
    )
    convo_id = r.json()["id"]

    r2 = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Only pain convo",
            "transcript": "David: hello\nAlice: hi",
            "transcript_format": "name_colon",
        },
    )
    convo_single_id = r2.json()["id"]

    async with session_factory() as session:
        await seed_tags(session)
        # convo with both tags
        session.add(
            Highlight(
                conversation_id=convo_id,
                tag_key="pain",
                quote="test pain",
                origin="ai",
                status="suggested",
            )
        )
        session.add(
            Highlight(
                conversation_id=convo_id,
                tag_key="workaround",
                quote="test workaround",
                origin="ai",
                status="suggested",
            )
        )
        # convo with only pain
        session.add(
            Highlight(
                conversation_id=convo_single_id,
                tag_key="pain",
                quote="single pain",
                origin="ai",
                status="suggested",
            )
        )
        # convo with money tag (should NOT appear)
        session.add(
            Highlight(
                conversation_id=convo_single_id,
                tag_key="money",
                quote="money thing",
                origin="ai",
                status="suggested",
            )
        )
        await session.commit()

    # Repeated tag params for highlights endpoint — OR semantics
    r = await auth_client.get(
        "/api/highlights",
        params=[("tag", "pain"), ("tag", "workaround")],
    )
    assert r.status_code == 200
    body = r.json()
    # Should get all pain + workaround highlights from both conversations
    tag_keys_in_results = {item["tag_key"] for item in body["items"]}
    assert tag_keys_in_results <= {
        "pain",
        "workaround",
    }, f"Only pain and workaround should appear, got: {tag_keys_in_results}"
    # Should include highlights from both conversations
    convo_ids_in_results = {item["conversation_id"] for item in body["items"]}
    assert convo_id in convo_ids_in_results
    assert (
        convo_single_id in convo_ids_in_results
    ), "Convo with pain-only should appear since we OR-filter tags in highlights"
    # Money highlight should NOT appear
    assert all(item["tag_key"] != "money" for item in body["items"])
