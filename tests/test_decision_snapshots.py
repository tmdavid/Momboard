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


# --- P1: edit, evidence add/remove, draft, enrichment ----------------------


@pytest.mark.asyncio
async def test_patch_decision_edits_title_rationale_owner_area(auth_client, seeded_db):
    from app.services.decisions import create_decision

    _convo, h, _company = await _convo_with_highlight(seeded_db)
    d = await create_decision(seeded_db, title="Old", rationale_md="Old R", evidence_highlight_ids=[h.id])
    await seeded_db.commit()

    resp = await auth_client.patch(
        f"/api/decisions/{d.id}",
        json={"title": "New title", "rationale_md": "New rationale", "owner_id": 7, "area": "Pricing"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "New title"
    assert body["rationale_md"] == "New rationale"
    assert body["owner_id"] == 7
    assert body["area"] == "Pricing"


@pytest.mark.asyncio
async def test_add_and_remove_evidence(auth_client, seeded_db):
    from app.models import Highlight
    from app.services.decisions import create_decision

    convo, h1, _c = await _convo_with_highlight(seeded_db, quote="First")
    h2 = Highlight(conversation_id=convo.id, tag_key="money", quote="Second", status="accepted", origin="ai")
    seeded_db.add(h2)
    await seeded_db.flush()
    d = await create_decision(seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h1.id])
    await seeded_db.commit()

    # Add a second receipt (snapshots the quote).
    resp = await auth_client.post(f"/api/decisions/{d.id}/evidence/{h2.id}")
    assert resp.status_code == 201
    body = resp.json()
    quotes = {e["quote"] for e in body["evidence"]}
    assert quotes == {"First", "Second"}

    # Remove it again.
    resp = await auth_client.delete(f"/api/decisions/{d.id}/evidence/{h2.id}")
    assert resp.status_code == 200
    assert {e["quote"] for e in resp.json()["evidence"]} == {"First"}


@pytest.mark.asyncio
async def test_cannot_remove_last_evidence_from_nondraft(auth_client, seeded_db):
    from app.services.decisions import create_decision

    _convo, h, _c = await _convo_with_highlight(seeded_db)
    d = await create_decision(seeded_db, title="D", rationale_md="R", evidence_highlight_ids=[h.id])
    await seeded_db.commit()

    resp = await auth_client.delete(f"/api/decisions/{d.id}/evidence/{h.id}")
    assert resp.status_code == 422
    assert "at least one" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_draft_decision_allows_zero_evidence_then_transitions(auth_client, seeded_db):
    from app.services.decisions import create_decision

    d = await create_decision(seeded_db, title="Draft D", rationale_md="R", evidence_highlight_ids=[], status="draft")
    await seeded_db.commit()
    assert d.status == "draft"

    # draft -> proposed
    resp = await auth_client.patch(f"/api/decisions/{d.id}/status", json={"status": "proposed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "proposed"


@pytest.mark.asyncio
async def test_detail_returns_linked_hypothesis_and_superseded_title(auth_client, seeded_db):
    from app.models import Hypothesis
    from app.services.decisions import create_decision, transition_decision

    _convo, h, _c = await _convo_with_highlight(seeded_db)
    hyp = Hypothesis(statement="Mid-market teams want SSO", status="open", origin="human")
    seeded_db.add(hyp)
    await seeded_db.flush()

    d1 = await create_decision(seeded_db, title="D1", rationale_md="R", evidence_highlight_ids=[h.id], hypothesis_id=hyp.id)
    d2 = await create_decision(seeded_db, title="Successor D2", rationale_md="R2", evidence_highlight_ids=[h.id])
    await seeded_db.flush()
    await transition_decision(seeded_db, d1.id, new_status="decided")
    await transition_decision(seeded_db, d1.id, new_status="superseded", superseded_by_id=d2.id)
    await seeded_db.commit()

    body = (await auth_client.get(f"/api/decisions/{d1.id}")).json()
    assert body["hypothesis"]["statement"] == "Mid-market teams want SSO"
    assert body["hypothesis"]["band"] == "hunch"  # hypothesis has no links yet
    assert body["superseded_by_title"] == "Successor D2"


# --- P2: search + sort -----------------------------------------------------


@pytest.mark.asyncio
async def test_list_q_searches_title_and_rationale(auth_client, seeded_db):
    from app.services.decisions import create_decision

    _convo, h, _c = await _convo_with_highlight(seeded_db)
    await create_decision(seeded_db, title="Pricing pilot", rationale_md="annual lock-in", evidence_highlight_ids=[h.id])
    await create_decision(seeded_db, title="Reporting dashboard", rationale_md="weekly email", evidence_highlight_ids=[h.id])
    await seeded_db.commit()

    # Match on title
    r = await auth_client.get("/api/decisions", params={"q": "pricing"})
    titles = [d["title"] for d in r.json()["items"]]
    assert "Pricing pilot" in titles and "Reporting dashboard" not in titles

    # Match on rationale
    r = await auth_client.get("/api/decisions", params={"q": "weekly"})
    titles = [d["title"] for d in r.json()["items"]]
    assert titles == ["Reporting dashboard"]


@pytest.mark.asyncio
async def test_list_sort_date_asc_and_desc(auth_client, seeded_db):
    from app.services.decisions import create_decision

    _convo, h, _c = await _convo_with_highlight(seeded_db)
    first = await create_decision(seeded_db, title="First", rationale_md="R", evidence_highlight_ids=[h.id])
    await seeded_db.flush()
    second = await create_decision(seeded_db, title="Second", rationale_md="R", evidence_highlight_ids=[h.id])
    await seeded_db.commit()

    desc = [d["id"] for d in (await auth_client.get("/api/decisions", params={"sort": "date_desc"})).json()["items"]]
    asc = [d["id"] for d in (await auth_client.get("/api/decisions", params={"sort": "date_asc"})).json()["items"]]
    assert desc.index(second.id) < desc.index(first.id)
    assert asc.index(first.id) < asc.index(second.id)


@pytest.mark.asyncio
async def test_list_sort_integrity_puts_undermined_first(auth_client, seeded_db):
    from app.services.decisions import (
        INVALID_TAG_REJECTED,
        create_decision,
        invalidate_decision_evidence_for_highlights,
    )

    _convo, h1, _c = await _convo_with_highlight(seeded_db, quote="ok one")
    ok = await create_decision(seeded_db, title="Healthy", rationale_md="R", evidence_highlight_ids=[h1.id])
    _convo2, h2, _c2 = await _convo_with_highlight(seeded_db, company_name="Beta", quote="bad one")
    bad = await create_decision(seeded_db, title="Undermined one", rationale_md="R", evidence_highlight_ids=[h2.id])
    await seeded_db.flush()
    await invalidate_decision_evidence_for_highlights(seeded_db, [h2.id], reason=INVALID_TAG_REJECTED)
    await seeded_db.commit()

    ids = [d["id"] for d in (await auth_client.get("/api/decisions", params={"sort": "integrity"})).json()["items"]]
    assert ids.index(bad.id) < ids.index(ok.id)


# --- v0.4 gaps: list fields, archived-hypothesis flag, teammates ---------------


async def _decision_with_hypothesis(seeded_db, *, status="open"):
    from app.models import Hypothesis
    from app.services.decisions import create_decision

    _convo, h, _company = await _convo_with_highlight(seeded_db, quote="Cites a belief")
    hyp = Hypothesis(statement="Archive flagging works on decisions ok", status=status, origin="human")
    seeded_db.add(hyp)
    await seeded_db.flush()
    decision = await create_decision(
        seeded_db, title="Cites hypothesis", rationale_md="R",
        evidence_highlight_ids=[h.id], hypothesis_id=hyp.id,
    )
    await seeded_db.commit()
    return decision.id, hyp.id


@pytest.mark.asyncio
async def test_list_includes_evidence_count_and_hypothesis_ref(auth_client, seeded_db):
    decision_id, hyp_id = await _decision_with_hypothesis(seeded_db)
    items = (await auth_client.get("/api/decisions")).json()["items"]
    item = next(i for i in items if i["id"] == decision_id)
    assert item["evidence_count"] == 1
    assert item["hypothesis_id"] == hyp_id
    assert item["hypothesis_archived"] is False


@pytest.mark.asyncio
async def test_archiving_the_cited_hypothesis_flags_the_decision_but_does_not_undermine_it(
    auth_client, seeded_db
):
    decision_id, hyp_id = await _decision_with_hypothesis(seeded_db)
    r = await auth_client.patch(f"/api/hypotheses/{hyp_id}", json={"status": "archived"})
    assert r.status_code == 200

    items = (await auth_client.get("/api/decisions")).json()["items"]
    item = next(i for i in items if i["id"] == decision_id)
    assert item["hypothesis_archived"] is True
    assert item["integrity"] != "undermined"  # a flag, not a broken receipt

    detail = (await auth_client.get(f"/api/decisions/{decision_id}")).json()
    assert detail["hypothesis"]["archived"] is True
    assert detail["integrity"] != "undermined"

    # Restoring the hypothesis clears the flag again.
    await auth_client.patch(f"/api/hypotheses/{hyp_id}", json={"status": "open"})
    detail = (await auth_client.get(f"/api/decisions/{decision_id}")).json()
    assert detail["hypothesis"]["archived"] is False


@pytest.mark.asyncio
async def test_decision_without_hypothesis_is_not_flagged(auth_client, seeded_db):
    from app.services.decisions import create_decision

    _c, h, _co = await _convo_with_highlight(seeded_db, quote="No belief attached")
    d = await create_decision(seeded_db, title="Plain", rationale_md="R", evidence_highlight_ids=[h.id])
    await seeded_db.commit()
    item = next(i for i in (await auth_client.get("/api/decisions")).json()["items"] if i["id"] == d.id)
    assert item["hypothesis_id"] is None and item["hypothesis_archived"] is False
    assert item["evidence_count"] == 1


@pytest.mark.asyncio
async def test_team_users_lists_names_for_owner_picker(auth_client, user_david):
    r = await auth_client.get("/api/users")
    assert r.status_code == 200
    users = r.json()["items"]
    me = next(u for u in users if u["id"] == user_david.id)
    assert me["name"] and set(me) == {"id", "name"}  # no emails or hashes leak


@pytest.mark.asyncio
async def test_team_users_requires_auth(client):
    assert (await client.get("/api/users")).status_code == 401
