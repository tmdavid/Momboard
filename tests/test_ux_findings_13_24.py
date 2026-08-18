"""Tests for UX findings #13-#24 backend API changes.

Tests for:
- #14: Bulk accept highlights API
- #15: Company filtering (active_only)
- #19: Simulator sessions listing
- #22: Settings status API (safe config, no secrets)
"""

import pytest

from app.api.settings import _mask_key
from app.models import Company, Conversation, Highlight


class TestSettingsStatus:
    """#22: Settings status API returns safe config only."""

    @pytest.mark.asyncio
    async def test_settings_status_endpoint(self, auth_client):
        """Should return structured status with masked keys."""
        r = await auth_client.get("/api/settings/status")
        assert r.status_code == 200
        data = r.json()
        assert "llm" in data
        assert "vexa" in data
        assert "gdrive" in data
        assert "slack" in data
        assert "digest" in data
        assert "taxonomy_count" in data
        assert "active_company_count" in data

    @pytest.mark.asyncio
    async def test_settings_status_masks_api_key(self, auth_client):
        """API key should be masked."""
        r = await auth_client.get("/api/settings/status")
        assert r.status_code == 200
        data = r.json()
        hint = data["llm"]["api_key_hint"]
        # Should be "not set" (test env has no key) or masked
        assert hint == "not set" or "•••" in hint

    @pytest.mark.asyncio
    async def test_settings_status_never_exposes_secrets(self, auth_client):
        """Response should not contain database URL or session secret."""
        r = await auth_client.get("/api/settings/status")
        assert r.status_code == 200
        text = r.text
        assert "sqlite" not in text
        assert "test-secret" not in text

    @pytest.mark.asyncio
    async def test_settings_status_requires_auth(self, client):
        """Unauthenticated requests rejected."""
        r = await client.get("/api/settings/status")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_settings_taxonomy_count(self, auth_client):
        """taxonomy_count should match seeded tags."""
        r = await auth_client.get("/api/settings/status")
        assert r.status_code == 200
        data = r.json()
        # Tags are seeded in conftest; should be > 0
        assert data["taxonomy_count"] > 0


class TestCompanyFiltering:
    """#15: Hide zero-conversation companies from filter dropdowns."""

    @pytest.mark.asyncio
    async def test_companies_active_only_excludes_empty(
        self, auth_client, session_factory
    ):
        """active_only=true should exclude companies with zero conversations."""
        # Create a company with no conversations
        async with session_factory() as session:
            ghost = Company(name="GhostCorp", domain="ghost.com")
            session.add(ghost)
            await session.commit()

        r = await auth_client.get("/api/companies?active_only=true")
        assert r.status_code == 200
        names = [c["name"] for c in r.json()]
        assert "GhostCorp" not in names

    @pytest.mark.asyncio
    async def test_companies_without_active_only_includes_all(
        self, auth_client, session_factory
    ):
        """Without active_only, ghost companies appear."""
        async with session_factory() as session:
            ghost = Company(name="GhostCo2", domain="ghost2.com")
            session.add(ghost)
            await session.commit()

        r = await auth_client.get("/api/companies")
        assert r.status_code == 200
        names = [c["name"] for c in r.json()]
        assert "GhostCo2" in names

    @pytest.mark.asyncio
    async def test_active_company_has_conversation(
        self, auth_client, sample_conversation
    ):
        """Companies with conversations should appear with active_only."""
        r = await auth_client.get("/api/companies?active_only=true")
        assert r.status_code == 200
        names = [c["name"] for c in r.json()]
        assert "Acme Watches" in names


class TestBulkAcceptHighlights:
    """#14: Bulk accept highlights API."""

    @pytest.mark.asyncio
    async def test_bulk_accept_requires_filter(self, auth_client):
        """Must specify at least one filter."""
        r = await auth_client.post("/api/highlights/bulk-accept", json={})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_bulk_accept_by_confidence(
        self, auth_client, session_factory, sample_conversation
    ):
        """Accept all suggested >= 0.9 in a conversation."""
        # Add a high-confidence suggested highlight
        async with session_factory() as session:
            h = Highlight(
                conversation_id=sample_conversation.id,
                tag_key="pain",
                quote="It takes 2 hours every Monday",
                confidence=0.95,
                status="suggested",
                origin="ai",
            )
            session.add(h)
            await session.commit()
            h_id = h.id

        r = await auth_client.post(
            "/api/highlights/bulk-accept",
            json={
                "min_confidence": 0.9,
                "conversation_id": sample_conversation.id,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["accepted_count"] >= 1
        assert h_id in data["accepted_ids"]

    @pytest.mark.asyncio
    async def test_bulk_accept_by_tag(
        self, auth_client, session_factory, sample_conversation
    ):
        """Accept all suggested of a specific tag."""
        async with session_factory() as session:
            h = Highlight(
                conversation_id=sample_conversation.id,
                tag_key="workaround",
                quote="We export to Excel",
                confidence=0.7,
                status="suggested",
                origin="ai",
            )
            session.add(h)
            await session.commit()

        r = await auth_client.post(
            "/api/highlights/bulk-accept",
            json={"tag_key": "workaround", "conversation_id": sample_conversation.id},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["accepted_count"] >= 1

    @pytest.mark.asyncio
    async def test_bulk_accept_explicit_ids(self, auth_client):
        """Non-existent IDs return 0 accepted."""
        r = await auth_client.post(
            "/api/highlights/bulk-accept",
            json={"highlight_ids": [99999]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["accepted_count"] == 0
        assert data["accepted_ids"] == []


class TestSimulatorSessionsListing:
    """#19: Simulator past session history listing."""

    @pytest.mark.asyncio
    async def test_list_simulator_sessions(self, auth_client):
        """Should return sessions list (may be empty if none created)."""
        r = await auth_client.get("/api/simulator/sessions")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_simulator_sessions_requires_auth(self, client):
        """Unauthenticated requests rejected."""
        r = await client.get("/api/simulator/sessions")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_simulator_session_with_data(
        self, auth_client, session_factory
    ):
        """Sessions with source=simulator should appear in listing."""
        async with session_factory() as session:
            convo = Conversation(
                title="Sim: Practice run",
                source="simulator",
                status="ready",
                raw_transcript="user: hi\npersona: hello",
            )
            session.add(convo)
            await session.commit()

        r = await auth_client.get("/api/simulator/sessions")
        assert r.status_code == 200
        data = r.json()
        titles = [s["title"] for s in data["items"]]
        assert "Sim: Practice run" in titles


def test_mask_key_reveals_no_secret_characters():
    secret = "sk-super-secret-tail"
    hint = _mask_key(secret)
    assert hint == "configured"
    assert not any(fragment in hint for fragment in ("sk-", "sup", "ail"))
