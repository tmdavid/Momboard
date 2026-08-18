"""Tests for T35: Audio upload + Whisper transcription (no real API calls)."""

import pytest
import respx
from httpx import Response


@pytest.mark.asyncio
@respx.mock
async def test_upload_audio_unsupported_format(auth_client):
    """Upload with unsupported file extension → 422."""
    import io

    data = io.BytesIO(b"fake audio")
    r = await auth_client.post(
        "/api/conversations/upload",
        data={"title": "Test", "interviewer": "David"},
        files={"file": ("test.exe", data, "application/octet-stream")},
    )
    assert r.status_code == 422
    assert "Unsupported file type" in r.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_upload_audio_too_large(auth_client):
    """Upload exceeding 25MB limit → 422."""
    import io

    # Create a file just over 25MB
    big_data = io.BytesIO(b"x" * (26 * 1024 * 1024))
    r = await auth_client.post(
        "/api/conversations/upload",
        data={"title": "Test", "interviewer": "David"},
        files={"file": ("big.mp3", big_data, "audio/mpeg")},
    )
    assert r.status_code == 422
    assert "25 MB" in r.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_upload_audio_whisper_success(auth_client):
    """Successful audio upload: mocked Whisper returns diarized transcript.

    Validates that:
    1. Response is 201 with expected fields
    2. The conversation's raw_transcript starts with WEBVTT and contains timestamps
    3. An ingest job was created for the conversation
    """
    import io

    from sqlalchemy import select

    # Mock Whisper API response (verbose_json format)
    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=Response(200, json={
            "text": "Hello world. How are you?",
            "segments": [
                {"start": 0.0, "end": 2.5, "text": "Hello world."},
                {"start": 2.5, "end": 5.0, "text": "How are you?"},
            ],
        })
    )

    # Need an API key configured for this test
    auth_client._transport.app.state.settings.openai_api_key = "sk-test-fake-key"

    data = io.BytesIO(b"fake mp3 content")
    r = await auth_client.post(
        "/api/conversations/upload",
        data={"title": "Test Interview", "interviewer": "David"},
        files={"file": ("interview.mp3", data, "audio/mpeg")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Test Interview"
    assert body["status"] == "processing"
    assert "id" in body

    # Inspect the actual conversation in the DB
    from app.models import Conversation, Job

    session_factory = auth_client._transport.app.state.session_factory
    async with session_factory() as session:
        convo = await session.get(Conversation, body["id"])
        assert convo is not None
        # raw_transcript must be WEBVTT format with timestamps
        assert convo.raw_transcript is not None
        assert convo.raw_transcript.startswith("WEBVTT")
        assert "-->" in convo.raw_transcript  # contains timestamp markers
        assert "Hello world." in convo.raw_transcript
        assert convo.transcript_format == "vtt"

        # An ingest job must exist
        result = await session.execute(
            select(Job).where(
                Job.conversation_id == body["id"],
                Job.kind == "ingest",
                Job.status == "queued",
            )
        )
        job = result.scalar_one_or_none()
        assert job is not None, "Expected an ingest job to be queued"


@pytest.mark.asyncio
@respx.mock
async def test_upload_audio_whisper_upstream_error(auth_client):
    """Whisper API failure returns 502."""
    import io

    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=Response(500, text="Internal Server Error")
    )

    auth_client._transport.app.state.settings.openai_api_key = "sk-test-fake-key"

    data = io.BytesIO(b"fake mp3 content")
    r = await auth_client.post(
        "/api/conversations/upload",
        data={"title": "Test", "interviewer": "David"},
        files={"file": ("interview.mp3", data, "audio/mpeg")},
    )
    assert r.status_code == 502


@pytest.mark.asyncio
@respx.mock
async def test_upload_audio_no_api_key(auth_client):
    """Upload without API key configured → 502 (transcription fails gracefully)."""
    import io
    from unittest.mock import patch

    # Patch get_settings to return settings with empty API key
    from app.config import Settings
    no_key_settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test",
        openai_api_key="",
        env="test",
    )

    data = io.BytesIO(b"fake mp3 content")
    with patch("app.transcribe.get_settings", return_value=no_key_settings):
        r = await auth_client.post(
            "/api/conversations/upload",
            data={"title": "Test", "interviewer": "David"},
            files={"file": ("interview.mp3", data, "audio/mpeg")},
        )
    assert r.status_code == 502
    assert "not configured" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_audio_valid_extensions(auth_client):
    """Validates all supported extensions are accepted (up to size check)."""
    import io

    for ext in [".mp3", ".mp4", ".wav", ".webm", ".ogg", ".m4a"]:
        data = io.BytesIO(b"fake")
        # This will fail at transcription (no API key) but pass format validation
        r = await auth_client.post(
            "/api/conversations/upload",
            data={"title": "Test", "interviewer": "D"},
            files={"file": (f"audio{ext}", data, "audio/mpeg")},
        )
        # Should NOT be 422 for format — will be 502 (no API key)
        assert r.status_code != 422 or "Unsupported" not in r.json().get("detail", ""), \
            f"Extension {ext} should be supported"
