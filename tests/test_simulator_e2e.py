"""Tests for T39 end-to-end: simulator session end produces tag + analyze (critique).

Verifies Finding 3: the standard worker chain runs both tag and analyze jobs,
producing a critique/score for the simulated conversation.
"""

import pytest
from sqlalchemy import select

from app.config import Settings
from app.llm.client import FakeLLMClient
from app.models import (
    Analysis,
    Conversation,
    Highlight,
    Job,
    Utterance,
)


def _test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test-secret",
        openai_api_key="",
        env="test",
        worker_poll_interval=0.1,
    )


@pytest.mark.asyncio
async def test_simulator_end_produces_tag_and_analyze_chain(seeded_db, session_factory):
    """End-to-end: ending a simulator session enqueues tag → tag handler enqueues analyze
    → analyze handler produces critique/score. No feedback loops into hypothesis-linking."""
    from app.services.simulator import (
        build_persona,
        create_simulator_session,
        end_simulator_session,
    )
    from app.worker import handle_analyze, handle_tag

    settings = _test_settings()
    db = seeded_db
    llm = FakeLLMClient()

    # Build persona + create session + add turns
    persona = await build_persona(db, llm=llm)
    await db.flush()
    convo = await create_simulator_session(db, persona.id)
    await db.flush()

    # Add some turns for the tagger/analyzer to work with
    utt1 = Utterance(
        conversation_id=convo.id, idx=0,
        speaker_label="Interviewer", speaker_side="us",
        text="Tell me about how you handle reporting today.",
    )
    utt2 = Utterance(
        conversation_id=convo.id, idx=1,
        speaker_label="Marta", speaker_side="them",
        text="Every week I spend 2 hours exporting data to Excel manually.",
    )
    utt3 = Utterance(
        conversation_id=convo.id, idx=2,
        speaker_label="Interviewer", speaker_side="us",
        text="What happens if you don't do it?",
    )
    utt4 = Utterance(
        conversation_id=convo.id, idx=3,
        speaker_label="Marta", speaker_side="them",
        text="The manager doesn't get the dashboard and decisions are delayed.",
    )
    db.add_all([utt1, utt2, utt3, utt4])
    await db.flush()

    # End session — should enqueue tag job
    await end_simulator_session(db, convo.id)
    await db.commit()

    # Verify tag job was enqueued
    jobs = (await db.execute(
        select(Job).where(Job.conversation_id == convo.id, Job.status == "queued")
    )).scalars().all()
    tag_jobs = [j for j in jobs if j.kind == "tag"]
    assert len(tag_jobs) == 1, "Expected exactly one tag job"

    # Run tag handler
    tag_job = tag_jobs[0]
    tag_job.status = "running"
    await db.flush()
    await handle_tag(db, tag_job, settings)
    tag_job.status = "done"
    await db.commit()

    # Verify analyze job was enqueued by tag handler
    analyze_jobs = (await db.execute(
        select(Job).where(
            Job.conversation_id == convo.id,
            Job.kind == "analyze",
            Job.status == "queued",
        )
    )).scalars().all()
    assert len(analyze_jobs) == 1, "Tag handler should enqueue analyze job"

    # Verify NO hypothesis_link job was enqueued (simulated conversation excluded)
    hyp_link_jobs = (await db.execute(
        select(Job).where(
            Job.conversation_id == convo.id,
            Job.kind == "hypothesis_link",
        )
    )).scalars().all()
    assert len(hyp_link_jobs) == 0, "Simulated conversations should NOT get hypothesis_link jobs"

    # Run analyze handler
    analyze_job = analyze_jobs[0]
    analyze_job.status = "running"
    await db.flush()
    await handle_analyze(db, analyze_job, settings)
    analyze_job.status = "done"
    await db.commit()

    # Verify analysis with critique was created
    analyses = (await db.execute(
        select(Analysis).where(
            Analysis.conversation_id == convo.id,
            Analysis.kind == "conversation",
        )
    )).scalars().all()
    assert len(analyses) == 1, "Analyze handler should create conversation analysis"

    analysis = analyses[0]
    result = analysis.result
    assert result is not None
    # FakeLLMClient returns a default AnalystOutput with score
    assert "mom_test_critique" in result
    assert "score" in result["mom_test_critique"]

    # Verify conversation is marked ready after analysis
    await db.refresh(convo)
    assert convo.status == "ready"

    # Verify the conversation is still simulated (not leaked into corpus)
    assert convo.source == "simulator"
    assert convo.meta.get("simulated") is True


@pytest.mark.asyncio
async def test_simulator_exclusion_from_explore_highlights(auth_client, seeded_db):
    """Simulated conversation highlights do NOT appear in /api/highlights (Explore)."""
    # Create a simulated conversation with a highlight
    sim_convo = Conversation(
        title="Sim session", source="simulator", status="ready",
        meta={"simulated": True},
    )
    seeded_db.add(sim_convo)
    await seeded_db.flush()

    h = Highlight(
        conversation_id=sim_convo.id, tag_key="pain",
        quote="Simulated pain point", status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.commit()

    # Query explore highlights
    r = await auth_client.get("/api/highlights")
    assert r.status_code == 200
    items = r.json()["items"]

    # Ensure the simulated highlight is not in results
    sim_ids = [item["id"] for item in items if item.get("quote") == "Simulated pain point"]
    assert len(sim_ids) == 0, "Simulated highlights must be excluded from Explore"


@pytest.mark.asyncio
async def test_highlight_deletion_returns_409_when_cited(auth_client, seeded_db):
    """DELETE /api/highlights/:id returns 409 when cited by a decision."""
    from app.services.decisions import create_decision

    convo = Conversation(title="T", status="ready", source="upload")
    seeded_db.add(convo)
    await seeded_db.flush()

    h = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="Critical evidence",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.flush()

    # Cite in a decision
    await create_decision(
        seeded_db, title="Decision X", rationale_md="Because",
        evidence_highlight_ids=[h.id],
    )
    await seeded_db.commit()

    # Try to delete — should get 409
    r = await auth_client.delete(f"/api/highlights/{h.id}")
    assert r.status_code == 409
    body = r.json()["detail"]
    assert "citing_decision_ids" in body


@pytest.mark.asyncio
async def test_highlight_deletion_succeeds_when_not_cited(auth_client, seeded_db):
    """DELETE /api/highlights/:id succeeds for uncited highlights."""
    convo = Conversation(title="T", status="ready", source="upload")
    seeded_db.add(convo)
    await seeded_db.flush()

    h = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="Deletable",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.commit()

    r = await auth_client.delete(f"/api/highlights/{h.id}")
    assert r.status_code == 204
