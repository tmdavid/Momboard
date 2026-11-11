"""Filters the MCP tools need, added to the shared REST handlers so every surface agrees on them."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Analysis, Company, Conversation, Highlight, Utterance


async def call(db, name, company, score, *, source="upload"):
    co = None
    if company:
        co = (await db.execute(select(Company).where(Company.name == company))).scalar_one_or_none()
        if co is None:
            co = Company(name=company)
            db.add(co)
            await db.flush()
    c = Conversation(title=name, company_id=co.id if co else None, status="ready", source=source,
                     happened_at=datetime(2026, 11, 1, tzinfo=UTC), raw_transcript="x", transcript_format="name_colon")
    db.add(c)
    await db.flush()
    if score is not None:
        db.add(Analysis(conversation_id=c.id, kind="conversation",
                        result={"summary": "s", "mom_test_critique": {"score": score, "good_questions": [], "violations": []}}))
    await db.flush()
    return c


@pytest_asyncio.fixture
async def corpus(session_factory):
    async with session_factory() as db:
        a = await call(db, "Acme discovery", "Acme Legal LLP", 8)
        b = await call(db, "Beta intro", "Beta Watches", 3)
        c = await call(db, "Gamma", "acme partners", None)         # unscored, name also contains "acme"
        sim = await call(db, "Simulated Acme", "Acme Legal LLP", 9, source="simulator")
        await db.commit()
        return {"a": a.id, "b": b.id, "c": c.id, "sim": sim.id}


def ids(r):
    return {i["id"] for i in r.json()["items"]}


class TestConversationFilters:
    @pytest.mark.asyncio
    async def test_company_name_is_a_case_insensitive_substring(self, auth_client, corpus):
        r = await auth_client.get("/api/conversations", params={"company": "ACME"})
        assert ids(r) == {corpus["a"], corpus["c"]}                 # and never the simulated one
        assert r.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_company_wildcards_are_literal(self, auth_client, corpus):
        assert ids(await auth_client.get("/api/conversations", params={"company": "%"})) == set()
        assert ids(await auth_client.get("/api/conversations", params={"company": "_cme"})) == set()

    @pytest.mark.asyncio
    async def test_score_range_keeps_totals_correct(self, auth_client, corpus):
        r = await auth_client.get("/api/conversations", params={"min_score": 5})
        assert ids(r) == {corpus["a"]} and r.json()["total"] == 1
        r = await auth_client.get("/api/conversations", params={"max_score": 5})
        assert ids(r) == {corpus["b"]}                              # unscored calls match neither bound
        r = await auth_client.get("/api/conversations", params={"min_score": 3, "max_score": 8})
        assert ids(r) == {corpus["a"], corpus["b"]}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [{"min_score": -1}, {"min_score": 11}, {"max_score": 99}])
    async def test_score_bounds_are_validated(self, auth_client, bad):
        assert (await auth_client.get("/api/conversations", params=bad)).status_code == 422

    @pytest.mark.asyncio
    async def test_without_the_new_filters_nothing_changes(self, auth_client, corpus):
        r = await auth_client.get("/api/conversations")
        assert ids(r) == {corpus["a"], corpus["b"], corpus["c"]} and r.json()["total"] == 3


@pytest_asyncio.fixture
async def quotes(session_factory):
    async with session_factory() as db:
        c = await call(db, "Quotes", "Acme Legal LLP", 7)
        other = await call(db, "Other", "Beta Watches", 7)
        def utt(i, side):
            u = Utterance(conversation_id=c.id, idx=i, speaker_label="x", speaker_side=side, text=f"line {i}")
            db.add(u)
            return u
        customer, rep = utt(0, "them"), utt(1, "us")
        await db.flush()
        def hl(conv, uid, tag, conf, status="suggested", quote="q"):
            h = Highlight(conversation_id=conv.id, utterance_id=uid, tag_key=tag, quote=quote, status=status,
                          origin="ai", confidence=conf)
            db.add(h)
            return h
        rows = {
            "cust_hi": hl(c, customer.id, "pain", 0.95, quote="cust hi"),
            "cust_lo": hl(c, customer.id, "pain", 0.55, quote="cust lo"),
            "rep_pain": hl(c, rep.id, "pain", 0.9, quote="rep pain"),            # legacy: tagged on our side
            "rep_follow": hl(c, rep.id, "followup", 0.9, quote="rep follow"),     # allowed on either side
            "manual": hl(c, None, "pain", None, status="accepted", quote="manual"),
            "beta": hl(other, None, "pain", 0.9, quote="beta"),
        }
        await db.commit()
        return {k: v.id for k, v in rows.items()}


def quote_names(r, quotes):
    inv = {v: k for k, v in quotes.items()}
    return {inv[i["id"]] for i in r.json()["items"]}


class TestHighlightFilters:
    @pytest.mark.asyncio
    async def test_min_confidence(self, auth_client, quotes):
        r = await auth_client.get("/api/highlights", params={"min_confidence": 0.9})
        # manual / accepted highlights have no confidence and always pass, like the per-tag floor
        assert quote_names(r, quotes) == {"cust_hi", "rep_pain", "rep_follow", "manual", "beta"}
        assert r.json()["total"] == 5

    @pytest.mark.asyncio
    async def test_customer_only_drops_our_side_except_followup_and_commitment(self, auth_client, quotes):
        r = await auth_client.get("/api/highlights", params={"customer_only": True})
        assert quote_names(r, quotes) == {"cust_hi", "cust_lo", "rep_follow", "manual", "beta"}
        assert r.json()["total"] == 5

    @pytest.mark.asyncio
    async def test_company_name_filter(self, auth_client, quotes):
        r = await auth_client.get("/api/highlights", params={"company": "acme"})
        assert quote_names(r, quotes) == {"cust_hi", "cust_lo", "rep_pain", "rep_follow", "manual"}
        assert quote_names(await auth_client.get("/api/highlights", params={"company": "beta"}), quotes) == {"beta"}

    @pytest.mark.asyncio
    async def test_filters_combine_and_page_correctly(self, auth_client, quotes):
        params = {"company": "acme", "customer_only": True, "min_confidence": 0.5, "floor": True, "sort": "confidence", "limit": 1}
        r = await auth_client.get("/api/highlights", params=params)
        # acme + customer-only drops rep_pain; strongest first: cust_hi .95, rep_follow .9, cust_lo .55, manual (none)
        assert r.json()["total"] == 4 and quote_names(r, quotes) == {"cust_hi"}
        for offset, expected in [(1, "rep_follow"), (2, "cust_lo"), (3, "manual")]:
            r2 = await auth_client.get("/api/highlights", params={**params, "offset": offset})
            assert quote_names(r2, quotes) == {expected}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [{"min_confidence": -0.1}, {"min_confidence": 1.5}])
    async def test_confidence_bounds_are_validated(self, auth_client, bad):
        assert (await auth_client.get("/api/highlights", params=bad)).status_code == 422

    @pytest.mark.asyncio
    async def test_defaults_are_unchanged(self, auth_client, quotes):
        r = await auth_client.get("/api/highlights")
        assert r.json()["total"] == 6


class TestStatsSince:
    @pytest.mark.asyncio
    async def test_since_limits_everything_to_calls_on_or_after_that_date(self, auth_client, session_factory):
        async with session_factory() as db:
            old = await call(db, "Old", "Old Co", 2)
            old.happened_at = datetime(2026, 1, 5, tzinfo=UTC)
            new = await call(db, "New", "New Co", 8)
            new.happened_at = datetime(2026, 11, 1, tzinfo=UTC)
            for c in (old, new):
                db.add(Highlight(conversation_id=c.id, tag_key="pain", quote="q", status="accepted", origin="ai", confidence=0.9))
            await db.commit()
        everything = (await auth_client.get("/api/stats")).json()
        assert everything["total_conversations"] == 2 and everything["avg_critique_score"] == 5.0
        assert sum(m.get("pain", 0) for m in everything["tag_counts_by_month"].values()) == 2

        recent = (await auth_client.get("/api/stats", params={"since": "2026-06-01T00:00:00Z"})).json()
        assert recent["total_conversations"] == 1 and recent["avg_critique_score"] == 8.0
        assert sum(m.get("pain", 0) for m in recent["tag_counts_by_month"].values()) == 1

    @pytest.mark.asyncio
    async def test_a_date_in_the_future_is_empty_not_an_error(self, auth_client, corpus):
        r = (await auth_client.get("/api/stats", params={"since": "2099-01-01T00:00:00Z"})).json()
        assert r["total_conversations"] == 0 and r["avg_critique_score"] is None and r["tag_counts_by_month"] == {}


class TestStatsCustomerOnly:
    @pytest.mark.asyncio
    async def test_our_side_highlights_can_be_left_out_of_the_counts(self, auth_client, quotes):
        everything = (await auth_client.get("/api/stats")).json()["tag_counts_by_month"]
        customer = (await auth_client.get("/api/stats", params={"customer_only": True})).json()["tag_counts_by_month"]
        total = lambda d, tag: sum(m.get(tag, 0) for m in d.values())     # noqa: E731
        assert total(everything, "pain") == total(customer, "pain") + 1   # the legacy rep-tagged pain
        assert total(everything, "followup") == total(customer, "followup") == 1      # either side is allowed
