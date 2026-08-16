"""T10/T11: Tagger agent + verbatim-quote validator + chunking tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.client import FakeLLMClient
from app.llm.tagging import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    chunk_utterances,
    dedupe_highlights,
    run_tag,
    validate_quote,
)
from app.models import Company, Conversation, Tag, Utterance
from app.seed import seed_tags

# --- Verbatim quote validation ---


def test_verbatim_validator_accepts_exact_substring():
    is_valid, _ = validate_quote(
        "export it to Excel", "Every Monday I export it to Excel and clean it by hand"
    )
    assert is_valid


def test_verbatim_validator_accepts_full_text():
    text = "We use a spreadsheet"
    is_valid, _ = validate_quote(text, text)
    assert is_valid


def test_verbatim_validator_fuzzy_matches_minor_whitespace():
    # Extra space in quote
    is_valid, _ = validate_quote(
        "export it  to Excel",
        "Every Monday I export it to Excel and clean it by hand",
    )
    assert is_valid


def test_verbatim_validator_fuzzy_matches_curly_quotes():
    is_valid, _ = validate_quote(
        "\u2018sounds great\u2019",
        "She said 'sounds great' and left",
    )
    assert is_valid


def test_verbatim_validator_drops_fabricated_quote():
    is_valid, _ = validate_quote(
        "This is completely made up text that doesn't exist",
        "The actual utterance is about spreadsheets and Monday exports",
    )
    assert not is_valid


def test_verbatim_validator_drops_very_different_quote():
    is_valid, _ = validate_quote(
        "AI-powered detection system with 99% accuracy",
        "We manually check listings every week",
    )
    assert not is_valid


# --- Chunking ---


def test_chunks_of_80_utterances_with_10_overlap():
    utterances = [
        {"idx": i, "text": f"utterance {i}", "speaker": "A", "side": "us"} for i in range(200)
    ]
    chunks = chunk_utterances(utterances, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    assert len(chunks) > 1
    # First chunk is CHUNK_SIZE
    assert len(chunks[0]) == CHUNK_SIZE
    # Overlap: last items of chunk[0] should appear at start of chunk[1]
    overlap_end = chunks[0][-CHUNK_OVERLAP:]
    overlap_start = chunks[1][:CHUNK_OVERLAP]
    assert overlap_end == overlap_start


def test_short_transcript_is_single_chunk():
    utterances = [{"idx": i, "text": f"u{i}", "speaker": "A", "side": "us"} for i in range(50)]
    chunks = chunk_utterances(utterances)
    assert len(chunks) == 1
    assert len(chunks[0]) == 50


def test_highlights_deduped_on_utterance_and_tag_across_chunks():
    from app.llm.schemas import TaggerHighlight

    highlights = [
        TaggerHighlight(
            utterance_idx=5, tag_key="pain", quote="test", confidence=0.8, rationale=""
        ),
        TaggerHighlight(
            utterance_idx=5, tag_key="pain", quote="test", confidence=0.9, rationale=""
        ),
        TaggerHighlight(
            utterance_idx=5, tag_key="workaround", quote="test", confidence=0.7, rationale=""
        ),
    ]
    deduped = dedupe_highlights(highlights)
    assert len(deduped) == 2  # one pain (higher confidence), one workaround
    pain_hl = next(h for h in deduped if h.tag_key == "pain")
    assert pain_hl.confidence == 0.9


# --- Integration: run_tag ---


@pytest.mark.asyncio
async def test_tagger_persists_suggested_highlights(
    session_factory: async_sessionmaker[AsyncSession],
):
    """run_tag should create highlights with status=suggested, origin=ai."""
    async with session_factory() as db:
        await seed_tags(db)
        company = Company(name="TestCo")
        db.add(company)
        await db.flush()

        convo = Conversation(
            title="Test",
            company_id=company.id,
            interviewer="David",
            status="processing",
            raw_transcript="",
            transcript_format="name_colon",
        )
        db.add(convo)
        await db.flush()

        # Add utterances matching the fixture
        for i, (speaker, side, text) in enumerate(
            [
                ("David", "us", "Hey Maria, thanks for taking the time today."),
                (
                    "Maria",
                    "them",
                    "right now we have this spreadsheet where the team logs every infringement they find manually",
                ),
                ("David", "us", "And when you find an infringement, what happens next?"),
                (
                    "Maria",
                    "them",
                    "Every Monday I export it to Excel and clean it by hand, takes about 2 hours",
                ),
            ]
        ):
            db.add(
                Utterance(
                    conversation_id=convo.id,
                    idx=i,
                    speaker_label=speaker,
                    speaker_side=side,
                    text=text,
                )
            )
        await db.flush()
        convo_id = convo.id

        # Set up fake LLM with matching fixture
        fake = FakeLLMClient()
        fake.set_fixture(
            "tagger",
            {
                "highlights": [
                    {
                        "utterance_idx": 1,
                        "tag_key": "context",
                        "quote": "right now we have this spreadsheet where the team logs every infringement they find manually",
                        "confidence": 0.85,
                        "rationale": "Background info",
                    },
                    {
                        "utterance_idx": 3,
                        "tag_key": "workaround",
                        "quote": "Every Monday I export it to Excel and clean it by hand, takes about 2 hours",
                        "confidence": 0.95,
                        "rationale": "Recurring past behavior",
                    },
                ],
            },
        )

        created = await run_tag(db, convo_id, fake)
        await db.commit()

        assert len(created) == 2
        assert all(h.origin == "ai" for h in created)
        assert all(h.status == "suggested" for h in created)
        assert {h.tag_key for h in created} == {"context", "workaround"}


@pytest.mark.asyncio
async def test_unknown_tag_key_from_llm_is_dropped(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Tags not in the DB should be silently dropped."""
    async with session_factory() as db:
        await seed_tags(db)
        convo = Conversation(title="Test", interviewer="David", status="processing")
        db.add(convo)
        await db.flush()
        db.add(
            Utterance(
                conversation_id=convo.id,
                idx=0,
                speaker_label="David",
                speaker_side="us",
                text="test utterance",
            )
        )
        await db.flush()
        convo_id = convo.id

        fake = FakeLLMClient()
        fake.set_fixture(
            "tagger",
            {
                "highlights": [
                    {
                        "utterance_idx": 0,
                        "tag_key": "nonexistent_tag_xyz",
                        "quote": "test utterance",
                        "confidence": 0.9,
                        "rationale": "test",
                    },
                ],
            },
        )

        created = await run_tag(db, convo_id, fake)
        await db.commit()
        assert len(created) == 0


@pytest.mark.asyncio
async def test_fabricated_quote_is_dropped_with_warning(
    session_factory: async_sessionmaker[AsyncSession],
    caplog,
):
    """Quotes not matching any utterance text are dropped."""
    async with session_factory() as db:
        await seed_tags(db)
        convo = Conversation(title="Test", interviewer="David", status="processing")
        db.add(convo)
        await db.flush()
        db.add(
            Utterance(
                conversation_id=convo.id,
                idx=0,
                speaker_label="Maria",
                speaker_side="them",
                text="We export the spreadsheet weekly",
            )
        )
        await db.flush()
        convo_id = convo.id

        fake = FakeLLMClient()
        fake.set_fixture(
            "tagger",
            {
                "highlights": [
                    {
                        "utterance_idx": 0,
                        "tag_key": "pain",
                        "quote": "AI-powered system detects infringements automatically in real-time",
                        "confidence": 0.9,
                        "rationale": "fabricated",
                    },
                ],
            },
        )

        import logging

        with caplog.at_level(logging.WARNING):
            created = await run_tag(db, convo_id, fake)
        await db.commit()

        assert len(created) == 0
        assert "Fabricated quote" in caplog.text


@pytest.mark.asyncio
async def test_taxonomy_loaded_from_db_including_custom_tags(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Custom tags added to DB should appear in the prompt input."""
    async with session_factory() as db:
        await seed_tags(db)
        # Add a custom tag
        db.add(
            Tag(
                key="competitor_mention",
                emoji="🏁",
                name="Competitor mention",
                description="Customer mentions a competitor",
                signal_strength="medium",
                sort_order=13,
                is_active=True,
            )
        )
        await db.flush()

        convo = Conversation(title="Test", interviewer="David", status="processing")
        db.add(convo)
        await db.flush()
        db.add(
            Utterance(
                conversation_id=convo.id,
                idx=0,
                speaker_label="Maria",
                speaker_side="them",
                text="We tried Acme competitor product but it was too expensive",
            )
        )
        await db.flush()
        convo_id = convo.id

        fake = FakeLLMClient()
        fake.set_fixture("tagger", {"highlights": []})

        await run_tag(db, convo_id, fake)
        await db.commit()

        # Verify the taxonomy in the prompt input included the custom tag
        assert len(fake.calls) == 1
        input_data = fake.calls[0]["input_data"]
        assert "competitor_mention" in input_data["taxonomy"]


@pytest.mark.asyncio
async def test_small_context_produces_more_llm_calls_than_large(
    session_factory: async_sessionmaker[AsyncSession],
):
    """run_tag with a small max_context makes more LLM calls than with a large max_context.

    This validates that the max_context argument actually drives chunking in the
    real run_tag path, not just in calculate_chunk_size alone.
    """
    from app.llm.tagging import run_tag

    num_utterances = 200  # Long enough transcript to require multiple chunks at small context

    async def _run_with_context(max_context: int) -> int:
        """Run tagger with given max_context and return the number of LLM calls made."""
        async with session_factory() as db:
            await seed_tags(db)
            from app.models import Company

            company = Company(name="TestCo")
            db.add(company)
            await db.flush()

            convo = Conversation(
                title="Long Transcript",
                company_id=company.id,
                interviewer="David",
                status="processing",
                raw_transcript="",
                transcript_format="name_colon",
            )
            db.add(convo)
            await db.flush()

            # Create many utterances to force multiple chunks
            for i in range(num_utterances):
                speaker = "David" if i % 2 == 0 else "Maria"
                side = "us" if i % 2 == 0 else "them"
                db.add(
                    Utterance(
                        conversation_id=convo.id,
                        idx=i,
                        speaker_label=speaker,
                        speaker_side=side,
                        text=f"This is utterance number {i} with enough text to be realistic",
                    )
                )
            await db.flush()
            convo_id = convo.id

            fake = FakeLLMClient()
            fake.set_fixture("tagger", {"highlights": []})

            await run_tag(db, convo_id, fake, max_context=max_context)
            return len(fake.calls)

    # Small context (4096 tokens) → small chunks → more LLM calls
    calls_small = await _run_with_context(4096)
    # Large context (131072 tokens) → large chunks → fewer LLM calls
    calls_large = await _run_with_context(131072)

    assert calls_small > calls_large, (
        f"Small context ({calls_small} calls) should produce more LLM calls "
        f"than large context ({calls_large} calls) for {num_utterances} utterances"
    )
    # Sanity: small context should produce multiple chunks
    assert calls_small > 1, f"Expected multiple chunks with 4096 context, got {calls_small} calls"
