"""v0.5 D1-D3 through the real tagging pipeline (stubbed LLM): sides, filler, one tag per quote,
and what a retag must leave alone."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.client import FakeLLMClient
from app.llm.seller import SellerProfile, set_seller_profile
from app.llm.tagging import run_tag
from app.models import Company, Conversation, Highlight, Tag, Utterance
from app.seed import seed_tags

REP_LINE = "You said you have got seven thousand clients across the whole region"
PAIN = "Every Monday I export the report to Excel and clean it by hand"
REPUTATION = "We need to protect our reputation with every one of our customers"


async def make_call(
    session_factory: async_sessionmaker[AsyncSession],
    lines: list[tuple[str, str, str]],
    *,
    meta: dict | None = None,
    interviewer: str = "David",
) -> int:
    async with session_factory() as db:
        await seed_tags(db)
        db.add(Tag(key="outcome", emoji="🎯", name="Outcome", description="Desired result", origin="custom", category="outcome", is_active=True, sort_order=50))
        company = Company(name="Client Co")
        db.add(company)
        await db.flush()
        convo = Conversation(
            title="Call", company_id=company.id, interviewer=interviewer, status="processing",
            raw_transcript="x", transcript_format="name_colon", meta=meta,
        )
        db.add(convo)
        await db.flush()
        for i, (speaker, side, text) in enumerate(lines):
            db.add(Utterance(conversation_id=convo.id, idx=i, speaker_label=speaker, speaker_side=side, text=text))
        await db.commit()
        return convo.id


def llm_with(*highlights: dict) -> FakeLLMClient:
    fake = FakeLLMClient()
    fake.set_fixture("tagger", {"highlights": list(highlights)})
    return fake


def hl(idx: int, tag: str, quote: str, conf: float = 0.9) -> dict:
    return {"utterance_idx": idx, "tag_key": tag, "quote": quote, "confidence": conf, "rationale": "r"}


async def stored(session_factory, convo_id: int) -> list[Highlight]:
    async with session_factory() as db:
        rows = await db.execute(select(Highlight).where(Highlight.conversation_id == convo_id).order_by(Highlight.id))
        return list(rows.scalars().all())


BASIC = [("David", "us", REP_LINE), ("Maria", "them", PAIN), ("Maria", "them", REPUTATION)]


@pytest.mark.asyncio
async def test_evidence_tags_are_never_stored_on_our_side(session_factory):
    cid = await make_call(session_factory, BASIC)
    fake = llm_with(hl(0, "pain", REP_LINE), hl(1, "pain", PAIN))
    async with session_factory() as db:
        await run_tag(db, cid, fake)
        await db.commit()
    rows = await stored(session_factory, cid)
    assert [r.quote for r in rows] == [PAIN]


@pytest.mark.asyncio
async def test_followup_and_commitment_are_allowed_on_our_side(session_factory):
    lines = [("David", "us", "I will send the pricing deck to Maria by Friday afternoon"), ("Maria", "them", PAIN)]
    cid = await make_call(session_factory, lines)
    fake = llm_with(hl(0, "followup", lines[0][2]), hl(0, "pain", lines[0][2], 0.9))
    async with session_factory() as db:
        await run_tag(db, cid, fake)
        await db.commit()
    assert [(r.tag_key) for r in await stored(session_factory, cid)] == ["followup"]


@pytest.mark.asyncio
async def test_filler_is_not_stored_but_a_concrete_commitment_is(session_factory):
    lines = [("David", "us", "Shall we book a follow up?"), ("Maria", "them", "Yes."), ("Maria", "them", "Yes, 2 p.m. Thursday works"), ("Maria", "them", "We will discuss this.")]
    cid = await make_call(session_factory, lines)
    fake = llm_with(
        hl(1, "commitment", "Yes.", 0.7),
        hl(2, "commitment", "Yes, 2 p.m. Thursday works", 0.9),
        hl(3, "objection", "We will discuss this.", 0.6),
    )
    async with session_factory() as db:
        db.add(Tag(key="objection", emoji="✋", name="Objection", origin="custom", category="sales", is_active=True, sort_order=60))
        await db.commit()
    async with session_factory() as db:
        await run_tag(db, cid, fake)
        await db.commit()
    assert [r.quote for r in await stored(session_factory, cid)] == ["Yes, 2 p.m. Thursday works"]


@pytest.mark.asyncio
async def test_one_tag_per_quote_unless_a_strong_one_from_another_category(session_factory):
    cid = await make_call(session_factory, BASIC)
    fake = llm_with(
        hl(2, "pain", REPUTATION, 0.9),
        hl(2, "money", REPUTATION, 0.85),     # same (core) category -> dropped
        hl(2, "outcome", REPUTATION, 0.8),    # different category, both >= 0.7 -> kept
    )
    async with session_factory() as db:
        await run_tag(db, cid, fake)
        await db.commit()
    assert sorted(r.tag_key for r in await stored(session_factory, cid)) == ["outcome", "pain"]


@pytest.mark.asyncio
async def test_no_duplicate_text_per_call(session_factory):
    cid = await make_call(session_factory, [("Maria", "them", PAIN), ("Maria", "them", PAIN)])
    fake = llm_with(hl(0, "pain", PAIN, 0.8), hl(1, "pain", PAIN, 0.9))
    async with session_factory() as db:
        await run_tag(db, cid, fake)
        await db.commit()
    assert len(await stored(session_factory, cid)) == 1


@pytest.mark.asyncio
async def test_retag_does_not_duplicate_a_highlight_a_person_already_accepted(session_factory):
    cid = await make_call(session_factory, BASIC)
    async with session_factory() as db:
        utt = (await db.execute(select(Utterance).where(Utterance.conversation_id == cid, Utterance.idx == 1))).scalar_one()
        db.add(Highlight(conversation_id=cid, utterance_id=utt.id, tag_key="pain", quote=PAIN, status="accepted", origin="human", confidence=1.0))
        await db.commit()
    fake = llm_with(hl(1, "pain", PAIN, 0.95))
    async with session_factory() as db:
        await run_tag(db, cid, fake)
        await db.commit()
    rows = await stored(session_factory, cid)
    assert len(rows) == 1 and rows[0].status == "accepted"


@pytest.mark.asyncio
async def test_unknown_side_is_given_the_benefit_of_the_doubt(session_factory):
    cid = await make_call(session_factory, [("Speaker 2", "unknown", PAIN)], interviewer="Nobody Here")
    fake = llm_with(hl(0, "pain", PAIN))
    async with session_factory() as db:
        await run_tag(db, cid, fake)
        await db.commit()
    assert len(await stored(session_factory, cid)) == 1


class TestSpeakerSidesAreRefreshedBeforeTagging:
    """Rep speech was becoming customer evidence because only ONE named interviewer counted as us."""

    @pytest.mark.asyncio
    async def test_second_rep_from_clari_internal_list_is_ours(self, session_factory):
        lines = [("David", "us", REP_LINE), ("Sam Colleague", "them", "We also offer an enterprise tier with extra features included")]
        cid = await make_call(session_factory, lines, meta={"clari_us_speakers": ["David", "Sam Colleague"]})
        fake = llm_with(hl(1, "pain", lines[1][2]))
        async with session_factory() as db:
            await run_tag(db, cid, fake)
            await db.commit()
        assert await stored(session_factory, cid) == []
        async with session_factory() as db:
            sides = {u.speaker_label: u.speaker_side for u in (await db.execute(select(Utterance).where(Utterance.conversation_id == cid))).scalars()}
        assert sides["Sam Colleague"] == "us"

    @pytest.mark.asyncio
    async def test_company_name_in_the_label_marks_a_speaker_as_ours(self, session_factory):
        set_seller_profile(SellerProfile(name="Acme Corp", aliases=["Acme"]))
        lines = [("Jordan (Acme Corp)", "them", "Our platform removes the manual export step for you"), ("Maria", "them", PAIN)]
        cid = await make_call(session_factory, lines, interviewer="Nobody")
        fake = llm_with(hl(0, "pain", lines[0][2]), hl(1, "pain", PAIN))
        async with session_factory() as db:
            await run_tag(db, cid, fake)
            await db.commit()
        assert [r.quote for r in await stored(session_factory, cid)] == [PAIN]

    @pytest.mark.asyncio
    async def test_email_domain_from_clari_marks_a_speaker_as_ours(self, session_factory):
        set_seller_profile(SellerProfile(name="Acme Corp", email_domains=["acme.io"]))
        lines = [("Riley", "them", "We see this with most customers in your industry sector"), ("Maria", "them", PAIN)]
        cid = await make_call(
            session_factory, lines, interviewer="Nobody",
            meta={"clari_speaker_emails": {"Riley": "riley@sales.acme.io", "Maria": "maria@clientco.com"}},
        )
        fake = llm_with(hl(0, "pain", lines[0][2]), hl(1, "pain", PAIN))
        async with session_factory() as db:
            await run_tag(db, cid, fake)
            await db.commit()
        assert [r.quote for r in await stored(session_factory, cid)] == [PAIN]

    @pytest.mark.asyncio
    async def test_never_demotes_a_speaker_already_marked_ours(self, session_factory):
        set_seller_profile(SellerProfile(name="Other Company"))
        lines = [("David", "us", REP_LINE), ("Maria", "them", PAIN)]
        cid = await make_call(session_factory, lines)
        async with session_factory() as db:
            await run_tag(db, cid, llm_with())
            await db.commit()
            sides = {u.speaker_label: u.speaker_side for u in (await db.execute(select(Utterance).where(Utterance.conversation_id == cid))).scalars()}
        assert sides == {"David": "us", "Maria": "them"}
