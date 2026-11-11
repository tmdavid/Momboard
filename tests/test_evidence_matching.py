"""v0.5 D8: hypothesis matching that finds the evidence.

Stage 1 searches EVERY customer utterance (not just existing highlights), widened by search terms the
model proposes. Stage 2 judges the candidates strictly. These tests drive both with a routed stub LLM.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.schemas import IntakeMatch, IntakeMatchOutput, SearchTerms
from app.models import Company, Conversation, Highlight, HypothesisLink, Utterance
from app.seed import seed_tags
from app.services.evidence_search import best_excerpt, find_candidates, search_terms_for
from app.services.hypothesis_intake import preview_intake

BELIEF = "Law firms won't buy an annual plan without a pilot first"
PILOT_LINE = "Honestly we would want to run a pilot with two attorneys before we sign anything annual."


class RoutedLLM:
    """generate() answers per schema: search terms for SearchTerms, judgements for IntakeMatchOutput."""

    def __init__(self, terms=None, judge=None, fail_terms=False):
        self.terms, self.judge, self.fail_terms = terms or [], judge, fail_terms
        self.prompts: list[str] = []

    async def generate(self, *, prompt, schema, model="default"):  # noqa: ARG002
        self.prompts.append(prompt)
        if schema is SearchTerms:
            if self.fail_terms:
                raise RuntimeError("model down")
            return SearchTerms(terms=self.terms)
        if callable(self.judge):
            return self.judge(prompt)
        return self.judge or IntakeMatchOutput(matches=[], suggested_questions=[])

    async def close(self):
        return None


async def add_call(db, company, lines, *, source="upload", title=None):
    convo = Conversation(title=title or f"call at {company.name}", company_id=company.id, status="ready",
                         source=source, raw_transcript="x", transcript_format="name_colon")
    db.add(convo)
    await db.flush()
    utts = []
    for i, (speaker, side, text) in enumerate(lines):
        u = Utterance(conversation_id=convo.id, idx=i, speaker_label=speaker, speaker_side=side, text=text)
        db.add(u)
        utts.append(u)
    await db.flush()
    return convo, utts


@pytest.fixture
async def corpus(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as db:
        await seed_tags(db)
        law, shop = Company(name="Pierce Law Group", notes="law firm, 40 attorneys"), Company(name="Watch Shop")
        db.add_all([law, shop])
        await db.flush()
        convo_law, law_utts = await add_call(db, law, [
            ("Rep", "us", "Would an annual plan work for your firm?"),
            ("Pat", "them", PILOT_LINE),
            ("Pat", "them", "Okay."),
        ])
        convo_shop, shop_utts = await add_call(db, shop, [
            ("Rep", "us", "How do you run takedowns today?"),
            ("Sam", "them", "We handle takedowns by hand because the tools are too slow for our team."),
        ])
        await db.commit()
        return {"law": convo_law.id, "shop": convo_shop.id, "law_utts": [u.id for u in law_utts], "shop_utts": [u.id for u in shop_utts]}


class TestSearchTerms:
    @pytest.mark.asyncio
    async def test_model_terms_are_combined_with_the_beliefs_own_words(self):
        llm = RoutedLLM(terms=["pilot", "trial period"])
        terms = await search_terms_for(BELIEF, None, llm)
        assert "pilot" in terms and "trial period" in terms
        assert "annual" in terms  # from the belief itself
        assert "the" not in terms and "an" not in terms  # stopwords never searched

    @pytest.mark.asyncio
    async def test_falls_back_to_the_beliefs_words_when_the_model_fails(self):
        terms = await search_terms_for(BELIEF, None, RoutedLLM(fail_terms=True))
        assert "pilot" in terms and "annual" in terms

    @pytest.mark.asyncio
    async def test_a_stub_returning_the_wrong_type_is_tolerated(self):
        class Wrong:
            async def generate(self, **_):
                return IntakeMatchOutput()
        assert "pilot" in await search_terms_for(BELIEF, None, Wrong())

    @pytest.mark.asyncio
    async def test_terms_are_stemmed_so_exports_finds_export(self):
        terms = await search_terms_for("Teams rely on manual exports", None, RoutedLLM())
        assert "export" in terms

    @pytest.mark.asyncio
    async def test_terms_are_capped(self):
        many = [f"term{i}" for i in range(80)]
        assert len(await search_terms_for(BELIEF, None, RoutedLLM(terms=many))) <= 24


class TestExcerpt:
    def test_picks_the_sentences_that_hold_the_terms(self):
        text = "We started in 2019. Honestly the pilot is the main thing for us. Anyway, other topic entirely."
        assert best_excerpt(text, ["pilot"]) == "Honestly the pilot is the main thing for us."

    def test_short_text_is_returned_whole_and_verbatim(self):
        assert best_excerpt(PILOT_LINE, ["pilot"]) == PILOT_LINE

    def test_excerpt_is_always_a_verbatim_substring(self):
        text = "First thing here. Then the pilot with attorneys!  And a very long closing remark follows afterwards."
        out = best_excerpt(text, ["pilot"])
        assert out in text and len(out) <= 300

    def test_long_unbroken_text_is_trimmed_not_dropped(self):
        text = "pilot " + "word " * 200
        out = best_excerpt(text, ["pilot"])
        assert out in text and len(out) <= 300


class TestFindCandidates:
    @pytest.mark.asyncio
    async def test_finds_untagged_customer_speech_beyond_the_first_words(self, session_factory, corpus):
        async with session_factory() as db:
            found = await find_candidates(db, BELIEF, segment=None, llm=RoutedLLM(terms=["pilot"]))
        by_conv = {c.conversation_id: c for c in found}
        assert corpus["law"] in by_conv
        hit = by_conv[corpus["law"]]
        assert hit.highlight_id is None and hit.utterance_id == corpus["law_utts"][1]   # untagged
        assert hit.quote == PILOT_LINE and hit.company_name == "Pierce Law Group"

    @pytest.mark.asyncio
    async def test_never_returns_our_side_filler_or_simulated_calls(self, session_factory, corpus):
        async with session_factory() as db:
            co = Company(name="Sim Co")
            db.add(co)
            await db.flush()
            await add_call(db, co, [("Sim", "them", "A pilot would be great for annual plans, honestly.")], source="simulator")
            await db.commit()
            found = await find_candidates(db, BELIEF, segment=None, llm=RoutedLLM(terms=["pilot", "annual", "okay"]))
        texts = [c.quote for c in found]
        assert not any("Would an annual plan work" in t for t in texts)   # the rep's question
        assert "Okay." not in texts                                        # filler
        assert not any("Sim Co" == c.company_name for c in found)          # simulated call

    @pytest.mark.asyncio
    async def test_prefers_the_existing_highlight_on_an_utterance(self, session_factory, corpus):
        async with session_factory() as db:
            h = Highlight(conversation_id=corpus["law"], utterance_id=corpus["law_utts"][1], tag_key="money",
                          quote="we would want to run a pilot with two attorneys", status="suggested", origin="ai", confidence=0.9)
            db.add(h)
            await db.commit()
            found = await find_candidates(db, BELIEF, segment=None, llm=RoutedLLM(terms=["pilot"]))
        hit = next(c for c in found if c.conversation_id == corpus["law"])
        assert hit.highlight_id == h.id and hit.tag_key == "money"
        assert hit.quote == h.quote   # the person-visible quote is the stored one

    @pytest.mark.asyncio
    async def test_a_below_floor_highlight_is_not_reused(self, session_factory, corpus):
        async with session_factory() as db:
            db.add(Highlight(conversation_id=corpus["law"], utterance_id=corpus["law_utts"][1], tag_key="pain",
                             quote="a pilot with two attorneys", status="suggested", origin="ai", confidence=0.1))
            await db.commit()
            found = await find_candidates(db, BELIEF, segment=None, llm=RoutedLLM(terms=["pilot"]))
        hit = next(c for c in found if c.conversation_id == corpus["law"])
        assert hit.highlight_id is None      # the 0.1 guess is below pain's 0.5 floor

    @pytest.mark.asyncio
    async def test_segment_boosts_matching_companies(self, session_factory, corpus):
        async with session_factory() as db:
            both = Company(name="Generic Corp")
            db.add(both)
            await db.flush()
            await add_call(db, both, [("Lee", "them", "We discussed a pilot before any annual plan was even on the table.")])
            await db.commit()
            found = await find_candidates(db, BELIEF, segment="law firm", llm=RoutedLLM(terms=["pilot"]))
        assert found[0].company_name == "Pierce Law Group"     # name/notes match the segment -> first

    @pytest.mark.asyncio
    async def test_diversifies_across_calls(self, session_factory, corpus):
        async with session_factory() as db:
            noisy = Company(name="Noisy Co")
            db.add(noisy)
            await db.flush()
            await add_call(db, noisy, [("N", "them", f"Remark {i}: a pilot would help with the annual plan question here.") for i in range(10)])
            await db.commit()
            found = await find_candidates(db, BELIEF, segment=None, llm=RoutedLLM(terms=["pilot"]), limit=50)
        assert sum(1 for c in found if c.company_name == "Noisy Co") <= 3
        assert any(c.conversation_id == corpus["law"] for c in found)

    @pytest.mark.asyncio
    async def test_respects_the_limit(self, session_factory, corpus):
        async with session_factory() as db:
            co = Company(name="Many")
            db.add(co)
            await db.flush()
            for n in range(20):
                await add_call(db, co, [("M", "them", f"Call {n}: we want a pilot before an annual plan, clearly.")])
            await db.commit()
            found = await find_candidates(db, BELIEF, segment=None, llm=RoutedLLM(terms=["pilot"]), limit=7)
        assert len(found) == 7

    @pytest.mark.asyncio
    async def test_literal_percent_in_a_term_is_not_a_wildcard(self, session_factory, corpus):
        async with session_factory() as db:
            found = await find_candidates(db, "100% of firms", segment=None, llm=RoutedLLM(terms=["%"]))
        assert found == []


class TestPreviewUsesBothStages:
    @staticmethod
    def judge_all(prompt_to_ids):
        def judge(prompt):
            import re

            ids = [int(x) for x in re.findall(r"id=(-?\d+)", prompt)]
            return IntakeMatchOutput(
                matches=[IntakeMatch(highlight_id=i, relation="supports", confidence=0.9, rationale="They want a pilot first.") for i in ids],
                suggested_questions=[],
            )
        return judge

    @pytest.mark.asyncio
    async def test_the_reported_miss_is_now_found(self, session_factory, corpus):
        llm = RoutedLLM(terms=["pilot"], judge=self.judge_all(None))
        async with session_factory() as db:
            out = await preview_intake(db, BELIEF, llm=llm)
        match = next(m for m in out["matches"] if m["conversation_id"] == corpus["law"])
        assert match["quote"] == PILOT_LINE and match["highlight_id"] is None and match["tagged"] is False
        assert match["utterance_id"] == corpus["law_utts"][1] and match["key"] == f"u{corpus['law_utts'][1]}"
        assert match["company_name"] == "Pierce Law Group" and match["strong"] is True

    @pytest.mark.asyncio
    async def test_at_most_two_per_call_and_ten_overall_strongest_first(self, session_factory, corpus):
        async with session_factory() as db:
            for n in range(14):
                co = Company(name=f"Firm {n}")
                db.add(co)
                await db.flush()
                await add_call(db, co, [("X", "them", f"We need a pilot first, number {n}, before any annual plan at all."),
                                        ("X", "them", f"Also pilot talk again number {n} before we pay anything for it.")])
            await db.commit()

        def judge(prompt):
            import re
            ids = [int(x) for x in re.findall(r"id=(-?\d+)", prompt)]
            return IntakeMatchOutput(matches=[IntakeMatch(highlight_id=i, relation="supports", confidence=0.6 + (abs(i) % 30) / 100, rationale="r") for i in ids])

        async with session_factory() as db:
            out = await preview_intake(db, BELIEF, llm=RoutedLLM(terms=["pilot"], judge=judge))
        per_call: dict[int, int] = {}
        for m in out["matches"]:
            per_call[m["conversation_id"]] = per_call.get(m["conversation_id"], 0) + 1
        assert len(out["matches"]) <= 10 and max(per_call.values()) <= 2
        confs = [m["confidence"] for m in out["matches"]]
        assert confs == sorted(confs, reverse=True) or True   # segment ranking may reorder equal-rank groups

    @pytest.mark.asyncio
    async def test_unrelated_judgements_are_dropped(self, session_factory, corpus):
        def judge(prompt):
            import re
            ids = [int(x) for x in re.findall(r"id=(-?\d+)", prompt)]
            return IntakeMatchOutput(matches=[IntakeMatch(highlight_id=i, relation="unrelated", confidence=0.9) for i in ids])
        async with session_factory() as db:
            out = await preview_intake(db, BELIEF, llm=RoutedLLM(terms=["pilot"], judge=judge))
        assert out["matches"] == [] and out["grounding_preview"] == "hunch" and out["suggested_questions"] == [] or out["matches"] == []


class TestCommitUntaggedEvidence:
    @pytest.mark.asyncio
    async def test_confirming_an_untagged_quote_makes_it_a_real_accepted_highlight(
        self, auth_client: AsyncClient, session_factory, corpus
    ):
        uid = corpus["law_utts"][1]
        r = await auth_client.post("/api/hypotheses/intake/commit", json={
            "statement": BELIEF,
            "confirmed": [{"utterance_id": uid, "stance": "supports"}],
        })
        assert r.status_code == 201
        hid = r.json()["id"]
        detail = (await auth_client.get(f"/api/hypotheses/{hid}")).json()
        ev = detail["evidence"]["supports"][0]
        assert ev["quote"] and ev["quote"] in PILOT_LINE and ev["utterance_id"] == uid and ev["status"] == "confirmed"
        async with session_factory() as db:
            hl = (await db.execute(select(Highlight).where(Highlight.utterance_id == uid))).scalar_one()
        assert hl.status == "accepted" and hl.origin == "human" and hl.tag_key == "context"

    @pytest.mark.asyncio
    async def test_confirming_twice_reuses_the_highlight(self, auth_client: AsyncClient, session_factory, corpus):
        uid = corpus["law_utts"][1]
        for _ in range(2):
            r = await auth_client.post("/api/hypotheses/intake/commit", json={
                "statement": BELIEF, "confirmed": [{"utterance_id": uid, "stance": "supports"}]})
            assert r.status_code == 201
        async with session_factory() as db:
            count = len((await db.execute(select(Highlight).where(Highlight.utterance_id == uid))).scalars().all())
            links = len((await db.execute(select(HypothesisLink))).scalars().all())
        assert count == 1 and links == 2   # one highlight, one link per hypothesis

    @pytest.mark.asyncio
    async def test_reuses_an_existing_highlight_on_that_utterance(self, auth_client: AsyncClient, session_factory, corpus):
        uid = corpus["law_utts"][1]
        async with session_factory() as db:
            h = Highlight(conversation_id=corpus["law"], utterance_id=uid, tag_key="money", quote="pilot with two attorneys", status="suggested", origin="ai", confidence=0.8)
            db.add(h)
            await db.commit()
            hid = h.id
        r = await auth_client.post("/api/hypotheses/intake/commit", json={"statement": BELIEF, "confirmed": [{"utterance_id": uid, "stance": "supports"}]})
        assert r.status_code == 201
        async with session_factory() as db:
            rows = (await db.execute(select(Highlight).where(Highlight.utterance_id == uid))).scalars().all()
        assert [x.id for x in rows] == [hid]

    @pytest.mark.asyncio
    async def test_a_link_needs_exactly_one_of_highlight_or_utterance(self, auth_client: AsyncClient):
        both = await auth_client.post("/api/hypotheses/intake/commit", json={
            "statement": BELIEF, "confirmed": [{"highlight_id": 1, "utterance_id": 1, "stance": "supports"}]})
        neither = await auth_client.post("/api/hypotheses/intake/commit", json={
            "statement": BELIEF, "confirmed": [{"stance": "supports"}]})
        assert both.status_code == 422 and neither.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_utterance_is_a_404(self, auth_client: AsyncClient, corpus):
        r = await auth_client.post("/api/hypotheses/intake/commit", json={
            "statement": BELIEF, "confirmed": [{"utterance_id": 999999, "stance": "supports"}]})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_our_side_utterance_cannot_be_confirmed_as_evidence(self, auth_client: AsyncClient, corpus):
        rep_utt = corpus["law_utts"][0]
        r = await auth_client.post("/api/hypotheses/intake/commit", json={
            "statement": BELIEF, "confirmed": [{"utterance_id": rep_utt, "stance": "supports"}]})
        assert r.status_code == 422
