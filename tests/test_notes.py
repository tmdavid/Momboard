"""Notes API tests: get, put, optimistic concurrency conflict check."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_note_creates_empty_note_if_not_exists(
    auth_client: AsyncClient, sample_conversation,
):
    """GET note should auto-create an empty note for the conversation."""
    r = await auth_client.get(f"/api/conversations/{sample_conversation.id}/note")
    assert r.status_code == 200
    body = r.json()
    assert body["body_md"] == ""
    assert body["conversation_id"] == sample_conversation.id
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_put_note_creates_and_updates(auth_client: AsyncClient, sample_conversation):
    """PUT note should create if not exists, then update."""
    now = datetime.now(UTC)
    r = await auth_client.put(
        f"/api/conversations/{sample_conversation.id}/note",
        json={
            "body_md": "# Meeting Notes\n\n- Key insight: pain is real",
            "updated_at": now.isoformat(),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "Meeting Notes" in body["body_md"]
    assert body["conversation_id"] == sample_conversation.id

    # Read it back
    r2 = await auth_client.get(f"/api/conversations/{sample_conversation.id}/note")
    assert "Meeting Notes" in r2.json()["body_md"]


@pytest.mark.asyncio
async def test_put_note_conflict_detection(auth_client: AsyncClient, sample_conversation):
    """PUT with stale updated_at should return 409 conflict."""
    now = datetime.now(UTC)

    # First write
    r1 = await auth_client.put(
        f"/api/conversations/{sample_conversation.id}/note",
        json={"body_md": "First write", "updated_at": now.isoformat()},
    )
    assert r1.status_code == 200

    # Second write with an OLD timestamp (simulating concurrent edit)
    stale_time = now - timedelta(hours=1)
    r2 = await auth_client.put(
        f"/api/conversations/{sample_conversation.id}/note",
        json={"body_md": "Conflicting write", "updated_at": stale_time.isoformat()},
    )
    assert r2.status_code == 409
    assert "modified" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_put_note_within_tolerance_succeeds(
    auth_client: AsyncClient, sample_conversation,
):
    """PUT with timestamp within 1 second tolerance should succeed."""
    now = datetime.now(UTC)

    # First write
    r1 = await auth_client.put(
        f"/api/conversations/{sample_conversation.id}/note",
        json={"body_md": "Content A", "updated_at": now.isoformat()},
    )
    assert r1.status_code == 200
    saved_at = r1.json()["updated_at"]

    # Second write with very recent timestamp (within tolerance)
    r2 = await auth_client.put(
        f"/api/conversations/{sample_conversation.id}/note",
        json={"body_md": "Content B", "updated_at": saved_at},
    )
    assert r2.status_code == 200
    assert r2.json()["body_md"] == "Content B"


@pytest.mark.asyncio
async def test_note_for_nonexistent_conversation_404(auth_client: AsyncClient):
    r = await auth_client.get("/api/conversations/99999/note")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_put_note_nonexistent_conversation_404(auth_client: AsyncClient):
    now = datetime.now(UTC)
    r = await auth_client.put(
        "/api/conversations/99999/note",
        json={"body_md": "test", "updated_at": now.isoformat()},
    )
    assert r.status_code == 404
