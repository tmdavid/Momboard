"""Tests for custom-taxonomy origin/category (T47 Step 2)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag
from app.taxonomy import find_near_duplicate_category, normalize_category


@pytest.mark.asyncio
async def test_seed_marks_shipped_tags_as_core(seeded_db: AsyncSession) -> None:
    """All 12 shipped taxonomy tags are origin=core with no category."""
    rows = (await seeded_db.execute(select(Tag))).scalars().all()
    assert len(rows) == 12
    assert all(t.origin == "core" for t in rows)
    assert all(t.category is None for t in rows)


@pytest.mark.asyncio
async def test_tag_defaults_to_custom_origin(db_session: AsyncSession) -> None:
    """A tag created without an explicit origin defaults to custom."""
    tag = Tag(key="k_slack", emoji="💬", name="Slack", sort_order=99)
    db_session.add(tag)
    await db_session.flush()
    fetched = await db_session.get(Tag, "k_slack")
    assert fetched is not None
    assert fetched.origin == "custom"
    assert fetched.category is None


@pytest.mark.asyncio
async def test_list_tags_exposes_origin_and_category(
    auth_client: AsyncClient, seeded_db: AsyncSession
) -> None:
    """GET /api/tags returns origin + category on every tag."""
    resp = await auth_client.get("/api/tags")
    assert resp.status_code == 200
    body = resp.json()
    assert body
    sample = body[0]
    assert sample["origin"] == "core"
    assert "category" in sample


@pytest.mark.asyncio
async def test_create_custom_tag_with_category(
    auth_client: AsyncClient, seeded_db: AsyncSession
) -> None:
    """Admin can create a custom tag carrying origin=custom + a category."""
    resp = await auth_client.post(
        "/api/tags",
        json={
            "key": "channel_slack",
            "emoji": "💬",
            "name": "Slack channel",
            "sort_order": 50,
            "is_active": True,
            "origin": "custom",
            "category": "channel",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["origin"] == "custom"
    assert data["category"] == "channel"

    fetched = await seeded_db.get(Tag, "channel_slack")
    assert fetched is not None
    assert fetched.category == "channel"


@pytest.mark.asyncio
async def test_create_tag_defaults_origin_custom_when_omitted(
    auth_client: AsyncClient, seeded_db: AsyncSession
) -> None:
    """Omitting origin/category on create yields a custom, uncategorized tag."""
    resp = await auth_client.post(
        "/api/tags",
        json={
            "key": "misc_thing",
            "emoji": "🔖",
            "name": "Misc",
            "sort_order": 51,
            "is_active": True,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["origin"] == "custom"
    assert data["category"] is None


@pytest.mark.asyncio
async def test_patch_tag_sets_category(
    auth_client: AsyncClient, seeded_db: AsyncSession
) -> None:
    """A tag's category can be set via PATCH."""
    await auth_client.post(
        "/api/tags",
        json={
            "key": "p_billing",
            "emoji": "💳",
            "name": "Billing",
            "sort_order": 52,
            "is_active": True,
        },
    )
    resp = await auth_client.patch("/api/tags/p_billing", json={"category": "product"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == "product"


# --- near-duplicate category helper ---


def test_normalize_category_trims_and_blanks() -> None:
    assert normalize_category("  Channel  ") == "Channel"
    assert normalize_category("   ") is None
    assert normalize_category(None) is None


def test_near_duplicate_flags_plural_and_case() -> None:
    existing = ["channel", "product", "outcome"]
    assert find_near_duplicate_category("channels", existing) == "channel"
    assert find_near_duplicate_category("Channel", existing) is None  # exact (case) = reuse
    assert find_near_duplicate_category("Prodct", existing) == "product"


def test_near_duplicate_returns_none_for_distinct() -> None:
    existing = ["channel", "product"]
    assert find_near_duplicate_category("pricing", existing) is None
    assert find_near_duplicate_category("segment", []) is None
