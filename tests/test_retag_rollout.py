"""v0.5 R1: retag in staged, resumable batches, without silently breaking what people built."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Conversation,
    Decision,
    DecisionEvidence,
    Highlight,
    Hypothesis,
    HypothesisLink,
    Job,
    Utterance,
    utcnow,
)
from app.seed import seed_tags
from app.services.app_settings import set_setting

QUOTE = "Every Monday I export the report to Excel and clean it by hand"


async def make_call(db, title, *, version=None, status="ready", source="upload", happened=None):
    c = Conversation(title=title, status=status, source=source, raw_transcript="x", transcript_format="name_colon",
                     taxonomy_version=version, happened_at=happened)
    db.add(c)
    await db.flush()
    u = Utterance(conversation_id=c.id, idx=0, speaker_label="Maria", speaker_side="them", text=QUOTE)
    db.add(u)
    await db.flush()
    return c, u


async def add_hl(db, call, utt, *, status="suggested", origin="ai", tag="pain", conf=0.9, quote=QUOTE):
    h = Highlight(conversation_id=call.id, utterance_id=utt.id, tag_key=tag, quote=quote, status=status, origin=origin, confidence=conf)
    db.add(h)
    await db.flush()
    return h


@pytest.fixture
async def seeded(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as db:
        await seed_tags(db)
        await db.commit()


class TestClearSuggestions:
    @pytest.mark.asyncio
    async def test_deletes_plain_suggestions_keeps_accepted_and_rejected(self, session_factory, seeded):
        from app.services.retag import clear_suggestions

        async with session_factory() as db:
            c, u = await make_call(db, "c")
            plain = await add_hl(db, c, u, quote="plain suggestion that nobody cited anywhere")
            accepted = await add_hl(db, c, u, status="accepted", origin="human", quote="a human accepted this one for sure")
            rejected = await add_hl(db, c, u, status="rejected", quote="a human rejected this other one entirely")
            await db.commit()
            deleted, protected = await clear_suggestions(db, c.id)
            await db.commit()
            left = {h.id for h in (await db.execute(select(Highlight))).scalars()}
        assert deleted == 1 and protected == 0
        assert left == {accepted.id, rejected.id} and plain.id not in left

    @pytest.mark.asyncio
    async def test_protects_a_suggestion_a_decision_cites(self, session_factory, seeded):
        from app.services.retag import clear_suggestions

        async with session_factory() as db:
            c, u = await make_call(db, "c")
            cited = await add_hl(db, c, u, quote="cited by a decision receipt in the app")
            d = Decision(title="D", rationale_md="r", status="proposed")
            db.add(d)
            await db.flush()
            db.add(DecisionEvidence(decision_id=d.id, highlight_id=cited.id))
            await db.commit()
            deleted, protected = await clear_suggestions(db, c.id)
            await db.commit()
            still = await db.get(Highlight, cited.id)
        assert (deleted, protected) == (0, 1) and still is not None

    @pytest.mark.asyncio
    async def test_protects_a_suggestion_with_a_confirmed_hypothesis_link_but_not_a_pending_one(self, session_factory, seeded):
        from app.services.retag import clear_suggestions

        async with session_factory() as db:
            c, u = await make_call(db, "c")
            confirmed = await add_hl(db, c, u, quote="a belief rests on this confirmed quote")
            pending = await add_hl(db, c, u, quote="the linker only suggested this one so far")
            hyp = Hypothesis(statement="A belief that is long enough", status="open")
            db.add(hyp)
            await db.flush()
            db.add_all([
                HypothesisLink(hypothesis_id=hyp.id, highlight_id=confirmed.id, stance="supports", origin="human", status="confirmed"),
                HypothesisLink(hypothesis_id=hyp.id, highlight_id=pending.id, stance="supports", origin="ai", status="suggested"),
            ])
            await db.commit()
            deleted, protected = await clear_suggestions(db, c.id)
            await db.commit()
            left = {h.id for h in (await db.execute(select(Highlight))).scalars()}
        assert (deleted, protected) == (1, 1)
        assert confirmed.id in left and pending.id not in left   # an unreviewed suggestion may go; the linker re-suggests

    @pytest.mark.asyncio
    async def test_protects_a_suggestion_a_decision_cites_even_when_it_is_the_only_evidence(self, session_factory, seeded):
        from app.services.retag import clear_suggestions

        async with session_factory() as db:
            c, u = await make_call(db, "c")
            only = await add_hl(db, c, u)
            d = Decision(title="D", rationale_md="r", status="decided")
            db.add(d)
            await db.flush()
            db.add(DecisionEvidence(decision_id=d.id, highlight_id=only.id))
            await db.commit()
            await clear_suggestions(db, c.id)
            await db.commit()
            ev = (await db.execute(select(DecisionEvidence))).scalar_one()
        assert ev.highlight_id == only.id and ev.invalid_reason is None   # receipt untouched


class TestReprocessEndpoint:
    @pytest.mark.asyncio
    async def test_reprocess_uses_the_protection(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            c, u = await make_call(db, "c")
            cited = await add_hl(db, c, u, quote="cited by a decision receipt in the app")
            plain = await add_hl(db, c, u, quote="nobody cited this one at all here")
            d = Decision(title="D", rationale_md="r", status="proposed")
            db.add(d)
            await db.flush()
            db.add(DecisionEvidence(decision_id=d.id, highlight_id=cited.id))
            await db.commit()
            cid, cited_id, plain_id = c.id, cited.id, plain.id
        r = await auth_client.post(f"/api/conversations/{cid}/reprocess")
        assert r.status_code == 200 and r.json()["status"] == "processing"
        async with session_factory() as db:
            ids = {h.id for h in (await db.execute(select(Highlight))).scalars()}
            jobs = (await db.execute(select(Job).where(Job.kind == "tag"))).scalars().all()
        assert cited_id in ids and plain_id not in ids and len(jobs) == 1


class TestBatchEndpoint:
    async def _calls(self, db, n, *, version=None, base_days=0, **kw):
        out = []
        for i in range(n):
            c, _ = await make_call(db, f"call {base_days + i}", version=version, happened=utcnow() - timedelta(days=base_days + i), **kw)
            out.append(c)
        return out

    @pytest.mark.asyncio
    async def test_queues_the_newest_eligible_calls_first(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            calls = await self._calls(db, 5)
            await db.commit()
            newest_two = [calls[0].id, calls[1].id]
        r = await auth_client.post("/api/taxonomy/retag", json={"limit": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["queued"] == 2 and body["remaining"] == 3 and body["ids"] == newest_two
        async with session_factory() as db:
            jobs = (await db.execute(select(Job).where(Job.kind == "tag"))).scalars().all()
            statuses = {c.id: c.status for c in (await db.execute(select(Conversation))).scalars()}
        assert {j.conversation_id for j in jobs} == set(newest_two)
        assert [statuses[i] for i in newest_two] == ["processing", "processing"]

    @pytest.mark.asyncio
    async def test_is_resumable_it_never_requeues_calls_already_on_the_current_taxonomy(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            await set_setting(db, "taxonomy_version", 2)
            await self._calls(db, 3, version=2, base_days=0)           # already current
            stale = await self._calls(db, 2, version=1, base_days=10)   # older taxonomy
            await db.commit()
        r = await auth_client.post("/api/taxonomy/retag", json={"limit": 100})
        assert r.json()["queued"] == 2 and r.json()["remaining"] == 0
        assert set(r.json()["ids"]) == {c.id for c in stale}

    @pytest.mark.asyncio
    async def test_legacy_calls_with_no_stamp_are_eligible(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            await self._calls(db, 2, version=None)
            await db.commit()
        assert (await auth_client.post("/api/taxonomy/retag", json={"limit": 10})).json()["queued"] == 2

    @pytest.mark.asyncio
    async def test_skips_busy_unfinished_and_simulated_calls(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            await self._calls(db, 1, status="processing")
            await self._calls(db, 1, status="failed")
            await self._calls(db, 1, source="simulator")
            await db.commit()
        body = (await auth_client.post("/api/taxonomy/retag", json={"limit": 10})).json()
        assert body["queued"] == 0 and body["remaining"] == 0

    @pytest.mark.asyncio
    async def test_running_it_twice_does_not_double_queue(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            await self._calls(db, 3)
            await db.commit()
        a = (await auth_client.post("/api/taxonomy/retag", json={"limit": 10})).json()
        b = (await auth_client.post("/api/taxonomy/retag", json={"limit": 10})).json()
        assert a["queued"] == 3 and b["queued"] == 0     # the first batch is 'processing' now

    @pytest.mark.asyncio
    async def test_dry_run_changes_nothing(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            await self._calls(db, 3)
            await db.commit()
        body = (await auth_client.post("/api/taxonomy/retag", json={"limit": 2, "dry_run": True})).json()
        assert body["queued"] == 0 and body["would_queue"] == 2 and body["remaining"] == 3
        async with session_factory() as db:
            assert (await db.execute(select(Job).where(Job.kind == "tag"))).first() is None

    @pytest.mark.asyncio
    async def test_reports_protected_highlights(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            c, u = await make_call(db, "c")
            cited = await add_hl(db, c, u)
            d = Decision(title="D", rationale_md="r", status="proposed")
            db.add(d)
            await db.flush()
            db.add(DecisionEvidence(decision_id=d.id, highlight_id=cited.id))
            await db.commit()
        body = (await auth_client.post("/api/taxonomy/retag", json={"limit": 10})).json()
        assert body["protected_highlights"] == 1

    @pytest.mark.asyncio
    async def test_limit_is_validated_and_admin_only(self, auth_client: AsyncClient, member_client: AsyncClient, client: AsyncClient, seeded):
        assert (await auth_client.post("/api/taxonomy/retag", json={"limit": 0})).status_code == 422
        assert (await auth_client.post("/api/taxonomy/retag", json={"limit": 501})).status_code == 422
        assert (await member_client.post("/api/taxonomy/retag", json={"limit": 10})).status_code == 403
        assert (await client.post("/api/taxonomy/retag", json={"limit": 10})).status_code == 401


class TestStatusProgressAndEstimate:
    @pytest.mark.asyncio
    async def test_status_reports_eligible_in_progress_and_a_time_estimate(self, auth_client: AsyncClient, session_factory, seeded):
        now = utcnow()
        async with session_factory() as db:
            calls = []
            for i in range(4):
                c, _ = await make_call(db, f"c{i}", version=None, happened=now - timedelta(days=i))
                calls.append(c)
            busy, _ = await make_call(db, "busy", status="processing", version=None)
            # finished jobs give a per-call duration: tag 20s + analyze 10s = 30s per call
            for kind, secs in (("tag", 20), ("analyze", 10)):
                for c in calls[:2]:
                    db.add(Job(conversation_id=c.id, kind=kind, status="done", started_at=now - timedelta(seconds=secs), finished_at=now))
            await db.commit()
        body = (await auth_client.get("/api/taxonomy/status")).json()
        assert body["eligible"] == 4 and body["in_progress"] == 1
        assert body["seconds_per_call"] == pytest.approx(30, abs=1)
        assert body["estimated_minutes"] is not None and body["estimated_minutes"] >= 1

    @pytest.mark.asyncio
    async def test_no_history_means_no_estimate(self, auth_client: AsyncClient, session_factory, seeded):
        async with session_factory() as db:
            await make_call(db, "c")
            await db.commit()
        body = (await auth_client.get("/api/taxonomy/status")).json()
        assert body["seconds_per_call"] is None and body["estimated_minutes"] is None


class TestBeforeAfterComparison:
    """After the pilot: 'compare tag counts before and after; watch for any tag that jumps or vanishes'."""

    async def _counts(self, session_factory, spec: dict[str, int], *, conf=0.9):
        async with session_factory() as db:
            c, u = await make_call(db, "base")
            n = 0
            for tag, count in spec.items():
                for i in range(count):
                    n += 1
                    db.add(Highlight(conversation_id=c.id, utterance_id=u.id, tag_key=tag, quote=f"{tag} quote number {n} with enough words",
                                     status="suggested", origin="ai", confidence=conf))
            await db.commit()

    @pytest.mark.asyncio
    async def test_compare_needs_a_snapshot_first(self, auth_client: AsyncClient, seeded):
        r = await auth_client.get("/api/taxonomy/compare")
        assert r.status_code == 200 and r.json()["snapshot"] is None and r.json()["rows"] == []

    @pytest.mark.asyncio
    async def test_snapshot_then_compare_flags_jumps_drops_new_and_vanished(self, auth_client: AsyncClient, session_factory, seeded):
        await self._counts(session_factory, {"pain": 20, "workaround": 12, "money": 10, "obstacle": 8})
        snap = await auth_client.post("/api/taxonomy/snapshot", json={"label": "before pilot"})
        assert snap.status_code == 200 and snap.json()["label"] == "before pilot"
        assert snap.json()["counts"]["pain"] == 20

        async with session_factory() as db:   # simulate the retag changing the distribution
            from sqlalchemy import delete
            await db.execute(delete(Highlight).where(Highlight.tag_key.in_(["workaround", "money"])))
            obstacle_ids = [h.id for h in (await db.execute(select(Highlight).where(Highlight.tag_key == "obstacle"))).scalars()]
            await db.execute(delete(Highlight).where(Highlight.id.in_(obstacle_ids[:5])))   # 8 -> 3
            c = (await db.execute(select(Conversation))).scalars().first()
            u = (await db.execute(select(Utterance))).scalars().first()
            for tag, count in {"pain": 60, "obstacle": 3, "emotion_pos": 15}.items():
                existing = (await db.execute(select(Highlight).where(Highlight.tag_key == tag))).scalars().all()
                for i in range(max(0, count - len(existing))):
                    db.add(Highlight(conversation_id=c.id, utterance_id=u.id, tag_key=tag, quote=f"{tag} new quote {i} plenty of words here",
                                     status="suggested", origin="ai", confidence=0.9))
            await db.commit()

        body = (await auth_client.get("/api/taxonomy/compare")).json()
        rows = {r["key"]: r for r in body["rows"]}
        assert body["snapshot"]["label"] == "before pilot"
        assert rows["pain"]["before"] == 20 and rows["pain"]["after"] == 60 and rows["pain"]["flag"] == "jumped"
        assert rows["workaround"]["after"] == 0 and rows["workaround"]["flag"] == "vanished"
        assert rows["money"]["flag"] == "vanished"
        assert rows["obstacle"]["before"] == 8 and rows["obstacle"]["after"] == 3 and rows["obstacle"]["flag"] is None   # a drop under 10 isn't alarming
        assert rows["emotion_pos"]["before"] == 0 and rows["emotion_pos"]["flag"] == "new"
        assert body["flagged"] == 4   # pain, workaround, money, emotion_pos
        order = [r["key"] for r in body["rows"]]
        assert order.index("workaround") < order.index("obstacle")   # flagged rows first

    @pytest.mark.asyncio
    async def test_counts_use_the_same_floor_as_insights(self, auth_client: AsyncClient, session_factory, seeded):
        await self._counts(session_factory, {"pain": 5}, conf=0.2)    # all below pain's 0.5 floor
        snap = (await auth_client.post("/api/taxonomy/snapshot", json={"label": "x"})).json()
        assert snap["counts"].get("pain", 0) == 0

    @pytest.mark.asyncio
    async def test_a_new_snapshot_replaces_the_old_one(self, auth_client: AsyncClient, session_factory, seeded):
        await self._counts(session_factory, {"pain": 4})
        await auth_client.post("/api/taxonomy/snapshot", json={"label": "first"})
        await auth_client.post("/api/taxonomy/snapshot", json={"label": "second"})
        assert (await auth_client.get("/api/taxonomy/compare")).json()["snapshot"]["label"] == "second"

    @pytest.mark.asyncio
    async def test_snapshot_is_admin_only_and_label_is_bounded(self, auth_client: AsyncClient, member_client: AsyncClient, seeded):
        assert (await member_client.post("/api/taxonomy/snapshot", json={"label": "x"})).status_code == 403
        assert (await auth_client.post("/api/taxonomy/snapshot", json={"label": "x" * 101})).status_code == 422
        assert (await member_client.get("/api/taxonomy/compare")).status_code == 200   # reading is fine
