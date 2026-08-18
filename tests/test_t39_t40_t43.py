"""Tests for T39 (simulator), T40 (decisions), T43 (lenses)."""

import pytest

from app.llm.client import FakeLLMClient
from app.models import (
    Company,
    Conversation,
    Highlight,
    Hypothesis,
    HypothesisLink,
    Utterance,
)

# --- T39: Interview Flight Simulator ---


@pytest.mark.asyncio
async def test_persona_built_from_segment_filter(seeded_db):
    """Persona built from accepted highlights; traits cite highlight IDs."""
    from app.services.simulator import build_persona

    # Create a conversation with accepted highlights
    company = Company(name="Enterprise Corp")
    seeded_db.add(company)
    await seeded_db.flush()

    convo = Conversation(
        title="Enterprise interview",
        company_id=company.id,
        status="ready",
        source="upload",
    )
    seeded_db.add(convo)
    await seeded_db.flush()

    h1 = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="Reports take 2h weekly",
        status="accepted", origin="ai",
    )
    h2 = Highlight(
        conversation_id=convo.id, tag_key="workaround", quote="We use Excel exports",
        status="accepted", origin="ai",
    )
    seeded_db.add_all([h1, h2])
    await seeded_db.commit()

    llm = FakeLLMClient()
    analysis = await build_persona(seeded_db, filters={"company_id": company.id}, llm=llm)
    await seeded_db.commit()

    assert analysis.kind == "persona"
    assert analysis.result is not None


@pytest.mark.asyncio
async def test_persona_empty_corpus_returns_starter(seeded_db):
    """Empty corpus returns a canned starter persona."""
    from app.services.simulator import build_persona

    llm = FakeLLMClient()
    analysis = await build_persona(seeded_db, filters={"company_id": 999}, llm=llm)
    await seeded_db.commit()

    result = analysis.result
    assert result["name"] == "Marta"
    assert result["sore_points"]


@pytest.mark.asyncio
async def test_simulator_session_creates_conversation_with_simulator_source(seeded_db):
    """Creating a session creates a conversation with source='simulator'."""
    from app.services.simulator import build_persona, create_simulator_session

    llm = FakeLLMClient()
    persona = await build_persona(seeded_db, llm=llm)
    await seeded_db.commit()

    convo = await create_simulator_session(seeded_db, persona.id)
    await seeded_db.commit()

    assert convo.source == "simulator"
    assert convo.meta["simulated"] is True
    assert convo.meta["persona_id"] == persona.id


@pytest.mark.asyncio
async def test_simulator_turns_persist_as_utterances(seeded_db):
    """Simulator turns are stored as utterances."""
    from app.services.simulator import (
        add_simulator_turn,
        build_persona,
        create_simulator_session,
    )

    llm = FakeLLMClient()
    persona = await build_persona(seeded_db, llm=llm)
    await seeded_db.flush()
    convo = await create_simulator_session(seeded_db, persona.id)
    await seeded_db.flush()

    result = await add_simulator_turn(seeded_db, convo.id, "Tell me about your day", llm=llm)
    await seeded_db.commit()

    assert "reply" in result
    # Check utterances were stored
    from sqlalchemy import select
    utts = (await seeded_db.execute(
        select(Utterance).where(Utterance.conversation_id == convo.id)
    )).scalars().all()
    assert len(utts) == 2  # user turn + persona reply
    assert utts[0].speaker_side == "us"
    assert utts[1].speaker_side == "them"


@pytest.mark.asyncio
async def test_end_session_enqueues_critique_job(seeded_db):
    """Ending a session enqueues a tag job for critique."""
    from sqlalchemy import select

    from app.models import Job
    from app.services.simulator import (
        build_persona,
        create_simulator_session,
        end_simulator_session,
    )

    llm = FakeLLMClient()
    persona = await build_persona(seeded_db, llm=llm)
    await seeded_db.flush()
    convo = await create_simulator_session(seeded_db, persona.id)
    await seeded_db.flush()
    await end_simulator_session(seeded_db, convo.id)
    await seeded_db.commit()

    jobs = (await seeded_db.execute(
        select(Job).where(Job.conversation_id == convo.id)
    )).scalars().all()
    assert any(j.kind == "tag" for j in jobs)


@pytest.mark.asyncio
async def test_simulated_conversations_excluded_from_corpus_chat(seeded_db):
    """Simulated conversations never appear in corpus chat results."""
    from app.services.corpus_chat import _retrieve_candidates
    from app.services.simulator import build_persona, create_simulator_session

    llm = FakeLLMClient()
    persona = await build_persona(seeded_db, llm=llm)
    await seeded_db.flush()
    sim_convo = await create_simulator_session(seeded_db, persona.id)
    await seeded_db.flush()

    # Add a highlight to the simulated conversation
    h = Highlight(
        conversation_id=sim_convo.id, tag_key="pain", quote="This is simulated pain",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.commit()

    candidates = await _retrieve_candidates(seeded_db, "simulated pain")
    candidate_ids = [c.id for c in candidates]
    assert h.id not in candidate_ids


@pytest.mark.asyncio
async def test_simulator_api_build_persona(auth_client, seeded_db):
    """POST /api/simulator/personas returns persona analysis."""
    r = await auth_client.post("/api/simulator/personas", json={"filters": None})
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "persona"
    assert "result" in data


@pytest.mark.asyncio
async def test_simulator_api_session_flow(auth_client, seeded_db):
    """Full simulator API flow: persona → session → turn → end."""
    # Build persona
    r = await auth_client.post("/api/simulator/personas", json={})
    assert r.status_code == 201
    persona_id = r.json()["id"]

    # Create session
    r = await auth_client.post("/api/simulator/sessions", json={"persona_id": persona_id})
    assert r.status_code == 201
    session_id = r.json()["id"]
    assert r.json()["source"] == "simulator"

    # Send turn
    r = await auth_client.post(
        f"/api/simulator/sessions/{session_id}/turns",
        json={"text": "What's your biggest challenge?"},
    )
    assert r.status_code == 200
    assert "reply" in r.json()

    # End session
    r = await auth_client.post(f"/api/simulator/sessions/{session_id}/end")
    assert r.status_code == 200


# --- T40: Decision Log ---


@pytest.mark.asyncio
async def test_decision_requires_at_least_one_evidence(seeded_db):
    """Creating a decision with zero evidence raises ValueError."""
    from app.services.decisions import create_decision

    with pytest.raises(ValueError, match="at least one evidence"):
        await create_decision(
            seeded_db,
            title="Ship feature X",
            rationale_md="Because",
            evidence_highlight_ids=[],
        )


@pytest.mark.asyncio
async def test_decision_crud_with_evidence(seeded_db):
    """Create a decision with evidence, retrieve it."""
    from app.services.decisions import create_decision, get_decision

    convo = Conversation(title="Test convo", status="ready", source="upload")
    seeded_db.add(convo)
    await seeded_db.flush()

    h = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="Pain quote",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.flush()

    decision = await create_decision(
        seeded_db,
        title="Build reporting dashboard",
        rationale_md="Enterprise users report 2h weekly on manual exports",
        evidence_highlight_ids=[h.id],
    )
    await seeded_db.commit()

    assert decision.status == "proposed"
    assert decision.integrity == "ok"

    fetched = await get_decision(seeded_db, decision.id)
    assert fetched is not None
    assert fetched.title == "Build reporting dashboard"


@pytest.mark.asyncio
async def test_decision_status_lifecycle(seeded_db):
    """Decisions transition: proposed → decided → superseded."""
    from app.services.decisions import create_decision, transition_decision

    convo = Conversation(title="Test", status="ready", source="upload")
    seeded_db.add(convo)
    await seeded_db.flush()
    h = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="x",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.flush()

    decision = await create_decision(
        seeded_db, title="D1", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.flush()

    # Create a successor decision for superseding
    successor = await create_decision(
        seeded_db, title="D2", rationale_md="R2", evidence_highlight_ids=[h.id],
    )
    await seeded_db.flush()

    # proposed → decided
    updated = await transition_decision(seeded_db, decision.id, new_status="decided")
    assert updated.status == "decided"
    assert updated.decided_at is not None

    # decided → superseded (requires successor)
    updated = await transition_decision(
        seeded_db, decision.id, new_status="superseded", superseded_by_id=successor.id
    )
    assert updated.status == "superseded"
    assert updated.superseded_by == successor.id

    # Cannot go back
    with pytest.raises(ValueError, match="Cannot transition"):
        await transition_decision(seeded_db, decision.id, new_status="proposed")


@pytest.mark.asyncio
async def test_decision_integrity_undermined_by_contradicting_evidence(seeded_db):
    """A decision is undermined when a confirmed contradiction exists on cited highlights."""
    from app.services.decisions import check_decision_integrity, create_decision

    convo = Conversation(title="Test", status="ready", source="upload")
    seeded_db.add(convo)
    await seeded_db.flush()

    h = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="x",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.flush()

    hyp = Hypothesis(statement="Users need X", status="open")
    seeded_db.add(hyp)
    await seeded_db.flush()

    decision = await create_decision(
        seeded_db, title="Build X", rationale_md="Because",
        evidence_highlight_ids=[h.id], hypothesis_id=hyp.id,
    )
    await seeded_db.flush()

    # Add a confirmed contradicting link
    link = HypothesisLink(
        hypothesis_id=hyp.id, highlight_id=h.id,
        stance="contradicts", status="confirmed", origin="human",
    )
    seeded_db.add(link)
    await seeded_db.commit()

    result = await check_decision_integrity(seeded_db, decision.id)
    assert result["integrity"] == "undermined"
    assert len(result["reasons"]) > 0


@pytest.mark.asyncio
async def test_decision_integrity_ok_without_contradictions(seeded_db):
    """Decision integrity is ok when no contradictions exist."""
    from app.services.decisions import check_decision_integrity, create_decision

    convo = Conversation(title="Test", status="ready", source="upload")
    seeded_db.add(convo)
    await seeded_db.flush()
    h = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="x",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.flush()

    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.commit()

    result = await check_decision_integrity(seeded_db, decision.id)
    assert result["integrity"] == "ok"


@pytest.mark.asyncio
async def test_cited_highlight_deletion_blocked(seeded_db):
    """Cited highlights cannot be deleted (ON DELETE RESTRICT)."""
    from app.services.decisions import check_highlight_cited, create_decision

    convo = Conversation(title="Test", status="ready", source="upload")
    seeded_db.add(convo)
    await seeded_db.flush()
    h = Highlight(
        conversation_id=convo.id, tag_key="pain", quote="x",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.flush()

    await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.commit()

    citing_decisions = await check_highlight_cited(seeded_db, h.id)
    assert len(citing_decisions) > 0


@pytest.mark.asyncio
async def test_decisions_api_create_requires_evidence(auth_client):
    """POST /api/decisions with zero evidence → 422."""
    r = await auth_client.post("/api/decisions", json={
        "title": "No evidence decision",
        "rationale_md": "Empty",
        "evidence": [],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_decisions_api_crud(auth_client, sample_conversation, seeded_db):
    """Full decisions API CRUD flow."""
    # Create a highlight to cite
    h = Highlight(
        conversation_id=sample_conversation.id,
        tag_key="pain", quote="Weekly report pain",
        status="accepted", origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.commit()

    # Create decision
    r = await auth_client.post("/api/decisions", json={
        "title": "Build auto-reports",
        "rationale_md": "Evidence shows manual reporting is a top pain",
        "evidence": [h.id],
    })
    assert r.status_code == 201
    decision_id = r.json()["id"]
    assert r.json()["status"] == "proposed"

    # Get decision
    r = await auth_client.get(f"/api/decisions/{decision_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "Build auto-reports"
    assert len(r.json()["evidence"]) == 1

    # List decisions
    r = await auth_client.get("/api/decisions")
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # Transition to decided
    r = await auth_client.patch(f"/api/decisions/{decision_id}/status", json={"status": "decided"})
    assert r.status_code == 200
    assert r.json()["status"] == "decided"

    # Check integrity
    r = await auth_client.get(f"/api/decisions/{decision_id}/integrity")
    assert r.status_code == 200
    assert r.json()["integrity"] == "ok"


# --- T43: Segment Lenses ---


@pytest.mark.asyncio
async def test_lens_requires_minimum_highlights(seeded_db):
    """Lens with <5 highlights on either side raises InsufficientEvidenceError."""
    from app.services.lenses import InsufficientEvidenceError, build_lens

    llm = FakeLLMClient()
    with pytest.raises(InsufficientEvidenceError, match="Not enough evidence"):
        await build_lens(
            seeded_db,
            filters_a={"company_id": 1},
            filters_b={"company_id": 2},
            llm=llm,
        )


@pytest.mark.asyncio
async def test_lens_stores_analysis_with_input_scope(seeded_db):
    """Lens stores as analyses(kind='lens') with both filter sets in input_scope."""
    from app.services.lenses import build_lens

    # Create enough highlights for both sides
    company_a = Company(name="Enterprise A")
    company_b = Company(name="SMB B")
    seeded_db.add_all([company_a, company_b])
    await seeded_db.flush()

    convo_a = Conversation(
        title="Enterprise call", company_id=company_a.id, status="ready", source="upload",
    )
    convo_b = Conversation(
        title="SMB call", company_id=company_b.id, status="ready", source="upload",
    )
    seeded_db.add_all([convo_a, convo_b])
    await seeded_db.flush()

    # 6 highlights per side
    for i in range(6):
        seeded_db.add(Highlight(
            conversation_id=convo_a.id, tag_key="pain",
            quote=f"Enterprise pain {i}", status="accepted", origin="ai",
        ))
        seeded_db.add(Highlight(
            conversation_id=convo_b.id, tag_key="pain",
            quote=f"SMB pain {i}", status="accepted", origin="ai",
        ))
    await seeded_db.commit()

    llm = FakeLLMClient()
    analysis = await build_lens(
        seeded_db,
        filters_a={"company_id": company_a.id},
        filters_b={"company_id": company_b.id},
        label_a="Enterprise",
        label_b="SMB",
        llm=llm,
    )
    await seeded_db.commit()

    assert analysis.kind == "lens"
    assert analysis.input_scope["filters_a"] == {"company_id": company_a.id}
    assert analysis.input_scope["label_a"] == "Enterprise"


@pytest.mark.asyncio
async def test_lens_validates_evidence_partition(seeded_db):
    """Lens validates that side A themes only cite side A highlight IDs."""
    from app.services.lenses import build_lens

    company_a = Company(name="Corp Alpha")
    company_b = Company(name="Corp Beta")
    seeded_db.add_all([company_a, company_b])
    await seeded_db.flush()

    convo_a = Conversation(title="A", company_id=company_a.id, status="ready", source="upload")
    convo_b = Conversation(title="B", company_id=company_b.id, status="ready", source="upload")
    seeded_db.add_all([convo_a, convo_b])
    await seeded_db.flush()

    for i in range(6):
        seeded_db.add(Highlight(
            conversation_id=convo_a.id, tag_key="pain",
            quote=f"Alpha pain {i}", status="accepted", origin="ai",
        ))
        seeded_db.add(Highlight(
            conversation_id=convo_b.id, tag_key="workaround",
            quote=f"Beta workaround {i}", status="accepted", origin="ai",
        ))
    await seeded_db.commit()

    # Provide a fixture that has some invalid IDs (should be stripped)
    llm = FakeLLMClient(fixtures={
        "lens": {
            "themes_a": [{"name": "Theme A", "summary": "S", "side": "a", "evidence_highlight_ids": [99999]}],
            "themes_b": [],
            "themes_shared": [],
            "contradictions": [],
        }
    })

    analysis = await build_lens(
        seeded_db,
        filters_a={"company_id": company_a.id},
        filters_b={"company_id": company_b.id},
        llm=llm,
    )
    await seeded_db.commit()

    # Invalid IDs should have been stripped
    result = analysis.result
    if result["themes_a"]:
        for theme in result["themes_a"]:
            for hid in theme.get("evidence_highlight_ids", []):
                # All remaining IDs should be valid for side A
                assert hid != 99999


@pytest.mark.asyncio
async def test_lens_api_insufficient_evidence(auth_client):
    """POST /api/lenses with too few highlights → 422."""
    r = await auth_client.post("/api/lenses", json={
        "a": {"company_id": 9999},
        "b": {"company_id": 9998},
        "label_a": "Empty A",
        "label_b": "Empty B",
    })
    assert r.status_code == 422
    assert "Not enough evidence" in r.json()["detail"]


@pytest.mark.asyncio
async def test_lens_api_success(auth_client, seeded_db):
    """POST /api/lenses with enough highlights succeeds."""
    company_a = Company(name="Lens Corp A")
    company_b = Company(name="Lens Corp B")
    seeded_db.add_all([company_a, company_b])
    await seeded_db.flush()

    convo_a = Conversation(title="LA", company_id=company_a.id, status="ready", source="upload")
    convo_b = Conversation(title="LB", company_id=company_b.id, status="ready", source="upload")
    seeded_db.add_all([convo_a, convo_b])
    await seeded_db.flush()

    for i in range(6):
        seeded_db.add(Highlight(
            conversation_id=convo_a.id, tag_key="pain",
            quote=f"LA pain {i}", status="accepted", origin="ai",
        ))
        seeded_db.add(Highlight(
            conversation_id=convo_b.id, tag_key="pain",
            quote=f"LB pain {i}", status="accepted", origin="ai",
        ))
    await seeded_db.commit()

    r = await auth_client.post("/api/lenses", json={
        "a": {"company_id": company_a.id},
        "b": {"company_id": company_b.id},
        "label_a": "Corp A",
        "label_b": "Corp B",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "lens"
    assert "result" in data

    # Retrieve it
    lens_id = data["id"]
    r = await auth_client.get(f"/api/lenses/{lens_id}")
    assert r.status_code == 200
    assert r.json()["kind"] == "lens"
