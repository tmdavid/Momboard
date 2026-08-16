"""T12: Analyst agent tests."""

import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.analyst import run_analyze
from app.llm.client import FakeLLMClient
from app.llm.schemas import AnalystOutput
from app.models import Conversation, Highlight, Utterance
from app.seed import seed_tags


@pytest.mark.asyncio
async def test_analysis_row_created_with_expected_shape(
    session_factory: async_sessionmaker[AsyncSession],
):
    """run_analyze should create an Analysis row with result matching AnalystOutput schema."""
    async with session_factory() as db:
        await seed_tags(db)
        convo = Conversation(title="Test Analysis", interviewer="David", status="processing")
        db.add(convo)
        await db.flush()

        # Add utterances
        for i, (speaker, side, text) in enumerate([
            ("David", "us", "How do you handle monitoring today?"),
            ("Maria", "them", "We use a spreadsheet and it takes forever"),
            ("David", "us", "What have you tried to fix it?"),
            ("Maria", "them", "We tried a freelancer but accuracy dropped"),
        ]):
            db.add(Utterance(
                conversation_id=convo.id, idx=i,
                speaker_label=speaker, speaker_side=side, text=text,
            ))
        await db.flush()

        # Add some highlights
        h1 = Highlight(
            conversation_id=convo.id, tag_key="pain",
            quote="it takes forever", origin="ai", status="suggested", confidence=0.9,
        )
        h2 = Highlight(
            conversation_id=convo.id, tag_key="workaround",
            quote="We tried a freelancer", origin="ai", status="accepted", confidence=0.88,
        )
        db.add_all([h1, h2])
        await db.flush()
        convo_id = convo.id

        fake = FakeLLMClient()
        fake.set_fixture("analyst", {
            "summary": "Customer uses manual spreadsheet-based process.",
            "top_pains": [
                {"pain": "Manual process too slow", "evidence_highlight_ids": [h1.id, h2.id], "severity": "high"}
            ],
            "commitments": [],
            "compliment_ratio": 0.0,
            "mom_test_critique": {
                "score": 7,
                "good_questions": ["Asked about current process"],
                "violations": [],
            },
            "suggested_followups": ["Ask about budget"],
            "open_questions": ["How many people on the team?"],
        })

        analysis = await run_analyze(db, convo_id, fake)
        await db.commit()

        assert analysis is not None
        assert analysis.kind == "conversation"
        assert analysis.prompt_version is not None
        assert analysis.model is not None

        # Validate stored JSON against schema
        out = AnalystOutput.model_validate(analysis.result)
        assert 0 <= out.mom_test_critique.score <= 10
        assert len(out.top_pains) >= 1


@pytest.mark.asyncio
async def test_analyst_input_includes_only_non_rejected_highlights(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Rejected highlights should NOT be passed to the analyst."""
    async with session_factory() as db:
        await seed_tags(db)
        convo = Conversation(title="Test", interviewer="David", status="processing")
        db.add(convo)
        await db.flush()
        db.add(Utterance(
            conversation_id=convo.id, idx=0,
            speaker_label="Maria", speaker_side="them", text="test",
        ))
        await db.flush()

        # One accepted, one rejected
        h_accepted = Highlight(
            conversation_id=convo.id, tag_key="pain",
            quote="accepted quote", origin="ai", status="accepted", confidence=0.9,
        )
        h_rejected = Highlight(
            conversation_id=convo.id, tag_key="compliment",
            quote="rejected quote", origin="ai", status="rejected", confidence=0.5,
        )
        db.add_all([h_accepted, h_rejected])
        await db.flush()
        convo_id = convo.id

        fake = FakeLLMClient()
        fake.set_fixture("analyst", {
            "summary": "test",
            "top_pains": [],
            "commitments": [],
            "compliment_ratio": 0.0,
            "mom_test_critique": {"score": 5, "good_questions": [], "violations": []},
            "suggested_followups": [],
            "open_questions": [],
        })

        await run_analyze(db, convo_id, fake)
        await db.commit()

        # Check the input sent to the fake LLM
        assert len(fake.calls) == 1
        input_data = fake.calls[0]["input_data"]
        assert "accepted quote" in input_data["highlights"]
        assert "rejected quote" not in input_data["highlights"]


@pytest.mark.asyncio
async def test_evidence_highlight_ids_with_invalid_ids_stripped(
    session_factory: async_sessionmaker[AsyncSession], caplog,
):
    """Non-existent highlight IDs in evidence should be stripped, not crash."""
    async with session_factory() as db:
        await seed_tags(db)
        convo = Conversation(title="Test", interviewer="David", status="processing")
        db.add(convo)
        await db.flush()
        db.add(Utterance(
            conversation_id=convo.id, idx=0,
            speaker_label="Maria", speaker_side="them", text="test",
        ))
        await db.flush()

        h = Highlight(
            conversation_id=convo.id, tag_key="pain",
            quote="real quote", origin="ai", status="suggested", confidence=0.9,
        )
        db.add(h)
        await db.flush()
        convo_id = convo.id
        valid_id = h.id

        fake = FakeLLMClient()
        fake.set_fixture("analyst", {
            "summary": "test",
            "top_pains": [
                {"pain": "test pain", "evidence_highlight_ids": [valid_id, 99999], "severity": "high"}
            ],
            "commitments": [],
            "compliment_ratio": 0.0,
            "mom_test_critique": {"score": 5, "good_questions": [], "violations": []},
            "suggested_followups": [],
            "open_questions": [],
        })

        with caplog.at_level(logging.WARNING):
            analysis = await run_analyze(db, convo_id, fake)
        await db.commit()

        assert analysis is not None
        out = AnalystOutput.model_validate(analysis.result)
        # Only the valid ID should remain
        assert valid_id in out.top_pains[0].evidence_highlight_ids
        assert 99999 not in out.top_pains[0].evidence_highlight_ids
