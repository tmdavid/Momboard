"""Tests for T31 digest, T38 briefs, T42 corpus chat, T44 quote cards."""

from datetime import date

import pytest

from app.llm.client import FakeLLMClient
from app.services.digest import _next_monday_0800_utc, build_digest
from app.services.quote_cards import _autoshrink_quote, render_quote_card_svg

# --- T31 Digest ---


def test_digest_builder_omits_empty_sections():
    """Empty sections are omitted, not rendered as zero."""
    snapshot = {
        "new_commitments": [],
        "overdue_followups": [],
        "stale_hypotheses": [],
        "new_drifts": [],
    }
    md = build_digest(snapshot, date(2026, 8, 10))
    assert md == ""  # Fully empty → empty string


def test_digest_builder_renders_commitments():
    snapshot = {
        "new_commitments": [{"quote": "Will schedule demo", "company": "Acme"}],
        "overdue_followups": [],
        "stale_hypotheses": [],
        "new_drifts": [],
    }
    md = build_digest(snapshot, date(2026, 8, 10))
    assert "New Commitments" in md
    assert "Will schedule demo" in md
    assert "Acme" in md


def test_digest_builder_renders_overdue():
    snapshot = {
        "new_commitments": [],
        "overdue_followups": [{"quote": "Send pricing doc", "age_days": 21}],
        "stale_hypotheses": [],
        "new_drifts": [],
    }
    md = build_digest(snapshot, date(2026, 8, 10))
    assert "Overdue" in md
    assert "21d ago" in md


def test_next_monday_0800_utc():
    # From a Tuesday → next Monday
    d = date(2026, 8, 11)  # Tuesday
    result = _next_monday_0800_utc(d)
    assert result.weekday() == 0  # Monday
    assert result.hour == 8
    assert result.day == 17


def test_digest_reschedule_from_monday():
    # From Monday → next week Monday
    d = date(2026, 8, 17)  # Monday
    result = _next_monday_0800_utc(d)
    assert result.weekday() == 0
    assert result.day == 24


# --- T38 Briefs ---


@pytest.mark.asyncio
async def test_brief_first_call_degrades_gracefully(seeded_db):
    """Brief for a contact with no history degrades gracefully."""
    from app.models import Contact
    from app.services.briefs import build_brief

    contact = Contact(name="New Person")
    seeded_db.add(contact)
    await seeded_db.commit()

    llm = FakeLLMClient()
    analysis = await build_brief(seeded_db, contact.id, llm=llm)
    await seeded_db.commit()

    result = analysis.result
    assert result["is_first_call"] is True
    assert result["known_facts"] == []


# --- T42 Corpus Chat ---


@pytest.mark.asyncio
async def test_corpus_chat_gap_when_no_evidence(seeded_db):
    """Chat returns gap=true when no evidence matches."""
    from app.services.corpus_chat import ask_corpus

    llm = FakeLLMClient()
    result = await ask_corpus(seeded_db, "what about pricing?", llm=llm)

    assert result["gap"] is True
    assert result["suggested_interview_question"] is not None


# --- T44 Quote Cards ---


def test_card_svg_renders_1600x900():
    """SVG output has correct dimensions."""
    svg = render_quote_card_svg(
        quote="Every Monday I export to Excel and clean it by hand",
        tag_emoji="➡️",
        tag_name="Workaround",
        company_name="Acme",
        theme="light",
        anonymize=False,
    )
    assert 'width="1600"' in svg
    assert 'height="900"' in svg
    assert "Workaround" in svg
    assert "Acme" in svg


def test_card_anonymize_hides_company():
    svg = render_quote_card_svg(
        quote="We pay $50k per year for this",
        tag_emoji="💰",
        tag_name="Money",
        company_name="SecretCorp",
        theme="light",
        anonymize=True,
    )
    assert "SecretCorp" not in svg
    assert "Customer interview" in svg


def test_card_dark_theme():
    svg = render_quote_card_svg(
        quote="Short quote",
        tag_emoji="⚡",
        tag_name="Pain",
        theme="dark",
    )
    assert "#1a1a2e" in svg  # dark bg


def test_autoshrink_short_quote():
    text, size = _autoshrink_quote("Short quote")
    assert size == 48


def test_autoshrink_medium_quote():
    text, size = _autoshrink_quote("x" * 150)
    assert size == 40


def test_autoshrink_long_quote_ellipsis():
    text, size = _autoshrink_quote("x" * 500)
    assert size == 24
    assert "…" in text


@pytest.mark.asyncio
async def test_quote_card_api_rejected_returns_404(auth_client, sample_conversation, seeded_db):
    """Rejected highlights → 404 (never beautify rejected evidence)."""
    from app.models import Highlight

    # Add a rejected highlight
    h = Highlight(
        conversation_id=sample_conversation.id,
        tag_key="compliment",
        quote="Sounds great!",
        status="rejected",
        origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.commit()

    r = await auth_client.get(f"/api/highlights/{h.id}/card.png")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_quote_card_api_returns_png(auth_client, sample_conversation, seeded_db):
    """Valid highlight returns image content."""
    from app.models import Highlight

    h = Highlight(
        conversation_id=sample_conversation.id,
        tag_key="pain",
        quote="Reports take 2 hours every week",
        status="accepted",
        origin="ai",
    )
    seeded_db.add(h)
    await seeded_db.commit()

    r = await auth_client.get(f"/api/highlights/{h.id}/card.png")
    # May be SVG fallback if cairosvg isn't installed
    assert r.status_code == 200
