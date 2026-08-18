"""Tests for T34: Staging inbox — lifecycle, dedupe, API."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import (
    DuplicateSourceRefError,
    ignore_inbox_item,
    import_inbox_item,
    submit_to_inbox,
)


@pytest.mark.asyncio
async def test_submit_to_inbox_creates_pending_item(seeded_db: AsyncSession):
    item = await submit_to_inbox(
        seeded_db,
        source="gmeet",
        source_ref="gdrive:doc123",
        title="Test Meeting",
        raw_content="Speaker: Hello\nOther: Hi",
        content_format="name_colon",
    )
    await seeded_db.commit()

    assert item.id is not None
    assert item.status == "pending_import"
    assert item.source == "gmeet"
    assert item.source_ref == "gdrive:doc123"


@pytest.mark.asyncio
async def test_source_ref_dedupe_raises_on_duplicate(seeded_db: AsyncSession):
    await submit_to_inbox(
        seeded_db,
        source="gmeet",
        source_ref="gdrive:dup1",
        title="First",
        raw_content="content",
    )
    await seeded_db.commit()

    with pytest.raises(DuplicateSourceRefError) as exc_info:
        await submit_to_inbox(
            seeded_db,
            source="gmeet",
            source_ref="gdrive:dup1",
            title="Second",
            raw_content="other content",
        )

    assert "dup1" in str(exc_info.value)


@pytest.mark.asyncio
async def test_import_creates_conversation_and_enqueues_job(seeded_db: AsyncSession):
    item = await submit_to_inbox(
        seeded_db,
        source="gmeet",
        source_ref="gdrive:import1",
        title="Import Test",
        raw_content="David: hello\nMaria: hi there",
        content_format="name_colon",
    )
    await seeded_db.flush()

    imported = await import_inbox_item(
        seeded_db,
        item.id,
        interviewer="David",
        company_name="TestCo",
    )
    await seeded_db.commit()

    assert imported.status == "imported"
    assert imported.conversation_id is not None
    assert imported.imported_at is not None


@pytest.mark.asyncio
async def test_import_rejects_non_pending_item(seeded_db: AsyncSession):
    item = await submit_to_inbox(
        seeded_db,
        source="test",
        source_ref="ref:1",
        title="T",
        raw_content="c",
    )
    await ignore_inbox_item(seeded_db, item.id)
    await seeded_db.commit()

    with pytest.raises(ValueError, match="Cannot import"):
        await import_inbox_item(seeded_db, item.id)


@pytest.mark.asyncio
async def test_ignore_sets_status(seeded_db: AsyncSession):
    item = await submit_to_inbox(
        seeded_db,
        source="test",
        source_ref="ref:ign1",
        title="Ignore me",
        raw_content="spam",
    )
    await seeded_db.flush()

    ignored = await ignore_inbox_item(seeded_db, item.id)
    assert ignored.status == "ignored"


@pytest.mark.asyncio
async def test_parse_error_status_stored(seeded_db: AsyncSession):
    item = await submit_to_inbox(
        seeded_db,
        source="gmeet",
        source_ref="gdrive:bad1",
        title="Bad Doc",
        raw_content="unparseable garbage",
        status="parse_error",
        parse_error="Could not parse Meet Doc: too short",
    )
    await seeded_db.commit()

    assert item.status == "parse_error"
    assert item.parse_error is not None


@pytest.mark.asyncio
async def test_inbox_api_list(auth_client: AsyncClient):
    # Create some items
    for i in range(3):
        await auth_client.post("/api/inbox", json={
            "source": "test",
            "source_ref": f"api-test:{i}",
            "title": f"Item {i}",
            "raw_content": f"content {i}",
        })

    r = await auth_client.get("/api/inbox")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 3
    assert len(body["items"]) >= 3


@pytest.mark.asyncio
async def test_inbox_api_create_and_dedupe(auth_client: AsyncClient):
    payload = {
        "source": "mcp",
        "source_ref": "mcp:unique1",
        "title": "MCP Submission",
        "raw_content": "transcript text",
    }

    r1 = await auth_client.post("/api/inbox", json=payload)
    assert r1.status_code == 201

    r2 = await auth_client.post("/api/inbox", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_inbox_api_import_flow(auth_client: AsyncClient):
    # Create
    r = await auth_client.post("/api/inbox", json={
        "source": "gmeet",
        "source_ref": "gdrive:flow1",
        "title": "Flow Test",
        "raw_content": "David: hello\nMaria: hi",
    })
    assert r.status_code == 201
    item_id = r.json()["id"]

    # Import
    r2 = await auth_client.post(f"/api/inbox/{item_id}/import", json={
        "interviewer": "David",
        "company_name": "FlowCo",
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "imported"
    assert r2.json()["conversation_id"] is not None


@pytest.mark.asyncio
async def test_inbox_api_ignore(auth_client: AsyncClient):
    r = await auth_client.post("/api/inbox", json={
        "source": "test",
        "source_ref": "gdrive:ign-api",
        "title": "Ignore API",
        "raw_content": "x",
    })
    item_id = r.json()["id"]

    r2 = await auth_client.post(f"/api/inbox/{item_id}/ignore")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_inbox_filter_by_status(auth_client: AsyncClient):
    await auth_client.post("/api/inbox", json={
        "source": "test",
        "source_ref": "filt:1",
        "title": "F1",
        "raw_content": "c",
    })

    r = await auth_client.get("/api/inbox?status=pending_import")
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["status"] == "pending_import" for i in items)
