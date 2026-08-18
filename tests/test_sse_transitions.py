"""T08 RED: SSE transition-only events plus tests.

Tests verify:
- SSE endpoint emits events ONLY on state transitions (not repeated polls of same state)
- Events follow the format {kind}.{status}
- Stream terminates on terminal state (ready/failed)
- No duplicate events for the same transition
"""

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Conversation, Job, utcnow


@pytest.mark.asyncio
async def test_sse_emits_only_transitions_not_repeated_state(
    app, auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """SSE should emit each transition exactly once, not repeat current state on every poll.

    The current implementation re-emits all job states on every poll iteration.
    A correct transition-only implementation should track what was already sent and only
    emit NEW transitions.
    """
    # Create a conversation with a done ingest job and a running tag job
    async with session_factory() as session:
        convo = Conversation(title="SSE Test", status="processing")
        session.add(convo)
        await session.flush()
        convo_id = convo.id
        # Ingest already done, tag running
        session.add(
            Job(
                conversation_id=convo_id,
                kind="ingest",
                status="done",
                payload={},
                started_at=utcnow(),
                finished_at=utcnow(),
            )
        )
        session.add(
            Job(
                conversation_id=convo_id,
                kind="tag",
                status="running",
                payload={},
                started_at=utcnow(),
            )
        )
        await session.commit()

    # After a brief delay, mark conversation ready so stream can close
    async def mark_ready():
        await asyncio.sleep(0.3)
        async with session_factory() as session:
            convo = await session.get(Conversation, convo_id)
            convo.status = "ready"
            await session.commit()

    events: list[dict] = []
    try:
        async with asyncio.timeout(5):
            # Start background task to transition the conversation
            task = asyncio.create_task(mark_ready())

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies=auth_client.cookies,
            ) as sse_client:
                async with sse_client.stream(
                    "GET", f"/api/conversations/{convo_id}/events"
                ) as response:
                    event_name = ""
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            event_name = line[len("event:") :].strip()
                        elif line.startswith("data:"):
                            data = line[len("data:") :].strip()
                            events.append({"event": event_name, "data": json.loads(data)})
                            if event_name == "done":
                                break

            await task
    except TimeoutError:
        pass

    # Key invariant: each transition event type appears at most once
    # (transition-only means we don't emit "ingest.done" twice even if polled multiple times)
    from collections import Counter

    event_keys = [e["event"] for e in events]
    counts = Counter(event_keys)
    for key, count in counts.items():
        assert count == 1, (
            f"Event '{key}' emitted {count} times; expected exactly 1 (transition-only). "
            f"The SSE endpoint must track previously-sent events and not re-emit them."
        )


@pytest.mark.asyncio
async def test_sse_terminates_on_ready_status(
    app, auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """SSE stream should close after emitting 'done' event when conversation reaches terminal state."""
    async with session_factory() as session:
        convo = Conversation(title="SSE Terminal", status="ready")
        session.add(convo)
        await session.flush()
        convo_id = convo.id
        session.add(
            Job(
                conversation_id=convo_id,
                kind="ingest",
                status="done",
                payload={},
                started_at=utcnow(),
                finished_at=utcnow(),
            )
        )
        await session.commit()

    got_done = False
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=auth_client.cookies,
    ) as sse_client:
        try:
            async with asyncio.timeout(5):
                async with sse_client.stream(
                    "GET", f"/api/conversations/{convo_id}/events"
                ) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("event:") and "done" in line:
                            got_done = True
                            break
        except TimeoutError:
            pass

    assert got_done, "SSE stream should emit 'done' event for terminal 'ready' status"


@pytest.mark.asyncio
async def test_sse_terminates_on_failed_status(
    app, auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """SSE stream should close on 'failed' terminal state too."""
    async with session_factory() as session:
        convo = Conversation(title="SSE Failed", status="failed")
        session.add(convo)
        await session.flush()
        convo_id = convo.id
        session.add(
            Job(
                conversation_id=convo_id,
                kind="ingest",
                status="error",
                payload={},
                error="something went wrong",
                started_at=utcnow(),
                finished_at=utcnow(),
            )
        )
        await session.commit()

    got_done = False
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=auth_client.cookies,
    ) as sse_client:
        try:
            async with asyncio.timeout(5):
                async with sse_client.stream(
                    "GET", f"/api/conversations/{convo_id}/events"
                ) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("event:") and "done" in line:
                            got_done = True
                            break
        except TimeoutError:
            pass

    assert got_done, "SSE stream should emit 'done' event for terminal 'failed' status"


@pytest.mark.asyncio
async def test_sse_event_data_contains_kind_and_status(
    app, auth_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
):
    """Each SSE event data payload must contain 'kind' and 'status' fields."""
    async with session_factory() as session:
        convo = Conversation(title="SSE Data Test", status="ready")
        session.add(convo)
        await session.flush()
        convo_id = convo.id
        session.add(
            Job(
                conversation_id=convo_id,
                kind="tag",
                status="done",
                payload={},
                started_at=utcnow(),
                finished_at=utcnow(),
            )
        )
        await session.commit()

    events: list[dict] = []
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=auth_client.cookies,
    ) as sse_client:
        try:
            async with asyncio.timeout(5):
                async with sse_client.stream(
                    "GET", f"/api/conversations/{convo_id}/events"
                ) as response:
                    event_name = ""
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            event_name = line[len("event:") :].strip()
                        elif line.startswith("data:"):
                            data = json.loads(line[len("data:") :].strip())
                            events.append({"event": event_name, "data": data})
                            if event_name == "done":
                                break
        except TimeoutError:
            pass

    # All non-done events must have kind and status in data
    for e in events:
        if e["event"] != "done":
            assert "kind" in e["data"], f"Event {e['event']} missing 'kind' in data"
            assert "status" in e["data"], f"Event {e['event']} missing 'status' in data"


@pytest.mark.asyncio
async def test_worker_publishes_stage_before_handler_work(
    app, session_factory: async_sessionmaker[AsyncSession]
):
    """UX #10: stage state is committed before slow normalization/LLM work."""
    from app.worker import run_worker_once

    async with session_factory() as session:
        convo = Conversation(title="Observable stage", status="processing")
        session.add(convo)
        await session.flush()
        conversation_id = convo.id
        session.add(
            Job(
                conversation_id=conversation_id,
                kind="ingest",
                status="queued",
                payload={"conversation_id": conversation_id},
            )
        )
        await session.commit()

    observed_statuses: list[str] = []

    async def observe_stage(db, job, settings):
        async with session_factory() as observer:
            observed = await observer.get(Conversation, conversation_id)
            assert observed is not None
            observed_statuses.append(observed.status)
        current = await db.get(Conversation, conversation_id)
        assert current is not None
        current.status = "ready"

    processed = await run_worker_once(
        session_factory,
        app.state.settings,
        handlers={"ingest": observe_stage},
    )

    assert processed is True
    assert observed_statuses == ["normalizing"]
