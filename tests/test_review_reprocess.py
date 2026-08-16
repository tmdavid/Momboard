"""T13: Highlight review + reprocess tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Highlight, Job


@pytest.mark.asyncio
async def test_patch_highlight_accept(auth_client: AsyncClient, sample_conversation):
    """PATCH to accept a highlight should change status."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        h = Highlight(
            conversation_id=sample_conversation.id,
            tag_key="pain",
            quote="test quote",
            origin="ai",
            status="suggested",
            confidence=0.8,
        )
        db.add(h)
        await db.commit()
        h_id = h.id

    r = await auth_client.patch(f"/api/highlights/{h_id}", json={"status": "accepted"})
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_patch_highlight_reject(auth_client: AsyncClient, sample_conversation):
    """PATCH to reject a highlight."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        h = Highlight(
            conversation_id=sample_conversation.id,
            tag_key="compliment",
            quote="sounds great",
            origin="ai",
            status="suggested",
            confidence=0.7,
        )
        db.add(h)
        await db.commit()
        h_id = h.id

    r = await auth_client.patch(f"/api/highlights/{h_id}", json={"status": "rejected"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_patch_highlight_edit_tag_and_quote(auth_client: AsyncClient, sample_conversation):
    """PATCH to change tag and quote."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        h = Highlight(
            conversation_id=sample_conversation.id,
            tag_key="pain",
            quote="original quote",
            origin="ai",
            status="suggested",
            confidence=0.8,
        )
        db.add(h)
        await db.commit()
        h_id = h.id

    r = await auth_client.patch(
        f"/api/highlights/{h_id}",
        json={"tag_key": "workaround", "quote": "edited quote"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tag_key"] == "workaround"
    assert body["quote"] == "edited quote"


@pytest.mark.asyncio
async def test_patch_nonexistent_highlight_404(auth_client: AsyncClient):
    r = await auth_client.patch("/api/highlights/99999", json={"status": "accepted"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_manual_highlight_creation_origin_human_status_accepted(
    auth_client: AsyncClient, sample_conversation,
):
    """POST manual highlight should have origin=human, status=accepted."""
    r = await auth_client.post(
        f"/api/conversations/{sample_conversation.id}/highlights",
        json={
            "tag_key": "followup",
            "quote": "Need to follow up on this",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["origin"] == "human"
    assert body["status"] == "accepted"
    assert body["tag_key"] == "followup"


@pytest.mark.asyncio
async def test_reprocess_preserves_human_decisions(auth_client: AsyncClient, sample_conversation):
    """Reprocess should delete only AI+suggested highlights, preserving accepted/rejected."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        # Create highlights with different statuses
        h_accepted = Highlight(
            conversation_id=sample_conversation.id, tag_key="pain",
            quote="accepted", origin="ai", status="accepted", confidence=0.9,
        )
        h_rejected = Highlight(
            conversation_id=sample_conversation.id, tag_key="compliment",
            quote="rejected", origin="ai", status="rejected", confidence=0.5,
        )
        h_suggested = Highlight(
            conversation_id=sample_conversation.id, tag_key="context",
            quote="suggested", origin="ai", status="suggested", confidence=0.7,
        )
        h_human = Highlight(
            conversation_id=sample_conversation.id, tag_key="followup",
            quote="human note", origin="human", status="accepted", confidence=1.0,
        )
        db.add_all([h_accepted, h_rejected, h_suggested, h_human])
        await db.commit()
        accepted_id = h_accepted.id
        rejected_id = h_rejected.id
        suggested_id = h_suggested.id
        human_id = h_human.id

    # Reprocess
    r = await auth_client.post(f"/api/conversations/{sample_conversation.id}/reprocess")
    assert r.status_code == 200
    assert r.json()["status"] == "processing"

    # Verify preservation
    async with sf() as db:
        # Accepted should still be there
        assert await db.get(Highlight, accepted_id) is not None
        # Rejected should still be there
        assert await db.get(Highlight, rejected_id) is not None
        # Human should still be there
        assert await db.get(Highlight, human_id) is not None
        # Suggested AI highlight should be gone
        assert await db.get(Highlight, suggested_id) is None

        # A tag job should be queued
        result = await db.execute(
            select(Job).where(
                Job.conversation_id == sample_conversation.id,
                Job.kind == "tag",
                Job.status == "queued",
            )
        )
        assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_reprocess_enqueues_tag_job(auth_client: AsyncClient, sample_conversation):
    """Reprocess should enqueue a tag job that chains to analyze."""
    r = await auth_client.post(f"/api/conversations/{sample_conversation.id}/reprocess")
    assert r.status_code == 200

    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        result = await db.execute(
            select(Job).where(
                Job.conversation_id == sample_conversation.id,
                Job.kind == "tag",
            )
        )
        jobs = result.scalars().all()
        assert len(jobs) >= 1


@pytest.mark.asyncio
async def test_reprocess_nonexistent_conversation_404(auth_client: AsyncClient):
    r = await auth_client.post("/api/conversations/99999/reprocess")
    assert r.status_code == 404
