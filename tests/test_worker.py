"""T07: Worker loop tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Job, utcnow
from app.worker import run_worker_once


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        env="test",
        worker_max_retries=3,
    )


@pytest.mark.asyncio
async def test_worker_picks_up_queued_job_and_marks_done(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    async with session_factory() as session:
        job = Job(kind="noop", payload={}, status="queued")
        session.add(job)
        await session.commit()
        job_id = job.id

    # Define a noop handler
    async def ok_handler(db, job, settings):
        pass

    processed = await run_worker_once(
        session_factory, test_settings, handlers={"noop": ok_handler}
    )
    assert processed is True

    async with session_factory() as session:
        job = await session.get(Job, job_id)
        assert job.status == "done"
        assert job.started_at is not None
        assert job.finished_at is not None


@pytest.mark.asyncio
async def test_failing_job_retries_then_error(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    async with session_factory() as session:
        job = Job(kind="fail", payload={}, status="queued")
        session.add(job)
        await session.commit()
        job_id = job.id

    async def fail_handler(db, job, settings):
        raise ValueError("Intentional failure")

    # Drive three attempts while explicitly advancing past persisted backoff.
    for attempt in range(3):
        await run_worker_once(
            session_factory, test_settings, handlers={"fail": fail_handler}
        )
        if attempt < 2:
            async with session_factory() as session:
                queued_job = await session.get(Job, job_id)
                assert queued_job is not None
                assert queued_job.status == "queued"
                assert queued_job.run_after is not None
                queued_job.run_after = utcnow()
                await session.commit()

    async with session_factory() as session:
        job = await session.get(Job, job_id)
        assert job.status == "error"
        assert "Intentional failure" in (job.error or "")
        assert job.attempts == 3


@pytest.mark.asyncio
async def test_worker_returns_false_when_no_jobs(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    processed = await run_worker_once(session_factory, test_settings)
    assert processed is False


@pytest.mark.asyncio
async def test_unknown_job_kind_errors(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    async with session_factory() as session:
        job = Job(kind="nonexistent", payload={}, status="queued")
        session.add(job)
        await session.commit()
        job_id = job.id

    await run_worker_once(session_factory, test_settings)

    async with session_factory() as session:
        job = await session.get(Job, job_id)
        assert job.status == "error"
        assert "Unknown job kind" in (job.error or "")
