"""Tests for T36: Vexa meeting-bot integration — official API contract.

Official Vexa API:
- POST {base}/bots  body: {meeting_url} OR {platform, native_meeting_id}
- GET  {base}/transcripts/{platform}/{native_meeting_id}
- DELETE {base}/bots/{platform}/{native_meeting_id}
- Segments use completed: boolean (not status string)
- Supported platforms: google_meet, zoom, teams, jitsi
"""

import pytest
import respx
from httpx import Response

from app.config import Settings


def _vexa_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test-secret",
        openai_api_key="",
        env="test",
        vexa_base_url="https://api.vexa.test/v1",
        vexa_api_key="test-vexa-key-secret",
    )


def _disabled_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test-secret",
        openai_api_key="",
        env="test",
        vexa_base_url="",
        vexa_api_key="",
    )


# --- Service unit tests ---


@pytest.mark.asyncio
@respx.mock
async def test_send_bot_with_meeting_url():
    """send_bot POST /bots with meeting_url."""
    from app.services.vexa import send_bot

    settings = _vexa_settings()
    respx.post("https://api.vexa.test/v1/bots").mock(
        return_value=Response(
            201,
            json={
                "platform": "google_meet",
                "native_meeting_id": "abc-defg-hij",
                "status": "joining",
            },
        )
    )

    result = await send_bot(settings, meeting_url="https://meet.google.com/abc-defg-hij")
    assert result["platform"] == "google_meet"
    assert result["native_meeting_id"] == "abc-defg-hij"

    # Verify the request had the API key header
    req = respx.calls.last.request
    assert req.headers["X-API-Key"] == "test-vexa-key-secret"

    # Verify correct payload
    import json

    body = json.loads(req.content)
    assert body == {"meeting_url": "https://meet.google.com/abc-defg-hij"}


@pytest.mark.asyncio
@respx.mock
async def test_send_bot_with_platform_and_native_meeting_id():
    """send_bot POST /bots with platform + native_meeting_id."""
    from app.services.vexa import send_bot

    settings = _vexa_settings()
    respx.post("https://api.vexa.test/v1/bots").mock(
        return_value=Response(
            201,
            json={
                "platform": "zoom",
                "native_meeting_id": "12345678",
                "status": "joining",
            },
        )
    )

    result = await send_bot(settings, platform="zoom", native_meeting_id="12345678")
    assert result["platform"] == "zoom"
    assert result["native_meeting_id"] == "12345678"

    import json

    body = json.loads(respx.calls.last.request.content)
    assert body["platform"] == "zoom"
    assert body["native_meeting_id"] == "12345678"
    assert "native_id" not in body  # Must NOT use old field name


@pytest.mark.asyncio
async def test_send_bot_disabled_raises():
    """send_bot raises VexaDisabledError when not configured."""
    from app.services.vexa import VexaDisabledError, send_bot

    settings = _disabled_settings()
    with pytest.raises(VexaDisabledError):
        await send_bot(settings, meeting_url="https://meet.google.com/abc")


@pytest.mark.asyncio
async def test_send_bot_requires_url_or_platform():
    """send_bot raises ValueError without meeting_url or platform+native_meeting_id."""
    from app.services.vexa import send_bot

    settings = _vexa_settings()
    with pytest.raises(ValueError, match="Either meeting_url"):
        await send_bot(settings)


@pytest.mark.asyncio
async def test_send_bot_validates_platform():
    """send_bot rejects unsupported platform."""
    from app.services.vexa import send_bot

    settings = _vexa_settings()
    with pytest.raises(ValueError, match="Unsupported platform"):
        await send_bot(settings, platform="skype", native_meeting_id="123")


@pytest.mark.asyncio
@respx.mock
async def test_send_bot_422_validation():
    """send_bot raises VexaError on 422 and sanitizes error."""
    from app.services.vexa import VexaError, send_bot

    settings = _vexa_settings()
    respx.post("https://api.vexa.test/v1/bots").mock(
        return_value=Response(422, text="Invalid meeting URL format")
    )

    with pytest.raises(VexaError) as exc_info:
        await send_bot(settings, meeting_url="invalid://url")
    assert exc_info.value.status_code == 422
    # Should not leak raw API response with potential secrets
    assert "test-vexa-key-secret" not in exc_info.value.detail


@pytest.mark.asyncio
@respx.mock
async def test_stop_bot_uses_delete():
    """stop_bot sends DELETE /bots/{platform}/{native_meeting_id}."""
    from app.services.vexa import stop_bot

    settings = _vexa_settings()
    respx.delete("https://api.vexa.test/v1/bots/google_meet/abc-defg-hij").mock(
        return_value=Response(200, json={"status": "stopped"})
    )

    result = await stop_bot(settings, platform="google_meet", native_meeting_id="abc-defg-hij")
    assert result["status"] == "stopped"

    # Verify correct method and path
    req = respx.calls.last.request
    assert req.method == "DELETE"
    assert "/bots/google_meet/abc-defg-hij" in str(req.url)
    assert req.headers["X-API-Key"] == "test-vexa-key-secret"


@pytest.mark.asyncio
@respx.mock
async def test_stop_bot_accepts_self_hosted_jitsi_id_and_empty_response():
    """Official Jitsi IDs may use room@host; stop may return 204 No Content."""
    from app.services.vexa import stop_bot

    settings = _vexa_settings()
    respx.delete("https://api.vexa.test/v1/bots/jitsi/MyRoom@meet.example.com").mock(
        return_value=Response(204)
    )

    result = await stop_bot(
        settings,
        platform="jitsi",
        native_meeting_id="MyRoom@meet.example.com",
    )

    assert result == {
        "platform": "jitsi",
        "native_meeting_id": "MyRoom@meet.example.com",
        "status": "stopped",
    }


@pytest.mark.asyncio
async def test_stop_bot_rejects_path_separators():
    """Native IDs cannot escape the platform path segment."""
    from app.services.vexa import stop_bot

    with pytest.raises(ValueError, match="unsupported path characters"):
        await stop_bot(
            _vexa_settings(),
            platform="jitsi",
            native_meeting_id="room/../../other",
        )


@pytest.mark.asyncio
async def test_stop_bot_validates_platform():
    """stop_bot rejects unsupported platform."""
    from app.services.vexa import stop_bot

    settings = _vexa_settings()
    with pytest.raises(ValueError, match="Unsupported platform"):
        await stop_bot(settings, platform="webex", native_meeting_id="123")


@pytest.mark.asyncio
@respx.mock
async def test_get_transcript_uses_completed_boolean():
    """get_transcript fetches from /transcripts/{platform}/{id} and filters by completed=true."""
    from app.services.vexa import get_transcript

    settings = _vexa_settings()
    respx.get("https://api.vexa.test/v1/transcripts/zoom/meeting-123").mock(
        return_value=Response(
            200,
            json={
                "segments": [
                    {"speaker": "Alice", "text": "Hello", "completed": True},
                    {"speaker": "Bob", "text": "Incomplete...", "completed": False},
                    {"speaker": "Alice", "text": "Done", "completed": True},
                ]
            },
        )
    )

    segments = await get_transcript(
        settings, platform="zoom", native_meeting_id="meeting-123"
    )
    assert len(segments) == 2
    assert all(s.get("completed") is True for s in segments)
    # Must NOT filter by status string
    assert not any("status" in s for s in segments if s.get("completed") is True)


@pytest.mark.asyncio
@respx.mock
async def test_get_transcript_excludes_drafts():
    """get_transcript excludes segments where completed=false (drafts)."""
    from app.services.vexa import get_transcript

    settings = _vexa_settings()
    respx.get("https://api.vexa.test/v1/transcripts/teams/mtg-abc").mock(
        return_value=Response(
            200,
            json={
                "segments": [
                    {"speaker": "X", "text": "Draft only", "completed": False},
                ]
            },
        )
    )

    segments = await get_transcript(
        settings, platform="teams", native_meeting_id="mtg-abc"
    )
    assert len(segments) == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_transcript_upstream_failure():
    """get_transcript raises VexaError on upstream failure."""
    from app.services.vexa import VexaError, get_transcript

    settings = _vexa_settings()
    respx.get("https://api.vexa.test/v1/transcripts/zoom/bad-id").mock(
        return_value=Response(500, text="Internal Server Error")
    )

    with pytest.raises(VexaError) as exc_info:
        await get_transcript(settings, platform="zoom", native_meeting_id="bad-id")
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
@respx.mock
async def test_import_transcript_dedupe(seeded_db):
    """import_transcript deduplicates by platform/native_meeting_id (source_ref)."""
    from app.services.vexa import import_transcript

    settings = _vexa_settings()
    respx.get("https://api.vexa.test/v1/transcripts/google_meet/dup-meeting").mock(
        return_value=Response(
            200,
            json={
                "segments": [
                    {"speaker": "Alice", "text": "Hello world", "completed": True},
                ]
            },
        )
    )

    # First import
    item = await import_transcript(
        seeded_db,
        settings,
        platform="google_meet",
        native_meeting_id="dup-meeting",
        meeting_title="Meeting A",
    )
    await seeded_db.commit()
    assert item is not None
    assert item.source_ref == "vexa:google_meet:dup-meeting"
    assert item.source == "vexa"
    assert "Alice" in item.raw_content

    # Second import (same meeting) — should return None (dedupe)
    item2 = await import_transcript(
        seeded_db,
        settings,
        platform="google_meet",
        native_meeting_id="dup-meeting",
    )
    assert item2 is None


@pytest.mark.asyncio
@respx.mock
async def test_import_transcript_speaker_conversion(seeded_db):
    """import_transcript converts segments to speaker-attributed transcript."""
    from app.services.vexa import import_transcript

    settings = _vexa_settings()
    respx.get("https://api.vexa.test/v1/transcripts/jitsi/conv-test").mock(
        return_value=Response(
            200,
            json={
                "segments": [
                    {
                        "speaker": "Alice Johnson",
                        "text": "I have a problem with reports.",
                        "completed": True,
                    },
                    {
                        "speaker": "Bob Smith",
                        "text": "Tell me more about that.",
                        "completed": True,
                    },
                ]
            },
        )
    )

    item = await import_transcript(
        seeded_db,
        settings,
        platform="jitsi",
        native_meeting_id="conv-test",
    )
    await seeded_db.commit()
    assert item is not None
    assert "Alice Johnson: I have a problem with reports." in item.raw_content
    assert "Bob Smith: Tell me more about that." in item.raw_content
    assert item.content_format == "name_colon"
    # Meta should have platform/native_meeting_id
    assert item.meta["platform"] == "jitsi"
    assert item.meta["native_meeting_id"] == "conv-test"


def test_source_ref_deterministic():
    """source_ref is stable based on platform/native_meeting_id."""
    from app.services.vexa import _source_ref_for_meeting

    ref1 = _source_ref_for_meeting("zoom", "abc-123")
    ref2 = _source_ref_for_meeting("zoom", "abc-123")
    ref3 = _source_ref_for_meeting("zoom", "other-456")

    assert ref1 == ref2
    assert ref1 != ref3
    assert ref1 == "vexa:zoom:abc-123"


def test_segments_to_transcript():
    """_segments_to_transcript formats segments correctly."""
    from app.services.vexa import _segments_to_transcript

    segments = [
        {"speaker": "Alice", "text": "Hi there"},
        {"speaker": "Bob", "text": "Hello"},
        {"speaker": "Alice", "text": "How's work?"},
    ]
    result = _segments_to_transcript(segments)
    assert result == "Alice: Hi there\nBob: Hello\nAlice: How's work?"


def test_validate_platform_rejects_unsupported():
    """_validate_platform raises for unsupported platforms."""
    from app.services.vexa import _validate_platform

    # Supported should not raise
    _validate_platform("google_meet")
    _validate_platform("zoom")
    _validate_platform("teams")
    _validate_platform("jitsi")

    with pytest.raises(ValueError, match="Unsupported platform"):
        _validate_platform("skype")


def test_sanitize_native_meeting_id():
    """_sanitize_native_meeting_id rejects path-traversal characters."""
    from app.services.vexa import _sanitize_native_meeting_id

    # Valid
    _sanitize_native_meeting_id("abc-123")
    _sanitize_native_meeting_id("meeting_456")
    _sanitize_native_meeting_id("mtg.test")

    # Invalid (path traversal, spaces, slashes)
    with pytest.raises(ValueError):
        _sanitize_native_meeting_id("../../../etc/passwd")
    with pytest.raises(ValueError):
        _sanitize_native_meeting_id("has space")
    with pytest.raises(ValueError):
        _sanitize_native_meeting_id("slash/bad")


# --- API integration tests ---


@pytest.mark.asyncio
async def test_vexa_api_send_bot_disabled(auth_client):
    """POST /api/vexa/bots returns 503 when Vexa is disabled."""
    r = await auth_client.post(
        "/api/vexa/bots", json={"meeting_url": "https://meet.google.com/abc"}
    )
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"]


@pytest.mark.asyncio
async def test_vexa_api_send_bot_validation(auth_client):
    """POST /api/vexa/bots with no URL/platform returns 422."""
    r = await auth_client.post("/api/vexa/bots", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_vexa_api_send_bot_unsupported_platform(auth_client):
    """POST /api/vexa/bots with unsupported platform returns 422."""
    r = await auth_client.post(
        "/api/vexa/bots",
        json={"platform": "skype", "native_meeting_id": "123"},
    )
    assert r.status_code == 422
    assert "Unsupported platform" in r.json()["detail"]


@pytest.mark.asyncio
async def test_vexa_api_stop_disabled(auth_client):
    """DELETE /api/vexa/bots/{platform}/{id} returns 503 when disabled."""
    r = await auth_client.delete("/api/vexa/bots/google_meet/abc-123")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_vexa_api_transcript_disabled(auth_client):
    """GET /api/vexa/transcripts/{platform}/{id} returns 503 when disabled."""
    r = await auth_client.get("/api/vexa/transcripts/zoom/meeting-123")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_vexa_api_import_disabled(auth_client):
    """POST /api/vexa/import returns 503 when disabled."""
    r = await auth_client.post(
        "/api/vexa/import",
        json={"platform": "google_meet", "native_meeting_id": "abc-123"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_vexa_api_import_validates_platform(auth_client):
    """POST /api/vexa/import with unsupported platform returns 422."""
    r = await auth_client.post(
        "/api/vexa/import",
        json={"platform": "webex", "native_meeting_id": "abc"},
    )
    assert r.status_code == 422
    assert "Unsupported platform" in r.json()["detail"]


@pytest.mark.asyncio
async def test_vexa_api_requires_auth(client):
    """Vexa endpoints require authentication."""
    r = await client.post(
        "/api/vexa/bots", json={"meeting_url": "https://meet.google.com/abc"}
    )
    assert r.status_code == 401
