"""v0.5 D7: which taxonomy tagged each call, and an honest 'not yet retagged' count."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.llm.client import FakeLLMClient
from app.llm.tagging import run_tag
from app.models import Conversation, Highlight, Tag, Utterance, utcnow
from app.seed import seed_tags
from app.services.taxonomy_version import get_taxonomy_version, stale_call_counts

PAIN = "Every Monday I export the report to Excel and clean it by hand"


async def add_call(db, title="c", *, version=None, tagged_at=None, created=None, source="upload", status="ready"):
    c = Conversation(title=title, status=status, source=source, raw_transcript="x",
                     transcript_format="name_colon", taxonomy_version=version, tagged_at=tagged_at)
    if created:
        c.created_at = created
    db.add(c)
    await db.flush()
    db.add(Utterance(conversation_id=c.id, idx=0, speaker_label="Maria", speaker_side="them", text=PAIN))
    await db.flush()
    return c


async def add_ai_highlight(db, call, tag, when, quote="some quote about weekly exports and spreadsheets"):
    h = Highlight(conversation_id=call.id, tag_key=tag, quote=quote, confidence=0.9, status="suggested", origin="ai")
    h.created_at = when
    db.add(h)
    await db.flush()
    return h


class TestVersionCounter:
    @pytest.mark.asyncio
    async def test_starts_at_zero(self, session_factory):
        async with session_factory() as db:
            assert await get_taxonomy_version(db) == 0

    @pytest.mark.asyncio
    async def test_creating_a_tag_bumps_the_version_and_stamps_the_tag(self, auth_client: AsyncClient, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await db.commit()
        r = await auth_client.post("/api/tags", json={
            "key": "impersonation", "emoji": "🎭", "name": "Impersonation", "origin": "custom",
            "category": "product", "sort_order": 70, "is_active": True})
        assert r.status_code == 201 and r.json()["added_in_version"] == 1
        r2 = await auth_client.post("/api/tags", json={
            "key": "pricing", "emoji": "💶", "name": "Pricing", "origin": "custom", "sort_order": 71, "is_active": True})
        assert r2.json()["added_in_version"] == 2
        status = (await auth_client.get("/api/taxonomy/status")).json()
        assert status["version"] == 2

    @pytest.mark.asyncio
    async def test_reactivating_a_tag_counts_as_adding_it(self, auth_client: AsyncClient, session_factory):
        await auth_client.post("/api/tags", json={"key": "t1", "emoji": "x", "name": "T1", "origin": "custom", "sort_order": 1, "is_active": False})
        before = (await auth_client.get("/api/taxonomy/status")).json()["version"]
        r = await auth_client.patch("/api/tags/t1", json={"is_active": True})
        assert r.json()["added_in_version"] == before + 1
        # editing something else does not bump
        await auth_client.patch("/api/tags/t1", json={"name": "T1b"})
        assert (await auth_client.get("/api/taxonomy/status")).json()["version"] == before + 1

    @pytest.mark.asyncio
    async def test_seeding_does_not_bump(self, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await db.commit()
            assert await get_taxonomy_version(db) == 0


class TestRunTagStamps:
    @pytest.mark.asyncio
    async def test_a_tagging_run_records_the_version_and_time(self, session_factory):
        from app.services.app_settings import set_setting

        async with session_factory() as db:
            await seed_tags(db)
            await set_setting(db, "taxonomy_version", 3)
            c = await add_call(db)
            await db.commit()
            cid = c.id
        fake = FakeLLMClient()
        fake.set_fixture("tagger", {"highlights": []})
        async with session_factory() as db:
            await run_tag(db, cid, fake)
            await db.commit()
        async with session_factory() as db:
            c = await db.get(Conversation, cid)
        assert c.taxonomy_version == 3 and c.tagged_at is not None


class TestStaleCounts:
    async def _tag(self, db, key, version):
        db.add(Tag(key=key, emoji="x", name=key.title(), origin="custom", is_active=True, sort_order=80, added_in_version=version))
        await db.flush()

    @pytest.mark.asyncio
    async def test_calls_tagged_under_an_older_version_are_stale(self, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await self._tag(db, "impersonation", 2)
            await add_call(db, "old", version=1, tagged_at=utcnow())
            await add_call(db, "current", version=2, tagged_at=utcnow())
            await add_call(db, "newer", version=5, tagged_at=utcnow())
            await db.commit()
            counts = await stale_call_counts(db, ["impersonation"])
        assert counts["impersonation"].stale_calls == 1 and counts["impersonation"].total_calls == 3

    @pytest.mark.asyncio
    async def test_legacy_calls_with_no_version_predate_any_tag_added_since(self, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await self._tag(db, "impersonation", 1)
            await add_call(db, "legacy", version=None)
            await db.commit()
            counts = await stale_call_counts(db, ["impersonation"])
        assert counts["impersonation"].stale_calls == 1

    @pytest.mark.asyncio
    async def test_a_tag_that_existed_from_the_start_is_never_stale(self, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await add_call(db, "legacy", version=None)
            await db.commit()
            counts = await stale_call_counts(db, ["pain"])
        assert counts["pain"].stale_calls == 0

    @pytest.mark.asyncio
    async def test_legacy_estimate_old_calls_before_a_tags_first_use_are_stale(self, session_factory):
        """Sample tag was added to the live taxonomy AFTER most calls were tagged, but it has no
        version stamp. Estimate from the data: calls tagged well before its first use predate it."""
        now = utcnow()
        async with session_factory() as db:
            await seed_tags(db)
            await db.execute(Tag.__table__.insert().values(key="sample_tag", emoji="x", name="Sample tag", origin="custom", is_active=True, sort_order=60, min_confidence=0.5, added_in_version=0))
            early = await add_call(db, "early", version=None)
            await add_ai_highlight(db, early, "pain", now - timedelta(days=30))
            late = await add_call(db, "late", version=None)
            await add_ai_highlight(db, late, "pain", now - timedelta(days=1))
            await add_ai_highlight(db, late, "sample_tag", now - timedelta(days=1))   # first use of the tag
            await db.commit()
            counts = await stale_call_counts(db, ["sample_tag"])
        assert counts["sample_tag"].stale_calls == 1       # only 'early'; 'late' produced the first use itself
        assert counts["sample_tag"].total_calls == 2

    @pytest.mark.asyncio
    async def test_unused_legacy_tag_has_no_basis_for_a_claim(self, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await db.execute(Tag.__table__.insert().values(key="never_used", emoji="x", name="Never", origin="custom", is_active=True, sort_order=61, min_confidence=0.5, added_in_version=0))
            await add_call(db, "legacy", version=None)
            await db.commit()
            counts = await stale_call_counts(db, ["never_used"])
        assert counts["never_used"].stale_calls == 0

    @pytest.mark.asyncio
    async def test_simulated_and_unfinished_calls_are_not_counted(self, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await self._tag(db, "impersonation", 1)
            await add_call(db, "real", version=0, tagged_at=utcnow())
            await add_call(db, "sim", version=0, source="simulator")
            await add_call(db, "busy", version=0, status="processing")
            await db.commit()
            counts = await stale_call_counts(db, ["impersonation"])
        assert counts["impersonation"].total_calls == 1


class TestApi:
    @pytest.mark.asyncio
    async def test_status_reports_progress_on_the_current_taxonomy(self, auth_client: AsyncClient, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await add_call(db, "a", version=None)
            await add_call(db, "b", version=None)
            await db.commit()
        await auth_client.post("/api/tags", json={"key": "impersonation", "emoji": "x", "name": "Impersonation", "origin": "custom", "sort_order": 70, "is_active": True})
        async with session_factory() as db:
            c = (await db.execute(select(Conversation).where(Conversation.title == "a"))).scalar_one()
            c.taxonomy_version = 1
            await db.commit()
        body = (await auth_client.get("/api/taxonomy/status")).json()
        assert body["version"] == 1
        assert body["total_calls"] == 2 and body["calls_on_current"] == 1
        assert [t["key"] for t in body["tags"]] == ["impersonation"]
        assert body["tags"][0]["stale_calls"] == 1

    @pytest.mark.asyncio
    async def test_stale_endpoint_answers_for_the_filtered_tags(self, auth_client: AsyncClient, session_factory):
        async with session_factory() as db:
            await seed_tags(db)
            await add_call(db, "a", version=None)
            await db.commit()
        await auth_client.post("/api/tags", json={"key": "impersonation", "emoji": "x", "name": "Impersonation", "origin": "custom", "sort_order": 70, "is_active": True})
        r = await auth_client.get("/api/taxonomy/stale", params={"tag": ["impersonation", "pain"]})
        items = {i["key"]: i for i in r.json()["items"]}
        assert items["impersonation"]["stale_calls"] == 1 and items["impersonation"]["name"] == "Impersonation"
        assert items["pain"]["stale_calls"] == 0

    @pytest.mark.asyncio
    async def test_requires_login(self, client: AsyncClient):
        assert (await client.get("/api/taxonomy/status")).status_code == 401
        assert (await client.get("/api/taxonomy/stale")).status_code == 401
