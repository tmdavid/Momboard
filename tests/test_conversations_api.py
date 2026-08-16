"""T05: Conversations CRUD tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_conversation_returns_201_and_enqueues_ingest(auth_client: AsyncClient):
    r = await auth_client.post(
        "/api/conversations",
        json={
            "title": "Acme Watches discovery call",
            "happened_at": "2026-08-10T10:00:00Z",
            "interviewer": "David",
            "company": {"name": "Acme Watches"},
            "contacts": [{"name": "Jane Doe", "role": "Brand Manager"}],
            "transcript": "David: hi\nJane: hello",
            "transcript_format": "name_colon",
            "meta": {"deal_stage": "discovery", "plan": "enterprise"},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "processing"
    assert "id" in body


@pytest.mark.asyncio
async def test_list_conversations(auth_client: AsyncClient):
    # Create two conversations
    await auth_client.post(
        "/api/conversations",
        json={"title": "Call 1", "transcript": "David: hi\nAlice: hey", "transcript_format": "name_colon"},
    )
    await auth_client.post(
        "/api/conversations",
        json={"title": "Call 2", "transcript": "David: hello\nBob: yo", "transcript_format": "name_colon"},
    )

    r = await auth_client.get("/api/conversations")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    assert len(body["items"]) >= 2


@pytest.mark.asyncio
async def test_list_filter_by_q(auth_client: AsyncClient):
    await auth_client.post(
        "/api/conversations",
        json={"title": "Unique Title XYZ", "transcript": "David: test\nBob: ok", "transcript_format": "name_colon"},
    )
    r = await auth_client.get("/api/conversations", params={"q": "Unique Title XYZ"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any("Unique Title XYZ" in item["title"] for item in body["items"])


@pytest.mark.asyncio
async def test_get_conversation_detail(auth_client: AsyncClient):
    cr = await auth_client.post(
        "/api/conversations",
        json={"title": "Detail Test", "transcript": "David: hi\nMaria: hello", "transcript_format": "name_colon"},
    )
    convo_id = cr.json()["id"]

    r = await auth_client.get(f"/api/conversations/{convo_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Detail Test"
    assert body["status"] == "processing"


@pytest.mark.asyncio
async def test_get_nonexistent_conversation_404(auth_client: AsyncClient):
    r = await auth_client.get("/api/conversations/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_conversation(auth_client: AsyncClient):
    cr = await auth_client.post(
        "/api/conversations",
        json={"title": "Original", "transcript": "David: hi\nBob: hey", "transcript_format": "name_colon"},
    )
    convo_id = cr.json()["id"]

    r = await auth_client.patch(f"/api/conversations/{convo_id}", json={"title": "Updated"})
    assert r.status_code == 200

    detail = await auth_client.get(f"/api/conversations/{convo_id}")
    assert detail.json()["title"] == "Updated"


@pytest.mark.asyncio
async def test_delete_conversation(auth_client: AsyncClient):
    cr = await auth_client.post(
        "/api/conversations",
        json={"title": "To Delete", "transcript": "David: hi\nBob: hey", "transcript_format": "name_colon"},
    )
    convo_id = cr.json()["id"]

    r = await auth_client.delete(f"/api/conversations/{convo_id}")
    assert r.status_code == 204

    r2 = await auth_client.get(f"/api/conversations/{convo_id}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_company_get_or_create(auth_client: AsyncClient):
    """Creating two conversations with same company name should reuse company."""
    await auth_client.post(
        "/api/conversations",
        json={"title": "Call 1", "company": {"name": "Acme"}, "transcript": "A: hi\nB: hey", "transcript_format": "name_colon"},
    )
    await auth_client.post(
        "/api/conversations",
        json={"title": "Call 2", "company": {"name": "acme"}, "transcript": "A: hi\nB: hey", "transcript_format": "name_colon"},
    )

    companies = await auth_client.get("/api/companies")
    acme_companies = [c for c in companies.json() if c["name"].lower() == "acme"]
    assert len(acme_companies) == 1
