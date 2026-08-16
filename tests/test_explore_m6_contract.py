"""M6: API contract tests for missing explore/synthesis requirements.

T19/T20: HighlightWithContext must include utterance_id for source-anchored navigation.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Company,
    Conversation,
    Highlight,
    Utterance,
)
from app.seed import seed_tags


@pytest.mark.asyncio
async def test_highlights_endpoint_includes_utterance_id(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
):
    """GET /api/highlights items must include utterance_id for anchor navigation.

    Requirement: The Explore page needs utterance_id so that clicking a quote
    card navigates to /conversations/{id}#utterance-{utterance_id}.
    """
    async with session_factory() as db:
        await seed_tags(db)

        company = Company(name="AnchorCo")
        db.add(company)
        await db.flush()

        convo = Conversation(
            title="Anchor test conversation",
            company_id=company.id,
            interviewer="David",
            status="ready",
        )
        db.add(convo)
        await db.flush()

        utt = Utterance(
            conversation_id=convo.id,
            idx=0,
            speaker_label="Contact",
            speaker_side="them",
            text="Every Monday I export all flagged listings to Excel.",
        )
        db.add(utt)
        await db.flush()

        highlight = Highlight(
            conversation_id=convo.id,
            utterance_id=utt.id,
            tag_key="pain",
            quote="Every Monday I export all flagged listings to Excel",
            origin="ai",
            status="accepted",
            confidence=0.95,
        )
        db.add(highlight)
        await db.commit()

    r = await auth_client.get("/api/highlights")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0

    # Find our highlight in the response
    item = next(
        (h for h in body["items"] if h["quote"] == "Every Monday I export all flagged listings to Excel"),
        None,
    )
    assert item is not None, "Created highlight not found in explore response"

    # KEY ASSERTION: utterance_id must be present for anchor navigation
    assert "utterance_id" in item, (
        "HighlightWithContext must include utterance_id for source-utterance anchored navigation"
    )
    assert item["utterance_id"] == utt.id


@pytest.mark.asyncio
async def test_highlights_endpoint_includes_utterance_id_for_null_utterance(
    auth_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
):
    """GET /api/highlights items with utterance_id=None should return utterance_id as null.

    Requirement: Manual highlights without an utterance anchor should still
    include the field (as null) so the frontend can conditionally build hash links.
    """
    async with session_factory() as db:
        await seed_tags(db)

        company = Company(name="NullAnchorCo")
        db.add(company)
        await db.flush()

        convo = Conversation(
            title="Null anchor test",
            company_id=company.id,
            interviewer="David",
            status="ready",
        )
        db.add(convo)
        await db.flush()

        # Highlight without utterance_id (manual highlight, no anchor)
        highlight = Highlight(
            conversation_id=convo.id,
            utterance_id=None,
            tag_key="pain",
            quote="A highlight without anchor",
            origin="human",
            status="accepted",
            confidence=1.0,
        )
        db.add(highlight)
        await db.commit()

    r = await auth_client.get("/api/highlights")
    assert r.status_code == 200
    body = r.json()

    item = next(
        (h for h in body["items"] if h["quote"] == "A highlight without anchor"),
        None,
    )
    assert item is not None

    # The field must exist (even if null) for consistent API contract
    assert "utterance_id" in item, (
        "HighlightWithContext must always include utterance_id field (null when not anchored)"
    )
    assert item["utterance_id"] is None
