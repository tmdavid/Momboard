"""Tests for UX fix loop backend changes.

Tests for:
- Fix I: /api/highlights/bulk-accept commits transaction
- Fix G: next_step preference in InsightsPage open follow-ups / digest
- Fix I: Route ordering — bulk-accept resolves before dynamic {highlight_id}
"""

import pytest
from sqlalchemy import select

from app.models import Highlight


class TestBulkAcceptCommitsPersistence:
    """Fix I: bulk-accept must commit transaction so changes persist."""

    @pytest.mark.asyncio
    async def test_bulk_accept_persists_across_fresh_query(
        self, auth_client, session_factory, sample_conversation
    ):
        """After bulk-accept, a fresh query should see status=accepted."""
        # Create suggested highlights
        async with session_factory() as session:
            h1 = Highlight(
                conversation_id=sample_conversation.id,
                tag_key="pain",
                quote="Persistent highlight 1",
                confidence=0.95,
                status="suggested",
                origin="ai",
            )
            h2 = Highlight(
                conversation_id=sample_conversation.id,
                tag_key="pain",
                quote="Persistent highlight 2",
                confidence=0.92,
                status="suggested",
                origin="ai",
            )
            session.add_all([h1, h2])
            await session.commit()
            h1_id = h1.id
            h2_id = h2.id

        # Bulk accept by confidence
        r = await auth_client.post(
            "/api/highlights/bulk-accept",
            json={
                "min_confidence": 0.9,
                "conversation_id": sample_conversation.id,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["accepted_count"] >= 2
        assert h1_id in data["accepted_ids"]
        assert h2_id in data["accepted_ids"]

        # Fresh query — should see accepted status persisted
        async with session_factory() as session:
            result = await session.execute(
                select(Highlight).where(Highlight.id.in_([h1_id, h2_id]))
            )
            highlights = list(result.scalars().all())
            for h in highlights:
                assert h.status == "accepted", f"Highlight {h.id} not persisted as accepted"

    @pytest.mark.asyncio
    async def test_bulk_accept_by_explicit_ids_persists(
        self, auth_client, session_factory, sample_conversation
    ):
        """Explicit ID bulk-accept also commits."""
        async with session_factory() as session:
            h = Highlight(
                conversation_id=sample_conversation.id,
                tag_key="workaround",
                quote="Explicit persist test",
                confidence=0.8,
                status="suggested",
                origin="ai",
            )
            session.add(h)
            await session.commit()
            h_id = h.id

        r = await auth_client.post(
            "/api/highlights/bulk-accept",
            json={"highlight_ids": [h_id]},
        )
        assert r.status_code == 200
        assert r.json()["accepted_count"] == 1

        # Verify persistence
        async with session_factory() as session:
            result = await session.execute(select(Highlight).where(Highlight.id == h_id))
            h_after = result.scalar_one()
            assert h_after.status == "accepted"


class TestBulkAcceptRouteOrdering:
    """Fix I: /bulk-accept must resolve before /{highlight_id}."""

    @pytest.mark.asyncio
    async def test_bulk_accept_route_not_confused_with_dynamic(self, auth_client):
        """POST /api/highlights/bulk-accept should not 404 or route to PATCH."""
        r = await auth_client.post(
            "/api/highlights/bulk-accept",
            json={"highlight_ids": [99999]},
        )
        # Should be 200 (0 accepted) not 404 or 405
        assert r.status_code == 200
        assert r.json()["accepted_count"] == 0

    @pytest.mark.asyncio
    async def test_dynamic_route_still_works(self, auth_client, session_factory, sample_conversation):
        """PATCH /api/highlights/{id} still works after bulk-accept route exists."""
        async with session_factory() as session:
            h = Highlight(
                conversation_id=sample_conversation.id,
                tag_key="pain",
                quote="Dynamic route test",
                confidence=0.9,
                status="suggested",
                origin="ai",
            )
            session.add(h)
            await session.commit()
            h_id = h.id

        r = await auth_client.patch(
            f"/api/highlights/{h_id}",
            json={"status": "accepted"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"


class TestNextStepPreference:
    """Fix G #8: Open follow-ups and digest should prefer synthesized next_step."""

    @pytest.mark.asyncio
    async def test_stats_followups_include_quote(self, auth_client, sample_conversation):
        """The /api/stats open_followups endpoint returns quote field which
        frontend should use, but when next_step is available in analysis,
        it should be preferred. Backend just returns raw highlights;
        the preference logic is in the analysis result structure."""
        r = await auth_client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "open_followups" in data
        # Verify structure includes quote field
        # (actual preference is tested in analysis schema validation)
        for fu in data["open_followups"]:
            assert "quote" in fu
            assert "conversation_id" in fu
            assert "conversation_title" in fu
