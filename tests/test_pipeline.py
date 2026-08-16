"""T08: Pipeline chaining tests."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Analysis, Conversation, Job, Utterance
from app.seed import seed_tags
from app.worker import run_worker_once


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",  # Will use FakeLLMClient
        env="test",
        worker_max_retries=3,
    )


@pytest.mark.asyncio
async def test_ingest_success_persists_utterances_and_enqueues_tag(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    async with session_factory() as session:
        await seed_tags(session)
        convo = Conversation(
            title="Test",
            raw_transcript="David: hi\nMaria: hello world",
            transcript_format="name_colon",
            interviewer="David",
            status="processing",
        )
        session.add(convo)
        await session.flush()
        job = Job(
            conversation_id=convo.id,
            kind="ingest",
            payload={"conversation_id": convo.id},
            status="queued",
        )
        session.add(job)
        await session.commit()
        convo_id = convo.id

    # Process ingest
    await run_worker_once(session_factory, test_settings)

    async with session_factory() as session:
        utts = (
            await session.execute(
                select(Utterance).where(Utterance.conversation_id == convo_id)
            )
        ).scalars().all()
        assert len(utts) == 2
        assert utts[0].speaker_label == "David"

        # Check tag job was enqueued
        tag_jobs = (
            await session.execute(
                select(Job).where(Job.conversation_id == convo_id, Job.kind == "tag")
            )
        ).scalars().all()
        assert len(tag_jobs) == 1
        assert tag_jobs[0].status == "queued"


@pytest.mark.asyncio
async def test_full_chain_reaches_ready(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """Full pipeline: ingest → tag → analyze → conversation becomes ready."""
    async with session_factory() as session:
        await seed_tags(session)
        convo = Conversation(
            title="Full Chain Test",
            raw_transcript="David: How do you handle this today?\nMaria: We use a spreadsheet, it takes forever.",
            transcript_format="name_colon",
            interviewer="David",
            status="processing",
        )
        session.add(convo)
        await session.flush()
        job = Job(
            conversation_id=convo.id,
            kind="ingest",
            payload={"conversation_id": convo.id},
            status="queued",
        )
        session.add(job)
        await session.commit()
        convo_id = convo.id

    # Run worker until no more jobs (max 10 iterations to avoid infinite loop)
    for _ in range(10):
        processed = await run_worker_once(session_factory, test_settings)
        if not processed:
            break

    async with session_factory() as session:
        convo = await session.get(Conversation, convo_id)
        assert convo.status == "ready"

        # Utterances exist
        utts = (
            await session.execute(
                select(Utterance).where(Utterance.conversation_id == convo_id)
            )
        ).scalars().all()
        assert len(utts) >= 2

        # Analysis exists
        analyses = (
            await session.execute(
                select(Analysis).where(Analysis.conversation_id == convo_id)
            )
        ).scalars().all()
        assert len(analyses) >= 1
