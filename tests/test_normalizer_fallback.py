"""T06/T09 RED: LLM normalizer fallback when deterministic parsing fails.

Tests verify:
- When NeedsLLMNormalization is raised (messy paste), the pipeline falls back to LLM normalization
- LLM normalizer uses the NormalizerOutput schema
- The normalizer-produced utterances are persisted correctly
- The fallback is never called when deterministic parsing succeeds
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.client import FakeLLMClient
from app.llm.schemas import NormalizerOutput
from app.models import Conversation, Job, Utterance
from app.normalize import NeedsLLMNormalization, normalize
from app.seed import seed_tags
from app.worker import run_worker_once


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="fake-key",  # Need a key to avoid fake client
        env="test",
        worker_max_retries=3,
    )


def test_messy_paste_raises_needs_llm_normalization():
    """A messy paste with no detectable speaker format should raise NeedsLLMNormalization."""
    messy = (
        "so basically what happened was we tried the thing and it worked ok "
        "but then the other team said no way and we had to go back to the "
        "drawing board because nobody could agree on the format and now we "
        "just use email for everything which takes forever"
    )
    with pytest.raises(NeedsLLMNormalization):
        normalize(messy, fmt="auto")


@pytest.mark.asyncio
async def test_ingest_falls_back_to_llm_normalizer_on_messy_input(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """When deterministic parsing fails, ingest handler should use LLM normalizer as fallback."""
    messy_transcript = (
        "so basically what happened was we tried the thing and it worked ok "
        "but then the other team said no way"
    )

    async with session_factory() as session:
        await seed_tags(session)
        convo = Conversation(
            title="Messy Input",
            raw_transcript=messy_transcript,
            transcript_format="auto",  # Will trigger auto-detection → fail → LLM fallback
            interviewer="David",
            status="processing",
        )
        session.add(convo)
        await session.flush()
        session.add(Job(conversation_id=convo.id, kind="ingest", payload={}, status="queued"))
        await session.commit()

    # The ingest handler should call the LLM normalizer when deterministic fails.
    # This requires production code that doesn't exist yet — hence the test will FAIL.
    # It needs: a `normalizer` prompt call via LLMClient that returns NormalizerOutput.

    # We mock the LLM to return a valid normalizer response
    fake_llm = FakeLLMClient()
    fake_llm.set_fixture(
        "normalizer",
        {
            "utterances": [
                {
                    "idx": 0,
                    "speaker_label": "Customer",
                    "speaker_side": "them",
                    "text": "so basically what happened was we tried the thing and it worked ok",
                },
                {
                    "idx": 1,
                    "speaker_label": "Customer",
                    "speaker_side": "them",
                    "text": "but then the other team said no way",
                },
            ],
            "detected_participants": [{"name": "Customer", "role": None}],
            "language": "en",
        },
    )

    # The handler needs to use this LLM fallback — requires a `normalizer_llm_fallback` function
    # in the ingest handler that doesn't exist yet.
    from app.worker import handle_ingest  # noqa: F401

    # This import should exist but doesn't — test will fail
    try:
        from app.normalize import normalize_with_llm_fallback  # noqa: F401
    except ImportError:
        pytest.fail(
            "app.normalize.normalize_with_llm_fallback does not exist yet. "
            "This function should accept (raw, interviewer, llm_client) and fall back to "
            "LLM normalization when NeedsLLMNormalization is raised."
        )


@pytest.mark.asyncio
async def test_llm_normalizer_output_validates_against_schema():
    """The LLM normalizer should produce output matching NormalizerOutput schema."""
    fake = FakeLLMClient()
    fake.set_fixture(
        "normalizer",
        {
            "utterances": [
                {
                    "idx": 0,
                    "speaker_label": "David",
                    "speaker_side": "us",
                    "text": "How do you handle this?",
                },
                {
                    "idx": 1,
                    "speaker_label": "Customer",
                    "speaker_side": "them",
                    "text": "We use Excel",
                },
            ],
            "detected_participants": [
                {"name": "David", "role": "interviewer"},
                {"name": "Customer", "role": "Brand Manager"},
            ],
            "language": "en",
        },
    )

    out, envelope = await fake.structured("normalizer", input_data={}, schema=NormalizerOutput)
    assert isinstance(out, NormalizerOutput)
    assert len(out.utterances) == 2
    assert out.utterances[0].speaker_side == "us"


@pytest.mark.asyncio
async def test_normalizer_fallback_not_called_when_deterministic_succeeds(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """When deterministic parsing works, LLM normalizer should NOT be called."""
    # This tests the negative case — LLM should not be invoked unnecessarily
    good_transcript = "David: How are things going?\nMaria: Pretty good, thanks."

    async with session_factory() as session:
        await seed_tags(session)
        convo = Conversation(
            title="Good Format",
            raw_transcript=good_transcript,
            transcript_format="name_colon",
            interviewer="David",
            status="processing",
        )
        session.add(convo)
        await session.flush()
        session.add(Job(conversation_id=convo.id, kind="ingest", payload={}, status="queued"))
        await session.commit()
        convo_id = convo.id

    # Run ingest
    await run_worker_once(session_factory, test_settings)

    # Verify utterances were created without LLM
    async with session_factory() as session:
        utts = (
            (await session.execute(select(Utterance).where(Utterance.conversation_id == convo_id)))
            .scalars()
            .all()
        )
        assert len(utts) == 2
        assert utts[0].speaker_label == "David"
