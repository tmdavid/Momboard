"""Tests for T29 contact memory, T30 timeline API, T41 staleness."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Company,
    Contact,
    Conversation,
    ConversationContact,
    Highlight,
    Hypothesis,
    utcnow,
)
from app.services.contacts import get_company_timeline, get_contact_timeline
from app.services.staleness import compute_freshness_band, get_hypothesis_freshness


@pytest.mark.asyncio
async def test_contact_timeline_merges_events(seeded_db: AsyncSession):
    """Timeline merges conversations, highlights, commitments."""
    company = Company(name="Timeline Corp")
    seeded_db.add(company)
    await seeded_db.flush()

    contact = Contact(name="Jane", company_id=company.id)
    seeded_db.add(contact)
    await seeded_db.flush()

    convo = Conversation(
        title="Timeline call",
        company_id=company.id,
        status="ready",
        happened_at=utcnow(),
    )
    seeded_db.add(convo)
    await seeded_db.flush()

    seeded_db.add(ConversationContact(conversation_id=convo.id, contact_id=contact.id))

    # Add highlights
    seeded_db.add(Highlight(
        conversation_id=convo.id,
        tag_key="pain",
        quote="Our reports take forever",
        status="accepted",
        origin="ai",
    ))
    seeded_db.add(Highlight(
        conversation_id=convo.id,
        tag_key="commitment",
        quote="We'll schedule a follow-up",
        status="accepted",
        origin="ai",
    ))
    await seeded_db.commit()

    events = await get_contact_timeline(seeded_db, contact.id)
    kinds = {e["kind"] for e in events}
    assert "conversation" in kinds
    assert "highlight" in kinds
    assert "commitment" in kinds


@pytest.mark.asyncio
async def test_company_timeline_aggregates_contacts(seeded_db: AsyncSession):
    """Company timeline shows all conversations across contacts."""
    company = Company(name="Multi Corp")
    seeded_db.add(company)
    await seeded_db.flush()

    convo = Conversation(title="Company call", company_id=company.id, status="ready")
    seeded_db.add(convo)
    await seeded_db.commit()

    events = await get_company_timeline(seeded_db, company.id)
    assert len(events) >= 1
    assert events[0]["kind"] == "conversation"


@pytest.mark.asyncio
async def test_contact_detail_endpoint(auth_client: AsyncClient, sample_conversation, session_factory):
    """GET /api/contacts/{id} returns detail with stats."""
    from sqlalchemy import select

    from app.models import ConversationContact

    # Get contact ID directly from the DB
    async with session_factory() as session:
        result = await session.execute(
            select(ConversationContact.contact_id).limit(1)
        )
        row = result.scalar_one_or_none()

    if row:
        r = await auth_client.get(f"/api/contacts/{row}")
        assert r.status_code == 200
        body = r.json()
        assert "name" in body
        assert "conversation_count" in body


@pytest.mark.asyncio
async def test_contact_timeline_endpoint(auth_client: AsyncClient, sample_conversation, session_factory):
    """GET /api/contacts/{id}/timeline returns events."""
    from sqlalchemy import select

    from app.models import ConversationContact

    async with session_factory() as session:
        result = await session.execute(
            select(ConversationContact.contact_id).limit(1)
        )
        row = result.scalar_one_or_none()

    if row:
        r = await auth_client.get(f"/api/contacts/{row}/timeline")
        assert r.status_code == 200
        assert "events" in r.json()


# --- T41 Staleness tests ---


def test_freshness_band_fresh():
    now = datetime(2026, 8, 17, tzinfo=UTC)
    evidence_date = now - timedelta(days=30)
    assert compute_freshness_band(evidence_date, now) == "fresh"


def test_freshness_band_aging():
    now = datetime(2026, 8, 17, tzinfo=UTC)
    evidence_date = now - timedelta(days=120)
    assert compute_freshness_band(evidence_date, now) == "aging"


def test_freshness_band_stale():
    now = datetime(2026, 8, 17, tzinfo=UTC)
    evidence_date = now - timedelta(days=200)
    assert compute_freshness_band(evidence_date, now) == "stale"


def test_freshness_band_none_is_stale():
    assert compute_freshness_band(None) == "stale"


@pytest.mark.asyncio
async def test_hypothesis_freshness_with_no_evidence(seeded_db: AsyncSession):
    """Hypothesis with no confirmed evidence is stale."""
    hyp = Hypothesis(statement="Test hypothesis for freshness check")
    seeded_db.add(hyp)
    await seeded_db.commit()

    result = await get_hypothesis_freshness(seeded_db, hyp.id)
    assert result["freshness"] == "stale"
    assert result["newest_evidence_at"] is None
