"""T07: Worker loop tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Conversation, Job, utcnow
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


@pytest.mark.asyncio
async def test_pipeline_retry_resets_visible_stage_to_processing(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    async with session_factory() as session:
        conversation = Conversation(title="Retry state", status="processing")
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id
        session.add(
            Job(
                kind="ingest",
                conversation_id=conversation_id,
                payload={"conversation_id": conversation_id},
                status="queued",
            )
        )
        await session.commit()

    async def fail_handler(db, job, settings):
        raise ValueError("retry me")

    await run_worker_once(
        session_factory, test_settings, handlers={"ingest": fail_handler}
    )

    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        assert conversation.status == "processing"


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_requeues_running(
    session_factory: async_sessionmaker[AsyncSession],
):
    from app.worker import reclaim_stale_jobs

    async with session_factory() as session:
        # A job orphaned in `running` (e.g. crash/suspend mid-handler).
        stale = Job(kind="tag", payload={}, status="running", started_at=utcnow(), attempts=1)
        # A queued job that must be left untouched.
        queued = Job(kind="tag", payload={}, status="queued")
        # A done job that must be left untouched.
        done = Job(kind="tag", payload={}, status="done", finished_at=utcnow())
        session.add_all([stale, queued, done])
        await session.commit()
        stale_id, queued_id, done_id = stale.id, queued.id, done.id

    reclaimed = await reclaim_stale_jobs(session_factory)
    assert reclaimed == 1

    async with session_factory() as session:
        assert (await session.get(Job, stale_id)).status == "queued"
        # attempts preserved so genuinely-wedging jobs still trip max_retries.
        assert (await session.get(Job, stale_id)).attempts == 1
        assert (await session.get(Job, stale_id)).started_at is None
        assert (await session.get(Job, queued_id)).status == "queued"
        assert (await session.get(Job, done_id)).status == "done"


@pytest.mark.asyncio
async def test_reclaim_stale_jobs_noop_when_none(
    session_factory: async_sessionmaker[AsyncSession],
):
    from app.worker import reclaim_stale_jobs

    assert await reclaim_stale_jobs(session_factory) == 0


@pytest.mark.asyncio
async def test_concurrent_workers_never_double_claim(tmp_path):
    """Many workers hitting the queue at once must each process distinct jobs.

    Uses a file-based SQLite DB so concurrent sessions share one real database
    (WAL + busy_timeout), exercising the atomic CAS claim under true concurrency.
    """
    import asyncio

    from sqlalchemy import event as sa_event
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import _set_sqlite_pragmas, create_session_factory
    from app.models import Base

    db_url = f"sqlite+aiosqlite:///{tmp_path/'w.db'}"
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False}, echo=False)
    sa_event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    settings = Settings(
        database_url=db_url, session_secret="t", openai_api_key="", env="test",
        worker_max_retries=3, worker_poll_interval=0.02,
    )

    n_jobs = 30
    async with factory() as session:
        for _ in range(n_jobs):
            session.add(Job(kind="noop", payload={}, status="queued"))
        await session.commit()

    processed_ids: list[int] = []
    lock = asyncio.Lock()

    async def record_handler(db, job, s):
        await asyncio.sleep(0.01)  # overlap workers
        async with lock:
            processed_ids.append(job.id)

    async def worker():
        while await run_worker_once(factory, settings, handlers={"noop": record_handler}):
            pass

    await asyncio.gather(*[worker() for _ in range(10)])

    assert len(processed_ids) == n_jobs
    assert len(set(processed_ids)) == n_jobs  # no double-claim
    async with factory() as session:
        done = (
            await session.execute(select(func.count()).select_from(Job).where(Job.status == "done"))
        ).scalar_one()
        assert done == n_jobs
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_worker_pool_drains_queue(tmp_path):
    """run_worker_pool with concurrency>1 drains the queue, then cancels cleanly."""
    import asyncio

    from sqlalchemy import event as sa_event
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import _set_sqlite_pragmas, create_session_factory
    from app.models import Base
    from app.worker import HANDLERS, run_worker_pool

    db_url = f"sqlite+aiosqlite:///{tmp_path/'pool.db'}"
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False}, echo=False)
    sa_event.listens_for(engine.sync_engine, "connect")(_set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    settings = Settings(
        database_url=db_url, session_secret="t", openai_api_key="", env="test",
        worker_poll_interval=0.05, worker_concurrency=5,
    )

    async with factory() as session:
        for _ in range(15):
            session.add(Job(kind="noop", payload={}, status="queued"))
        await session.commit()

    async def ok_handler(db, job, s):
        await asyncio.sleep(0.01)

    HANDLERS["noop"] = ok_handler
    remaining = 15
    try:
        pool = asyncio.create_task(run_worker_pool(factory, settings))
        for _ in range(100):
            await asyncio.sleep(0.05)
            async with factory() as session:
                remaining = (
                    await session.execute(
                        select(func.count()).select_from(Job).where(Job.status == "queued")
                    )
                ).scalar_one()
            if remaining == 0:
                break
        assert remaining == 0
        pool.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pool
    finally:
        HANDLERS.pop("noop", None)
        await engine.dispose()
