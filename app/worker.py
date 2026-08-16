"""Background job worker: polls jobs table, runs handlers, chains pipeline."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Conversation, Job, Utterance, utcnow

logger = logging.getLogger(__name__)

# Type for job handlers
HandlerFunc = Callable[[AsyncSession, Job, Settings], Coroutine[Any, Any, None]]


async def handle_ingest(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Ingest handler: normalize transcript → create utterances → enqueue tag.

    Uses deterministic parsing first. On NeedsLLMNormalization, falls back to
    LLM normalization via the factory-created client. If no API key is configured
    and backend is openai, the deterministic-only path is preserved (no LLM fallback).
    """
    from app.llm.factory import create_llm_client
    from app.normalize import NeedsLLMNormalization, normalize, normalize_with_llm_fallback

    convo = await db.get(Conversation, job.conversation_id)
    if not convo:
        raise ValueError(f"Conversation {job.conversation_id} not found")

    raw = convo.raw_transcript or ""
    fmt = convo.transcript_format or "auto"
    interviewer = convo.interviewer

    try:
        utterances = normalize(raw, fmt=fmt, interviewer=interviewer)
    except NeedsLLMNormalization:
        # Attempt LLM fallback if a real backend is available
        llm = create_llm_client(settings, agent="normalizer")
        try:
            from app.llm.client import FakeLLMClient

            if isinstance(llm, FakeLLMClient):
                # No real LLM available (no API key, no local backend) — cannot normalize
                convo.status = "failed"
                raise ValueError(
                    "Transcript could not be parsed deterministically and no LLM "
                    "backend is configured for normalization fallback."
                )
            utterances = await normalize_with_llm_fallback(
                raw, interviewer=interviewer, llm_client=llm, fmt=fmt
            )
        finally:
            if hasattr(llm, "close"):
                await llm.close()

    # Delete existing utterances (for reprocessing)
    existing = await db.execute(select(Utterance).where(Utterance.conversation_id == convo.id))
    for u in existing.scalars().all():
        await db.delete(u)
    await db.flush()

    # Create utterance rows
    for utt in utterances:
        db.add(
            Utterance(
                conversation_id=convo.id,
                idx=utt.idx,
                speaker_label=utt.speaker_label,
                speaker_side=utt.speaker_side,
                text=utt.text,
                start_ms=utt.start_ms,
            )
        )

    await db.flush()

    # Enqueue tag job
    tag_job = Job(
        conversation_id=convo.id,
        kind="tag",
        payload={"conversation_id": convo.id},
        status="queued",
    )
    db.add(tag_job)
    await db.flush()


async def handle_tag(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Tag handler: run tagger LLM → persist highlights → enqueue analyze."""
    from app.llm.factory import create_llm_client
    from app.llm.tagging import run_tag

    conversation_id = job.conversation_id
    if not conversation_id:
        raise ValueError("Tag job missing conversation_id")

    # Use factory to select appropriate client (openai, local/ollama, or fake)
    llm = create_llm_client(settings, agent="tagger")

    try:
        await run_tag(db, conversation_id, llm, max_context=settings.llm_max_context)
    finally:
        if hasattr(llm, "close"):
            await llm.close()

    # Enqueue analyze job
    analyze_job = Job(
        conversation_id=conversation_id,
        kind="analyze",
        payload={"conversation_id": conversation_id},
        status="queued",
    )
    db.add(analyze_job)
    await db.flush()

    # Chain hypothesis_link job only when open hypotheses exist (no delay to analyze)
    from app.models import Hypothesis

    open_count_result = await db.execute(
        select(Hypothesis.id).where(Hypothesis.status == "open").limit(1)
    )
    if open_count_result.scalar_one_or_none() is not None:
        hypothesis_link_job = Job(
            conversation_id=conversation_id,
            kind="hypothesis_link",
            payload={"conversation_id": conversation_id},
            status="queued",
        )
        db.add(hypothesis_link_job)
        await db.flush()


async def handle_analyze(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Analyze handler: run analyst LLM → persist analysis → mark conversation ready."""
    from app.llm.analyst import run_analyze
    from app.llm.factory import create_llm_client

    conversation_id = job.conversation_id
    if not conversation_id:
        raise ValueError("Analyze job missing conversation_id")

    # Use factory to select appropriate client (openai, local/ollama, or fake)
    llm = create_llm_client(settings, agent="analyst")

    try:
        await run_analyze(db, conversation_id, llm)
    finally:
        if hasattr(llm, "close"):
            await llm.close()

    # Mark conversation ready
    convo = await db.get(Conversation, conversation_id)
    if convo:
        convo.status = "ready"
    await db.flush()


async def handle_synthesize(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Synthesize handler: run synthesizer LLM on filtered highlights."""
    from app.llm.factory import create_llm_client
    from app.llm.synthesizer import run_synthesize

    payload = job.payload or {}
    analysis_id = payload.get("analysis_id")
    filters = payload.get("filters", {})

    if not analysis_id:
        raise ValueError("Synthesize job missing analysis_id")

    # Use factory to select appropriate client (openai, local/ollama, or fake)
    llm = create_llm_client(settings, agent="synthesizer")

    try:
        await run_synthesize(db, analysis_id, filters, llm)
    finally:
        if hasattr(llm, "close"):
            await llm.close()


async def handle_hypothesis_link(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Hypothesis linker handler: propose evidence links for open hypotheses."""
    from app.llm.factory import create_llm_client
    from app.llm.linker import run_hypothesis_link

    conversation_id = job.conversation_id
    if not conversation_id:
        raise ValueError("hypothesis_link job missing conversation_id")

    llm = create_llm_client(settings, agent="hypothesis_linker")

    try:
        await run_hypothesis_link(db, conversation_id, llm)
    finally:
        if hasattr(llm, "close"):
            await llm.close()


# Handler registry
HANDLERS: dict[str, HandlerFunc] = {
    "ingest": handle_ingest,
    "tag": handle_tag,
    "analyze": handle_analyze,
    "synthesize": handle_synthesize,
    "hypothesis_link": handle_hypothesis_link,
}


async def run_worker_once(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    handlers: dict[str, HandlerFunc] | None = None,
) -> bool:
    """Process one queued job. Returns True if a job was processed.

    Uses an atomic UPDATE...WHERE (CAS pattern) portable across SQLite and Postgres.
    """
    if handlers is None:
        handlers = HANDLERS

    now = utcnow()

    async with session_factory() as db:
        # Find oldest eligible job (FIFO)
        result = await db.execute(
            select(Job.id)
            .where(
                Job.status == "queued",
                (Job.run_after == None) | (Job.run_after <= now),  # noqa: E711
            )
            .order_by(Job.created_at)
            .limit(1)
        )
        job_row = result.scalar_one_or_none()

        if job_row is None:
            return False

        candidate_id = job_row

        # Atomic CAS claim: UPDATE ... WHERE id = ? AND status = 'queued'
        # This is portable across SQLite/Postgres and prevents double-claiming.
        claim_result = await db.execute(
            update(Job)
            .where(Job.id == candidate_id, Job.status == "queued")
            .values(
                status="running",
                started_at=now,
                attempts=Job.attempts + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()

        # If no rows were updated, another worker claimed this job
        if claim_result.rowcount == 0:
            return False

        claimed_job_id = candidate_id

    # Execute handler in separate session
    async with session_factory() as db:
        job_id = claimed_job_id
        job_kind = "unknown"
        try:
            # Re-load job in new session
            job = await db.get(Job, job_id)
            if job is None:
                return True
            job_kind = job.kind

            handler = handlers.get(job.kind)
            if handler is None:
                job.status = "error"
                job.error = f"Unknown job kind: {job.kind}"
                job.finished_at = utcnow()
                await db.commit()
                return True

            await handler(db, job, settings)

            job.status = "done"
            job.finished_at = utcnow()
            job.error = None
            await db.commit()

        except Exception as e:
            await db.rollback()
            logger.exception("Job %s (%s) failed: %s", job_id, job_kind, e)

            # Re-open session for error update
            async with session_factory() as err_db:
                job = await err_db.get(Job, job_id)
                if job:
                    max_retries = settings.worker_max_retries
                    if job.attempts >= max_retries:
                        job.status = "error"
                        job.error = str(e)[:1000]
                        job.finished_at = utcnow()

                        # Determine conversation status on terminal failure
                        if job.conversation_id:
                            convo = await err_db.get(Conversation, job.conversation_id)
                            if convo and convo.status == "processing":
                                # Check if any prior step succeeded (has done jobs)
                                prior_done = await err_db.execute(
                                    select(Job.id)
                                    .where(
                                        Job.conversation_id == job.conversation_id,
                                        Job.status == "done",
                                        Job.id != job.id,
                                    )
                                    .limit(1)
                                )
                                if prior_done.scalar_one_or_none() is not None:
                                    # Partial: some steps succeeded, this one failed
                                    convo.status = "partial"
                                else:
                                    convo.status = "failed"
                    else:
                        # Retry with backoff
                        job.status = "queued"
                        backoff_seconds = min(2**job.attempts * 5, 60)
                        job.run_after = utcnow() + timedelta(seconds=backoff_seconds)
                        job.error = str(e)[:1000]

                    await err_db.commit()

    return True


async def worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Main worker loop. Polls every settings.worker_poll_interval seconds."""
    logger.info("Worker started")
    while True:
        try:
            processed = await run_worker_once(session_factory, settings)
            if not processed:
                await asyncio.sleep(settings.worker_poll_interval)
        except asyncio.CancelledError:
            logger.info("Worker stopped")
            return
        except Exception:
            logger.exception("Worker loop error")
            await asyncio.sleep(settings.worker_poll_interval)
