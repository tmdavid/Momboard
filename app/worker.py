"""Background job worker: polls jobs table, runs handlers, chains pipeline."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Conversation, Job, Utterance, utcnow
from app.normalize import NeedsLLMNormalization, normalize

logger = logging.getLogger(__name__)

# Type for job handlers
HandlerFunc = Callable[[AsyncSession, Job, Settings], Coroutine[Any, Any, None]]


async def handle_ingest(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Ingest handler: normalize transcript → create utterances → enqueue tag."""
    convo = await db.get(Conversation, job.conversation_id)
    if not convo:
        raise ValueError(f"Conversation {job.conversation_id} not found")

    raw = convo.raw_transcript or ""
    fmt = convo.transcript_format or "auto"
    interviewer = convo.interviewer

    try:
        utterances = normalize(raw, fmt=fmt, interviewer=interviewer)
    except NeedsLLMNormalization:
        # For now, try name_colon as fallback, then mark failed
        try:
            utterances = normalize(raw, fmt="name_colon", interviewer=interviewer)
        except NeedsLLMNormalization:
            # TODO: implement LLM normalizer fallback
            convo.status = "failed"
            raise ValueError("Transcript could not be parsed without LLM normalization")

    # Delete existing utterances (for reprocessing)
    existing = await db.execute(
        select(Utterance).where(Utterance.conversation_id == convo.id)
    )
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
    from app.llm.client import FakeLLMClient, OpenAIResponsesClient
    from app.llm.tagging import run_tag

    conversation_id = job.conversation_id
    if not conversation_id:
        raise ValueError("Tag job missing conversation_id")

    # Choose LLM client
    llm: OpenAIResponsesClient | FakeLLMClient
    if settings.openai_api_key:
        llm = OpenAIResponsesClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model_map={"tagger": settings.llm_model_tagger},
        )
    else:
        # No API key — use fake (for dev/test)
        fake = FakeLLMClient()
        fake.set_fixture("tagger", {"highlights": []})
        llm = fake

    try:
        await run_tag(db, conversation_id, llm)
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


async def handle_analyze(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Analyze handler: run analyst LLM → persist analysis → mark conversation ready."""
    from app.llm.analyst import run_analyze
    from app.llm.client import FakeLLMClient, OpenAIResponsesClient

    conversation_id = job.conversation_id
    if not conversation_id:
        raise ValueError("Analyze job missing conversation_id")

    llm: OpenAIResponsesClient | FakeLLMClient
    if settings.openai_api_key:
        llm = OpenAIResponsesClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model_map={"analyst": settings.llm_model_analyst},
        )
    else:
        fake = FakeLLMClient()
        fake.set_fixture("analyst", {
            "summary": "No analysis available (no API key configured)",
            "top_pains": [],
            "commitments": [],
            "compliment_ratio": 0.0,
            "mom_test_critique": {"score": 5, "good_questions": [], "violations": []},
            "suggested_followups": [],
            "open_questions": [],
        })
        llm = fake

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
    from app.llm.client import FakeLLMClient, OpenAIResponsesClient
    from app.llm.synthesizer import run_synthesize

    payload = job.payload or {}
    analysis_id = payload.get("analysis_id")
    filters = payload.get("filters", {})

    if not analysis_id:
        raise ValueError("Synthesize job missing analysis_id")

    llm: OpenAIResponsesClient | FakeLLMClient
    if settings.openai_api_key:
        llm = OpenAIResponsesClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model_map={"synthesizer": settings.llm_model_synthesizer},
        )
    else:
        fake = FakeLLMClient()
        fake.set_fixture("synthesizer", {
            "themes": [],
            "contradictions": [],
            "validate_next": [],
        })
        llm = fake

    try:
        await run_synthesize(db, analysis_id, filters, llm)
    finally:
        if hasattr(llm, "close"):
            await llm.close()


# Handler registry
HANDLERS: dict[str, HandlerFunc] = {
    "ingest": handle_ingest,
    "tag": handle_tag,
    "analyze": handle_analyze,
    "synthesize": handle_synthesize,
}


async def run_worker_once(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    handlers: dict[str, HandlerFunc] | None = None,
) -> bool:
    """Process one queued job. Returns True if a job was processed."""
    if handlers is None:
        handlers = HANDLERS

    async with session_factory() as db:
        # Claim a job atomically
        now = utcnow()
        result = await db.execute(
            select(Job)
            .where(
                Job.status == "queued",
                (Job.run_after == None) | (Job.run_after <= now),  # noqa: E711
            )
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()

        if job is None:
            return False

        # Mark running
        job.status = "running"
        job.started_at = now
        job.attempts += 1
        claimed_job_id = job.id
        await db.commit()

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

                        # Mark conversation failed if this was a terminal failure
                        if job.conversation_id:
                            convo = await err_db.get(Conversation, job.conversation_id)
                            if convo and convo.status == "processing":
                                convo.status = "failed"
                    else:
                        # Retry with backoff
                        job.status = "queued"
                        backoff_seconds = min(2 ** job.attempts * 5, 60)
                        from datetime import timedelta
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
