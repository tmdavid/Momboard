"""T07 RED: Atomic guarded UPDATE job claiming — FIFO, no-double-claim, resilience, partial status.

These tests verify the worker's atomicity guarantees:
- FIFO ordering (oldest job claimed first)
- No double-claiming (concurrent workers don't claim same job)
- Resilience (worker survives handler exceptions and continues)
- Partial status (tag succeeds but analyze fails → conversation status = 'partial')
- Portable across SQLite and Postgres
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Conversation, Job, utcnow
from app.seed import seed_tags
from app.worker import run_worker_once


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        env="test",
        worker_max_retries=3,
        worker_poll_interval=0.01,
    )


@pytest.mark.asyncio
async def test_fifo_ordering_oldest_job_claimed_first(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """Jobs are processed in FIFO order (created_at ascending)."""
    processed_order: list[int] = []

    async with session_factory() as session:
        # Create jobs with different created_at to ensure order
        import datetime

        base_time = utcnow()
        for i in range(3):
            job = Job(
                kind="order_test",
                payload={"idx": i},
                status="queued",
                created_at=base_time + datetime.timedelta(seconds=i),
            )
            session.add(job)
        await session.commit()

    async def order_handler(db: AsyncSession, job: Job, settings: Settings) -> None:
        processed_order.append(job.payload["idx"])

    for _ in range(3):
        await run_worker_once(
            session_factory, test_settings, handlers={"order_test": order_handler}
        )

    assert processed_order == [0, 1, 2], f"Expected FIFO order [0,1,2], got {processed_order}"


@pytest.mark.asyncio
async def test_no_double_claim_concurrent_workers(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """Two concurrent workers must not claim the same job."""
    claim_count = 0

    async with session_factory() as session:
        job = Job(kind="concurrent_test", payload={}, status="queued")
        session.add(job)
        await session.commit()

    async def slow_handler(db: AsyncSession, job: Job, settings: Settings) -> None:
        nonlocal claim_count
        claim_count += 1
        await asyncio.sleep(0.1)  # Simulate work

    # Run two workers concurrently
    results = await asyncio.gather(
        run_worker_once(session_factory, test_settings, handlers={"concurrent_test": slow_handler}),
        run_worker_once(session_factory, test_settings, handlers={"concurrent_test": slow_handler}),
    )

    # Exactly one worker should have claimed the job
    assert sum(results) == 1, f"Expected exactly 1 claim, got {sum(results)}"
    assert claim_count == 1, f"Handler was called {claim_count} times"


@pytest.mark.asyncio
async def test_worker_survives_handler_exception_and_processes_next(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """After a handler crashes, the worker continues processing the next job."""
    processed: list[str] = []

    async with session_factory() as session:
        # Two jobs: first will fail, second should still succeed
        session.add(Job(kind="crash", payload={}, status="queued"))
        session.add(Job(kind="succeed", payload={}, status="queued"))
        await session.commit()

    async def crash_handler(db: AsyncSession, job: Job, settings: Settings) -> None:
        raise RuntimeError("intentional crash")

    async def succeed_handler(db: AsyncSession, job: Job, settings: Settings) -> None:
        processed.append("done")

    handlers = {"crash": crash_handler, "succeed": succeed_handler}

    # First call processes the crash job
    await run_worker_once(session_factory, test_settings, handlers=handlers)
    # Second call should pick up the succeed job
    await run_worker_once(session_factory, test_settings, handlers=handlers)

    assert "done" in processed


@pytest.mark.asyncio
async def test_partial_status_when_tag_succeeds_but_analyze_fails(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """If tagging succeeds but analyze fails terminally, conversation status = 'partial'."""
    async with session_factory() as session:
        await seed_tags(session)
        convo = Conversation(
            title="Partial Test",
            raw_transcript="David: test pain\nMaria: workaround here",
            transcript_format="name_colon",
            interviewer="David",
            status="processing",
        )
        session.add(convo)
        await session.flush()
        # Start with an ingest job
        session.add(Job(conversation_id=convo.id, kind="ingest", payload={}, status="queued"))
        await session.commit()
        convo_id = convo.id

    # Custom handlers: ingest and tag succeed, analyze always fails
    call_counts = {"ingest": 0, "tag": 0, "analyze": 0}

    async def good_ingest(db: AsyncSession, job: Job, settings: Settings) -> None:
        from app.worker import handle_ingest

        call_counts["ingest"] += 1
        await handle_ingest(db, job, settings)

    async def good_tag(db: AsyncSession, job: Job, settings: Settings) -> None:
        from app.worker import handle_tag

        call_counts["tag"] += 1
        await handle_tag(db, job, settings)

    async def failing_analyze(db: AsyncSession, job: Job, settings: Settings) -> None:
        call_counts["analyze"] += 1
        raise RuntimeError("Analyze always fails")

    handlers = {"ingest": good_ingest, "tag": good_tag, "analyze": failing_analyze}

    # Run worker until all jobs settle (max 20 iterations)
    for _ in range(20):
        processed = await run_worker_once(session_factory, test_settings, handlers=handlers)
        if not processed:
            # Check if there are queued jobs with future run_after
            async with session_factory() as session:
                pending = (
                    (
                        await session.execute(
                            select(Job).where(
                                Job.conversation_id == convo_id,
                                Job.status == "queued",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if pending:
                    # Advance run_after so they can be claimed
                    for j in pending:
                        j.run_after = utcnow()
                    await session.commit()
                else:
                    break

    # Conversation should be 'partial' — tag succeeded but analyze failed terminally
    async with session_factory() as session:
        convo = await session.get(Conversation, convo_id)
        assert convo is not None
        assert (
            convo.status == "partial"
        ), f"Expected 'partial' status when analyze fails but tag succeeded, got '{convo.status}'"


@pytest.mark.asyncio
async def test_run_after_respected_job_not_claimed_before_time(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """A job with run_after in the future should NOT be claimed."""
    import datetime

    async with session_factory() as session:
        future_job = Job(
            kind="future",
            payload={},
            status="queued",
            run_after=utcnow() + datetime.timedelta(hours=1),
        )
        session.add(future_job)
        await session.commit()

    async def handler(db: AsyncSession, job: Job, settings: Settings) -> None:
        pass

    result = await run_worker_once(session_factory, test_settings, handlers={"future": handler})
    assert result is False, "Job with future run_after should not be claimed"


@pytest.mark.asyncio
async def test_multiple_queued_jobs_same_conversation_fifo(
    session_factory: async_sessionmaker[AsyncSession], test_settings: Settings
):
    """Multiple queued jobs for the same conversation are processed in FIFO order."""
    import datetime

    processed_kinds: list[str] = []

    async with session_factory() as session:
        convo = Conversation(title="Multi-job", status="processing")
        session.add(convo)
        await session.flush()

        base_time = utcnow()
        for i, kind in enumerate(["first", "second", "third"]):
            session.add(
                Job(
                    conversation_id=convo.id,
                    kind=kind,
                    payload={},
                    status="queued",
                    created_at=base_time + datetime.timedelta(seconds=i),
                )
            )
        await session.commit()

    async def track_handler(db: AsyncSession, job: Job, settings: Settings) -> None:
        processed_kinds.append(job.kind)

    handlers = {"first": track_handler, "second": track_handler, "third": track_handler}

    for _ in range(3):
        await run_worker_once(session_factory, test_settings, handlers=handlers)

    assert processed_kinds == ["first", "second", "third"]
