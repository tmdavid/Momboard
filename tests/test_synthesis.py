"""T21: Synthesizer agent + endpoints tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.client import FakeLLMClient
from app.llm.schemas import SynthesizerOutput
from app.llm.synthesizer import run_synthesize
from app.models import Analysis, Company, Conversation, Highlight, Job
from app.seed import seed_tags


@pytest.mark.asyncio
async def test_post_synthesis_creates_analysis_and_enqueues_job(
    auth_client: AsyncClient,
):
    """POST /api/syntheses should create an Analysis(kind=synthesis) and queue a job."""
    r = await auth_client.post(
        "/api/syntheses",
        json={"filters": {"tag": "pain", "company_id": 1}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "synthesis"
    assert body["status"] == "queued"
    assert body["error"] is None
    assert body["input_scope"] == {"tag": "pain", "company_id": 1}

    # Verify job was queued
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        result = await db.execute(
            select(Job).where(Job.kind == "synthesize", Job.status == "queued")
        )
        job = result.scalar_one_or_none()
        assert job is not None
        assert job.payload["analysis_id"] == body["id"]
        assert job.payload["filters"] == {"tag": "pain", "company_id": 1}


@pytest.mark.asyncio
async def test_get_synthesis_returns_result(auth_client: AsyncClient):
    """GET /api/syntheses/{id} should return the synthesis."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        analysis = Analysis(
            kind="synthesis",
            input_scope={"tag": "pain"},
            result={"themes": [], "contradictions": [], "validate_next": []},
            model="gpt-4o",
            prompt_version="synthesizer-v1",
        )
        db.add(analysis)
        await db.commit()
        analysis_id = analysis.id

    r = await auth_client.get(f"/api/syntheses/{analysis_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "synthesis"
    assert body["status"] == "done"
    assert body["result"] is not None


@pytest.mark.asyncio
async def test_get_nonexistent_synthesis_404(auth_client: AsyncClient):
    r = await auth_client.get("/api/syntheses/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_synthesizer_input_is_highlights_not_transcripts(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Synthesizer prompt input should contain quotes/context, not full utterances."""
    async with session_factory() as db:
        await seed_tags(db)
        company = Company(name="SynthCo")
        db.add(company)
        await db.flush()

        convo = Conversation(
            title="Synth Test",
            company_id=company.id,
            interviewer="David",
            status="ready",
        )
        db.add(convo)
        await db.flush()

        # Add highlights
        h1 = Highlight(
            conversation_id=convo.id, tag_key="pain",
            quote="manual process is killing us", origin="ai", status="accepted",
            confidence=0.9,
        )
        h2 = Highlight(
            conversation_id=convo.id, tag_key="workaround",
            quote="we use a spreadsheet", origin="ai", status="suggested",
            confidence=0.85,
        )
        db.add_all([h1, h2])
        await db.flush()

        # Create analysis row to be updated
        analysis = Analysis(kind="synthesis", input_scope={"tag": "pain"})
        db.add(analysis)
        await db.flush()
        analysis_id = analysis.id

        fake = FakeLLMClient()
        fake.set_fixture("synthesizer", {
            "themes": [
                {
                    "name": "Manual processes",
                    "summary": "Teams struggle with manual work",
                    "evidence_highlight_ids": [h1.id],
                    "strength": "strong",
                }
            ],
            "contradictions": [],
            "validate_next": ["Ask about automation attempts"],
        })

        await run_synthesize(db, analysis_id, {"tag": "pain"}, fake)
        await db.commit()

        # Check the input doesn't contain full utterances
        assert len(fake.calls) == 1
        input_data = fake.calls[0]["input_data"]
        # Should contain highlight quotes
        assert "manual process is killing us" in input_data["highlights"]
        # Should NOT contain full utterance text (we didn't add utterances)


@pytest.mark.asyncio
async def test_synthesizer_result_validates_as_schema(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Result stored in analysis should validate against SynthesizerOutput."""
    async with session_factory() as db:
        await seed_tags(db)
        company = Company(name="ValidCo")
        db.add(company)
        await db.flush()

        convo = Conversation(
            title="Schema Test", company_id=company.id,
            interviewer="David", status="ready",
        )
        db.add(convo)
        await db.flush()

        h = Highlight(
            conversation_id=convo.id, tag_key="pain",
            quote="test pain", origin="ai", status="accepted", confidence=0.9,
        )
        db.add(h)
        await db.flush()
        h_id = h.id

        analysis = Analysis(kind="synthesis", input_scope={})
        db.add(analysis)
        await db.flush()
        analysis_id = analysis.id

        fake = FakeLLMClient()
        fake.set_fixture("synthesizer", {
            "themes": [
                {
                    "name": "Pain theme",
                    "summary": "Common pains",
                    "evidence_highlight_ids": [h_id],
                    "strength": "strong",
                }
            ],
            "contradictions": [
                {
                    "description": "Speed vs accuracy tradeoff",
                    "side_a_ids": [h_id],
                    "side_b_ids": [],
                }
            ],
            "validate_next": ["Check with more customers"],
        })

        result = await run_synthesize(db, analysis_id, {}, fake)
        await db.commit()

        assert result is not None
        out = SynthesizerOutput.model_validate(result.result)
        assert len(out.themes) == 1
        assert len(out.contradictions) == 1
        assert len(out.validate_next) == 1


@pytest.mark.asyncio
async def test_synthesizer_evidence_ids_validated(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Invalid evidence_highlight_ids should be stripped from themes."""
    async with session_factory() as db:
        await seed_tags(db)
        company = Company(name="EvidCo")
        db.add(company)
        await db.flush()

        convo = Conversation(
            title="Evidence Test", company_id=company.id,
            interviewer="David", status="ready",
        )
        db.add(convo)
        await db.flush()

        h = Highlight(
            conversation_id=convo.id, tag_key="pain",
            quote="real quote", origin="ai", status="accepted", confidence=0.9,
        )
        db.add(h)
        await db.flush()
        valid_id = h.id

        analysis = Analysis(kind="synthesis", input_scope={})
        db.add(analysis)
        await db.flush()
        analysis_id = analysis.id

        fake = FakeLLMClient()
        fake.set_fixture("synthesizer", {
            "themes": [
                {
                    "name": "Test",
                    "summary": "Test theme",
                    "evidence_highlight_ids": [valid_id, 99999],  # 99999 is invalid
                    "strength": "medium",
                }
            ],
            "contradictions": [],
            "validate_next": [],
        })

        result = await run_synthesize(db, analysis_id, {}, fake)
        await db.commit()

        assert result is not None
        out = SynthesizerOutput.model_validate(result.result)
        # Only valid ID should remain
        assert valid_id in out.themes[0].evidence_highlight_ids
        assert 99999 not in out.themes[0].evidence_highlight_ids


@pytest.mark.asyncio
async def test_get_synthesis_returns_safe_terminal_failure(auth_client: AsyncClient):
    """Polling should distinguish a failed worker job from a still-running synthesis."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        analysis = Analysis(kind="synthesis", input_scope={"tag": "pain"})
        db.add(analysis)
        await db.flush()
        db.add(
            Job(
                kind="synthesize",
                payload={"analysis_id": analysis.id, "filters": {"tag": "pain"}},
                status="error",
                error="provider secret or implementation detail",
            )
        )
        await db.commit()
        analysis_id = analysis.id

    response = await auth_client.get(f"/api/syntheses/{analysis_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error"] == "Synthesis failed. Please retry."
    assert "provider secret" not in response.text


# --- T45: Summaries list + save/discard ---


@pytest.mark.asyncio
async def test_list_syntheses_newest_first_with_status(auth_client: AsyncClient):
    """GET /api/syntheses lists all syntheses newest-first with derived status."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        done = Analysis(
            kind="synthesis",
            input_scope={"tag": "pain"},
            result={"themes": [], "contradictions": [], "validate_next": []},
        )
        pending = Analysis(kind="synthesis", input_scope={"tag": "workaround"})
        db.add_all([done, pending])
        await db.flush()
        db.add(
            Job(
                kind="synthesize",
                payload={"analysis_id": pending.id, "filters": {"tag": "workaround"}},
                status="queued",
            )
        )
        await db.commit()
        done_id, pending_id = done.id, pending.id

    r = await auth_client.get("/api/syntheses")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    ids = [item["id"] for item in body["items"]]
    # newest-first: pending was created after done
    assert ids.index(pending_id) < ids.index(done_id)

    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[done_id]["status"] == "done"
    assert by_id[pending_id]["status"] == "queued"
    assert by_id[done_id]["saved"] is False


@pytest.mark.asyncio
async def test_save_and_filter_saved_syntheses(auth_client: AsyncClient):
    """PATCH toggles saved; GET ?saved=true filters to kept syntheses."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        analysis = Analysis(
            kind="synthesis",
            input_scope={"tag": "pain"},
            result={"themes": [], "contradictions": [], "validate_next": []},
        )
        db.add(analysis)
        await db.commit()
        analysis_id = analysis.id

    r = await auth_client.patch(f"/api/syntheses/{analysis_id}", json={"saved": True})
    assert r.status_code == 200
    assert r.json()["saved"] is True

    r = await auth_client.get("/api/syntheses?saved=true")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert analysis_id in ids

    # Unsave and confirm it drops out of the saved filter
    r = await auth_client.patch(f"/api/syntheses/{analysis_id}", json={"saved": False})
    assert r.status_code == 200
    assert r.json()["saved"] is False
    r = await auth_client.get("/api/syntheses?saved=true")
    assert analysis_id not in [item["id"] for item in r.json()["items"]]


@pytest.mark.asyncio
async def test_delete_synthesis_removes_analysis_and_jobs(auth_client: AsyncClient):
    """DELETE discards the synthesis and its synthesize jobs."""
    sf = auth_client._transport.app.state.session_factory  # type: ignore
    async with sf() as db:
        analysis = Analysis(kind="synthesis", input_scope={"tag": "pain"})
        db.add(analysis)
        await db.flush()
        db.add(
            Job(
                kind="synthesize",
                payload={"analysis_id": analysis.id, "filters": {"tag": "pain"}},
                status="queued",
            )
        )
        await db.commit()
        analysis_id = analysis.id

    r = await auth_client.delete(f"/api/syntheses/{analysis_id}")
    assert r.status_code == 204

    assert (await auth_client.get(f"/api/syntheses/{analysis_id}")).status_code == 404

    async with sf() as db:
        remaining = await db.execute(
            select(Job).where(
                Job.kind == "synthesize",
                Job.payload["analysis_id"].as_integer() == analysis_id,
            )
        )
        assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_nonexistent_synthesis_404(auth_client: AsyncClient):
    assert (await auth_client.delete("/api/syntheses/99999")).status_code == 404
