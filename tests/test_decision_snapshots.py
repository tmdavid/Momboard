"""Decisions PRD P0 slice 1: evidence snapshots + integrity_checked_at + list shape."""
import pytest
from sqlalchemy import delete

from app.models import Company, Conversation, Decision, DecisionEvidence, Highlight


async def _convo_with_highlight(db, *, company_name="Acme Co", quote="Six hours every Monday"):
    company = Company(name=company_name)
    db.add(company)
    await db.flush()
    convo = Conversation(title="Discovery call", status="ready", source="upload", company_id=company.id)
    db.add(convo)
    await db.flush()
    h = Highlight(conversation_id=convo.id, tag_key="pain", quote=quote, status="accepted", origin="ai")
    db.add(h)
    await db.flush()
    return convo, h, company


@pytest.mark.asyncio
async def test_create_decision_captures_evidence_snapshot(seeded_db):
    """Creating a decision snapshots the quote/company/convo on each receipt."""
    from app.services.decisions import create_decision

    convo, h, company = await _convo_with_highlight(seeded_db)
    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.commit()

    from sqlalchemy import select
    rows = (await seeded_db.execute(
        select(DecisionEvidence).where(DecisionEvidence.decision_id == decision.id)
    )).scalars().all()
    assert len(rows) == 1
    r = rows[0]
    assert r.quote_snapshot == "Six hours every Monday"
    assert r.company_name == "Acme Co"
    assert r.conversation_id == convo.id
    assert r.cited_at is not None
    assert r.invalid_reason is None


@pytest.mark.asyncio
async def test_receipt_survives_highlight_change(seeded_db):
    """A receipt still shows its snapshot quote after the live highlight's quote changes."""
    from app.services.decisions import create_decision, get_decision_evidence

    _convo, h, _company = await _convo_with_highlight(seeded_db, quote="Original quote")
    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.flush()

    # Simulate a Retag mutating the live highlight.
    h.quote = "REPLACED by retag"
    await seeded_db.flush()

    evidence = await get_decision_evidence(seeded_db, decision.id)
    assert len(evidence) == 1
    # Receipt is served from the snapshot, not the mutated live highlight.
    assert evidence[0]["quote"] == "Original quote"
    assert evidence[0]["company_name"] == "Acme Co"


@pytest.mark.asyncio
async def test_receipt_survives_highlight_deletion(seeded_db):
    """Deleting the cited highlight (SET NULL) leaves the receipt readable from snapshot."""
    from app.services.decisions import create_decision, get_decision_evidence

    _convo, h, _company = await _convo_with_highlight(seeded_db, quote="Kept quote")
    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.flush()

    await seeded_db.execute(delete(Highlight).where(Highlight.id == h.id))
    await seeded_db.flush()

    evidence = await get_decision_evidence(seeded_db, decision.id)
    assert len(evidence) == 1
    assert evidence[0]["quote"] == "Kept quote"
    assert evidence[0]["highlight_id"] is None
    assert evidence[0]["status"] == "deleted"


@pytest.mark.asyncio
async def test_integrity_check_sets_checked_at(seeded_db):
    """Running the integrity check stamps integrity_checked_at and returns it."""
    from app.services.decisions import check_decision_integrity, create_decision

    _convo, h, _company = await _convo_with_highlight(seeded_db)
    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.flush()
    assert decision.integrity_checked_at is None

    result = await check_decision_integrity(seeded_db, decision.id)
    assert result["integrity"] == "ok"
    assert result["integrity_checked_at"] is not None
    assert decision.integrity_checked_at is not None


@pytest.mark.asyncio
async def test_list_returns_integrity_and_checked_at(auth_client, seeded_db):
    """GET /api/decisions returns integrity + integrity_checked_at per row (no per-row call)."""
    from app.services.decisions import check_decision_integrity, create_decision

    _convo, h, _company = await _convo_with_highlight(seeded_db)
    decision = await create_decision(
        seeded_db, title="Listed decision", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await check_decision_integrity(seeded_db, decision.id)
    await seeded_db.commit()

    resp = await auth_client.get("/api/decisions")
    assert resp.status_code == 200
    body = resp.json()
    row = next(r for r in body["items"] if r["id"] == decision.id)
    assert row["integrity"] == "ok"
    assert row["integrity_checked_at"] is not None
    assert row["status"] == "proposed"


@pytest.mark.asyncio
async def test_rejecting_cited_highlight_tag_undermines_decision(auth_client, seeded_db):
    """PATCH a cited highlight to status=rejected flags the receipt + undermines the decision."""
    from app.services.decisions import create_decision

    _convo, h, _company = await _convo_with_highlight(seeded_db, quote="Rejectable")
    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.commit()

    resp = await auth_client.patch(f"/api/highlights/{h.id}", json={"status": "rejected"})
    assert resp.status_code == 200

    # Assert through the API (avoids cross-session lazy-load on the in-memory DB).
    detail = (await auth_client.get(f"/api/decisions/{decision.id}")).json()
    assert detail["evidence"][0]["invalid_reason"] == "tag_rejected"
    assert detail["integrity"] == "undermined"


@pytest.mark.asyncio
async def test_deleting_cited_conversation_undermines_decision(seeded_db):
    """Deleting a conversation flags receipts snapshotting it (via the service hook)."""
    from app.services.decisions import (
        create_decision,
        get_decision_evidence,
        invalidate_decision_evidence_for_conversation,
    )

    convo, h, _company = await _convo_with_highlight(seeded_db, quote="Conv quote")
    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.flush()

    affected = await invalidate_decision_evidence_for_conversation(seeded_db, convo.id)
    assert decision.id in affected

    evidence = await get_decision_evidence(seeded_db, decision.id)
    assert evidence[0]["invalid_reason"] == "conversation_deleted"
    # Snapshot still readable after the receipt is flagged.
    assert evidence[0]["quote"] == "Conv quote"
    from sqlalchemy import select
    integ = (await seeded_db.execute(select(Decision.integrity).where(Decision.id == decision.id))).scalar_one()
    assert integ == "undermined"


@pytest.mark.asyncio
async def test_invalidation_is_idempotent(seeded_db):
    """Re-flagging the same receipt with the same reason doesn't duplicate reasons."""
    from app.services.decisions import (
        INVALID_TAG_REJECTED,
        check_decision_integrity,
        create_decision,
        invalidate_decision_evidence_for_highlights,
    )

    _convo, h, _company = await _convo_with_highlight(seeded_db)
    decision = await create_decision(
        seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id],
    )
    await seeded_db.flush()

    await invalidate_decision_evidence_for_highlights(seeded_db, [h.id], reason=INVALID_TAG_REJECTED)
    await invalidate_decision_evidence_for_highlights(seeded_db, [h.id], reason=INVALID_TAG_REJECTED)
    result = await check_decision_integrity(seeded_db, decision.id)
    # One receipt → exactly one invalidation reason, not two.
    tag_reasons = [r for r in result["reasons"] if r["source_type"] == "tag_rejected"]
    assert len(tag_reasons) == 1
