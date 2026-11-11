"""v0.5 D4: a per-tag confidence floor for what the UI shows, and a per-call cap in Explore."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Company, Conversation, Highlight, Tag
from app.seed import seed_tags

Q = "Every Monday I export the report to Excel and clean it by hand"


async def make_corpus(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Two companies, three calls, highlights above and below the floor."""
    async with session_factory() as db:
        await seed_tags(db)
        db.add(Tag(key="sample_tag", emoji="✋", name="Sample tag", origin="custom", category="sales",
                   is_active=True, sort_order=60, min_confidence=0.8))
        acme, globex = Company(name="Acme"), Company(name="Globex")
        db.add_all([acme, globex])
        await db.flush()
        calls = {}
        for name, company in (("a1", acme), ("a2", acme), ("g1", globex)):
            c = Conversation(title=name, company_id=company.id, status="ready", source="upload",
                             raw_transcript="x", transcript_format="name_colon")
            db.add(c)
            await db.flush()
            calls[name] = c.id

        def add(call, tag, conf, status="suggested", quote=None):
            db.add(Highlight(conversation_id=calls[call], tag_key=tag, confidence=conf, status=status,
                             origin="ai" if status == "suggested" else "human",
                             quote=quote or f"{call} {tag} {conf} quote text goes here for the call"))

        add("a1", "pain", 0.95)
        add("a1", "pain", 0.90)
        add("a1", "pain", 0.85)
        add("a1", "pain", 0.80)      # 4th pain in one call
        add("a1", "pain", 0.30)      # below the 0.5 floor
        add("a1", "sample_tag", 0.70)  # below sample_tag's own 0.8 floor
        add("a1", "sample_tag", 0.85)
        add("a2", "pain", 0.60)
        add("a2", "pain", 0.20, status="accepted")   # a person accepted it: always counts
        add("g1", "workaround", 0.75)
        add("g1", "pain", 0.45)      # below the floor
        await db.commit()
        return calls


def ids_of(items):
    return [i["id"] for i in items]


@pytest.mark.asyncio
async def test_explore_is_unchanged_by_default(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    body = (await auth_client.get("/api/highlights", params={"limit": 200})).json()
    assert body["total"] == 11  # no floor, no cap unless asked


@pytest.mark.asyncio
async def test_floor_hides_low_suggestions_but_keeps_accepted(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    body = (await auth_client.get("/api/highlights", params={"floor": "true", "limit": 200})).json()
    kept = {(i["conversation_title"], i["tag_key"], i["confidence"], i["status"]) for i in body["items"]}
    assert ("a1", "pain", 0.3, "suggested") not in kept
    assert ("g1", "pain", 0.45, "suggested") not in kept
    assert ("a1", "sample_tag", 0.7, "suggested") not in kept      # custom tag has its own floor (0.8)
    assert ("a1", "sample_tag", 0.85, "suggested") in kept
    assert ("a2", "pain", 0.2, "accepted") in kept                # human decision beats the floor
    assert body["total"] == 8


@pytest.mark.asyncio
async def test_sort_by_confidence_puts_the_strongest_first(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    items = (await auth_client.get("/api/highlights", params={"sort": "confidence", "limit": 200})).json()["items"]
    confs = [i["confidence"] for i in items]
    assert confs == sorted(confs, reverse=True)


@pytest.mark.asyncio
async def test_per_call_cap_limits_each_call_and_tag(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    body = (await auth_client.get(
        "/api/highlights", params={"floor": "true", "per_call_cap": 3, "sort": "confidence", "limit": 200}
    )).json()
    pains_a1 = [i for i in body["items"] if i["conversation_title"] == "a1" and i["tag_key"] == "pain"]
    assert len(pains_a1) == 3                                   # 4 qualifying, capped at 3
    assert sorted(i["confidence"] for i in pains_a1) == [0.85, 0.9, 0.95]   # the strongest three
    assert body["total"] == 7                                    # 8 above floor, one capped away


@pytest.mark.asyncio
async def test_first_screen_spans_several_companies(auth_client: AsyncClient, session_factory):
    """The reported bug: the first 10 cards were all from one call."""
    await make_corpus(session_factory)
    items = (await auth_client.get(
        "/api/highlights", params={"floor": "true", "per_call_cap": 1, "sort": "confidence", "limit": 3}
    )).json()["items"]
    assert len({i["company_name"] for i in items}) >= 2


@pytest.mark.asyncio
async def test_cap_paginates_over_the_capped_set(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    p = {"floor": "true", "per_call_cap": 3, "sort": "confidence", "limit": 3}
    first = (await auth_client.get("/api/highlights", params={**p, "offset": 0})).json()
    second = (await auth_client.get("/api/highlights", params={**p, "offset": 3})).json()
    third = (await auth_client.get("/api/highlights", params={**p, "offset": 6})).json()
    all_ids = ids_of(first["items"]) + ids_of(second["items"]) + ids_of(third["items"])
    assert first["total"] == second["total"] == 7
    assert len(all_ids) == 7 and len(set(all_ids)) == 7


@pytest.mark.asyncio
async def test_library_signal_counts_respect_the_floor(auth_client: AsyncClient, session_factory):
    calls = await make_corpus(session_factory)
    items = (await auth_client.get("/api/conversations", params={"limit": 50})).json()["items"]
    by_title = {i["title"]: i for i in items}
    assert by_title["a1"]["tag_counts"] == {"pain": 4, "sample_tag": 1}   # 0.30 pain and 0.70 sample_tag excluded
    assert by_title["a2"]["tag_counts"] == {"pain": 2}                    # 0.60 plus the accepted 0.20
    assert "pain" not in by_title["g1"]["tag_counts"]                     # its only pain is 0.45
    assert calls["a1"] == by_title["a1"]["id"]


@pytest.mark.asyncio
async def test_tag_filter_ignores_calls_whose_only_match_is_below_the_floor(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    titles = {i["title"] for i in (await auth_client.get("/api/conversations", params={"tag": "pain"})).json()["items"]}
    assert titles == {"a1", "a2"}   # g1's pain is 0.45 -> not a "pain" call


@pytest.mark.asyncio
async def test_insights_stats_respect_the_floor(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    months = (await auth_client.get("/api/stats")).json()["tag_counts_by_month"]
    totals: dict[str, int] = {}
    for per_tag in months.values():
        for tag, n in per_tag.items():
            totals[tag] = totals.get(tag, 0) + n
    assert totals == {"pain": 6, "sample_tag": 1, "workaround": 1}   # 4+2 pains, not 8


@pytest.mark.asyncio
async def test_tag_floor_is_editable_and_validated(auth_client: AsyncClient, session_factory):
    await make_corpus(session_factory)
    r = await auth_client.patch("/api/tags/pain", json={"min_confidence": 0.9})
    assert r.status_code == 200 and r.json()["min_confidence"] == 0.9
    assert (await auth_client.patch("/api/tags/pain", json={"min_confidence": 1.5})).status_code == 422
    assert (await auth_client.patch("/api/tags/pain", json={"min_confidence": -0.1})).status_code == 422
    tags = (await auth_client.get("/api/tags")).json()
    assert next(t for t in tags if t["key"] == "pain")["min_confidence"] == 0.9
    assert next(t for t in tags if t["key"] == "sample_tag")["min_confidence"] == 0.8


@pytest.mark.asyncio
async def test_helper_treats_unknown_tag_and_null_confidence_as_passing(session_factory):
    from app.services.confidence_floor import passes_floor

    async with session_factory() as db:
        await seed_tags(db)
        c = Conversation(title="x", status="ready", raw_transcript="x", transcript_format="name_colon")
        db.add(c)
        await db.flush()
        db.add(Highlight(conversation_id=c.id, tag_key="pain", quote="no confidence recorded here at all", status="suggested", origin="ai", confidence=None))
        await db.commit()
        rows = (await db.execute(select(Highlight).where(passes_floor()))).scalars().all()
    assert len(rows) == 1
