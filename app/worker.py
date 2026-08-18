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

    # Chain hypothesis_link job only when open hypotheses exist AND conversation
    # is not simulated (T39 corpus isolation: simulated conversations must not
    # feed hypothesis linking)
    convo = await db.get(Conversation, conversation_id)
    is_simulated = convo and convo.source == "simulator"

    if not is_simulated:
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
    """Analyze handler: run analyst LLM → persist analysis → mark conversation ready.

    Chains drift_check when the conversation's contacts have prior accepted highlights.
    """
    from app.llm.analyst import run_analyze
    from app.llm.factory import create_llm_client

    conversation_id = job.conversation_id
    if not conversation_id:
        raise ValueError("Analyze job missing conversation_id")

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

    # Chain drift_check only when contacts have prior accepted history (Blocker 6)
    from app.models import ConversationContact, Highlight

    contact_ids_result = await db.execute(
        select(ConversationContact.contact_id)
        .where(ConversationContact.conversation_id == conversation_id)
    )
    contact_ids = [r[0] for r in contact_ids_result.all()]

    if contact_ids:
        # Check if any contact has prior accepted highlights (from other conversations)
        prior_convo_ids_result = await db.execute(
            select(ConversationContact.conversation_id)
            .where(
                ConversationContact.contact_id.in_(contact_ids),
                ConversationContact.conversation_id != conversation_id,
            )
            .limit(1)
        )
        has_prior = prior_convo_ids_result.scalar_one_or_none() is not None

        if has_prior:
            # Check for accepted highlights in those prior conversations
            prior_accepted = await db.execute(
                select(Highlight.id)
                .join(
                    ConversationContact,
                    ConversationContact.conversation_id == Highlight.conversation_id,
                )
                .where(
                    ConversationContact.contact_id.in_(contact_ids),
                    Highlight.conversation_id != conversation_id,
                    Highlight.status == "accepted",
                )
                .limit(1)
            )
            if prior_accepted.scalar_one_or_none() is not None:
                drift_job = Job(
                    conversation_id=conversation_id,
                    kind="drift_check",
                    payload={"conversation_id": conversation_id},
                    status="queued",
                )
                db.add(drift_job)
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

    # T40: Re-check decision integrity after new hypothesis links
    await _refresh_decision_integrity(db, conversation_id)


async def handle_drift_check(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Drift check handler: detect contradictions in contact statements."""
    from app.llm.factory import create_llm_client
    from app.services.contacts import run_drift_check

    conversation_id = job.conversation_id
    if not conversation_id:
        raise ValueError("drift_check job missing conversation_id")

    llm = create_llm_client(settings, agent="drift_checker")

    try:
        await run_drift_check(db, conversation_id, llm)
    finally:
        if hasattr(llm, "close"):
            await llm.close()

    # T40: Re-check decision integrity after drift detection
    await _refresh_decision_integrity(db, conversation_id)


async def _refresh_decision_integrity(db: AsyncSession, conversation_id: int) -> None:
    """T40: Re-check integrity of decisions citing highlights from this conversation.

    Runs after drift_check and hypothesis_link jobs. Updates integrity status
    and persists reasons without changing decision status (human decision).
    """
    from app.models import DecisionEvidence, Highlight
    from app.services.decisions import check_decision_integrity

    # Find highlights from this conversation that are cited by decisions
    cited_result = await db.execute(
        select(DecisionEvidence.decision_id)
        .join(Highlight, Highlight.id == DecisionEvidence.highlight_id)
        .where(Highlight.conversation_id == conversation_id)
    )
    affected_decision_ids = list(set(r[0] for r in cited_result.all()))

    for decision_id in affected_decision_ids:
        try:
            await check_decision_integrity(db, decision_id)
        except ValueError:
            pass  # Decision may have been deleted

    await db.flush()


async def handle_digest(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Digest handler: build and deliver weekly digest."""
    from datetime import date

    from app.llm.factory import create_llm_client
    from app.services.digest import run_digest

    payload = job.payload or {}
    week_of_str = payload.get("week_of")
    week_of = date.fromisoformat(week_of_str) if week_of_str else date.today()

    llm = create_llm_client(settings, agent="digest")
    slack_url = getattr(settings, "slack_webhook_url", None)

    try:
        await run_digest(db, week_of=week_of, llm=llm, slack_webhook_url=slack_url)
    finally:
        if hasattr(llm, "close"):
            await llm.close()


async def handle_gmeet_poll(db: AsyncSession, job: Job, settings: Settings) -> None:
    """Google Meet/Drive poll handler: check for new transcript docs.

    Self-reschedules for the next configured interval (default 30 minutes).
    Idempotent: uses run_after to prevent overlapping polls.
    """
    from app.services.gmeet import poll_drive_for_transcripts

    await poll_drive_for_transcripts(db, settings)

    # Self-reschedule next poll (idempotent — check no existing queued gmeet_poll)
    poll_interval_minutes = getattr(settings, "gdrive_poll_interval_minutes", 30)
    next_run = utcnow() + timedelta(minutes=poll_interval_minutes)

    existing_queued = await db.execute(
        select(Job.id).where(
            Job.kind == "gmeet_poll",
            Job.status == "queued",
            Job.id != job.id,
        ).limit(1)
    )
    if existing_queued.scalar_one_or_none() is None:
        reschedule_job = Job(
            kind="gmeet_poll",
            payload={},
            status="queued",
            run_after=next_run,
        )
        db.add(reschedule_job)
        await db.flush()


# Handler registry
HANDLERS: dict[str, HandlerFunc] = {
    "ingest": handle_ingest,
    "tag": handle_tag,
    "analyze": handle_analyze,
    "synthesize": handle_synthesize,
    "hypothesis_link": handle_hypothesis_link,
    "drift_check": handle_drift_check,
    "digest": handle_digest,
    "gmeet_poll": handle_gmeet_poll,
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
            select(Job.id, Job.kind, Job.conversation_id)
            .where(
                Job.status == "queued",
                (Job.run_after == None) | (Job.run_after <= now),  # noqa: E711
            )
            .order_by(Job.created_at)
            .limit(1)
        )
        job_row = result.one_or_none()

        if job_row is None:
            return False

        candidate_id, candidate_kind, candidate_conversation_id = job_row

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

        # If no rows were updated, another worker claimed this job.
        if claim_result.rowcount == 0:
            await db.rollback()
            return False

        # Publish an observable pipeline stage in the same committed claim transaction.
        # Long-running LLM work happens in a separate session, so clients can read this
        # state immediately via SSE-triggered refresh or the 5-second polling fallback.
        stage_by_kind = {
            "ingest": "normalizing",
            "tag": "tagging",
            "analyze": "analyzing",
        }
        stage = stage_by_kind.get(candidate_kind)
        if candidate_conversation_id and stage:
            await db.execute(
                update(Conversation)
                .where(Conversation.id == candidate_conversation_id)
                .values(status=stage)
            )

        await db.commit()
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
                            if convo and convo.status in {
                                "processing",
                                "normalizing",
                                "tagging",
                                "analyzing",
                            }:
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
                        # Retry with backoff. The next claim will publish the specific
                        # stage again; show a truthful generic pending state meanwhile.
                        job.status = "queued"
                        backoff_seconds = min(2**job.attempts * 5, 60)
                        job.run_after = utcnow() + timedelta(seconds=backoff_seconds)
                        job.error = str(e)[:1000]
                        if job.conversation_id:
                            convo = await err_db.get(Conversation, job.conversation_id)
                            if convo and convo.status in {
                                "normalizing",
                                "tagging",
                                "analyzing",
                            }:
                                convo.status = "processing"

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
