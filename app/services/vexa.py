"""T36: Vexa meeting-bot integration — send/stop bot, fetch transcript segments, import.

Official Vexa API contract (docs.vexa.ai/api/meetings):
- POST {base}/bots  — body: {meeting_url} OR {platform, native_meeting_id}
- GET  {base}/transcripts/{platform}/{native_meeting_id}
- DELETE {base}/bots/{platform}/{native_meeting_id}  — stop bot
- Transcript segments use `completed: boolean` (not status string)
- Supported platforms: google_meet, zoom, teams, jitsi
"""

import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import StagingInboxItem

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = {"google_meet", "zoom", "teams", "jitsi"}


class VexaDisabledError(Exception):
    """Raised when Vexa is not configured."""

    def __init__(self):
        super().__init__(
            "Vexa integration is disabled. Set VEXA_BASE_URL and VEXA_API_KEY."
        )


class VexaError(Exception):
    """Raised when a Vexa API call fails."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Vexa API error {status_code}: {detail}")


def _check_enabled(settings: Settings) -> tuple[str, str]:
    """Validate Vexa is configured. Returns (base_url, api_key)."""
    if not settings.vexa_base_url or not settings.vexa_api_key:
        raise VexaDisabledError()
    return settings.vexa_base_url.rstrip("/"), settings.vexa_api_key


def _validate_platform(platform: str) -> str:
    """Validate platform is in the supported set."""
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(
            f"Unsupported platform '{platform}'. "
            f"Supported: {sorted(SUPPORTED_PLATFORMS)}"
        )
    return platform


def _sanitize_native_meeting_id(native_meeting_id: str) -> str:
    """Validate a native meeting ID before placing it in a Vexa URL path.

    Vexa uses ``room@host`` for rooms on self-hosted Jitsi deployments and
    Teams identifiers may contain colons, so both characters are intentional.
    Path separators and control characters remain forbidden.
    """
    if not re.fullmatch(r"[a-zA-Z0-9@:\-_.]+", native_meeting_id):
        raise ValueError(
            "Invalid native_meeting_id: contains unsupported path characters"
        )
    return native_meeting_id


def _sanitize_error(response_text: str) -> str:
    """Sanitize upstream error to avoid leaking secrets/internal details."""
    # Truncate and strip anything that looks like a key/token
    safe = response_text[:200]
    # Remove anything that looks like an API key
    safe = re.sub(r"[a-zA-Z0-9]{32,}", "[REDACTED]", safe)
    return safe


async def send_bot(
    settings: Settings,
    *,
    meeting_url: str | None = None,
    platform: str | None = None,
    native_meeting_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send a Vexa bot to a meeting.

    Official contract: POST {base}/bots
    Body: {meeting_url} OR {platform, native_meeting_id}

    Returns the API response which includes platform and native_meeting_id
    for subsequent addressing.
    """
    base_url, api_key = _check_enabled(settings)

    payload: dict[str, Any] = {}
    if meeting_url:
        payload["meeting_url"] = meeting_url
    elif platform and native_meeting_id:
        _validate_platform(platform)
        _sanitize_native_meeting_id(native_meeting_id)
        payload["platform"] = platform
        payload["native_meeting_id"] = native_meeting_id
    else:
        raise ValueError(
            "Either meeting_url or (platform + native_meeting_id) required"
        )

    client = http_client or httpx.AsyncClient(timeout=30.0)
    close_client = http_client is None

    try:
        response = await client.post(
            f"{base_url}/bots",
            json=payload,
            headers={"X-API-Key": api_key},
        )
        if response.status_code == 422:
            raise VexaError(422, _sanitize_error(response.text))
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result
    except httpx.HTTPStatusError as e:
        raise VexaError(e.response.status_code, _sanitize_error(e.response.text))
    except httpx.RequestError as e:
        raise VexaError(0, str(e))
    finally:
        if close_client:
            await client.aclose()


async def stop_bot(
    settings: Settings,
    *,
    platform: str,
    native_meeting_id: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Stop a Vexa bot.

    Official contract: DELETE {base}/bots/{platform}/{native_meeting_id}
    """
    base_url, api_key = _check_enabled(settings)
    _validate_platform(platform)
    _sanitize_native_meeting_id(native_meeting_id)

    client = http_client or httpx.AsyncClient(timeout=30.0)
    close_client = http_client is None

    try:
        response = await client.delete(
            f"{base_url}/bots/{platform}/{native_meeting_id}",
            headers={"X-API-Key": api_key},
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {
                "platform": platform,
                "native_meeting_id": native_meeting_id,
                "status": "stopped",
            }
        result: dict[str, Any] = response.json()
        return result
    except httpx.HTTPStatusError as e:
        raise VexaError(e.response.status_code, _sanitize_error(e.response.text))
    except httpx.RequestError as e:
        raise VexaError(0, str(e))
    finally:
        if close_client:
            await client.aclose()


async def get_transcript(
    settings: Settings,
    *,
    platform: str,
    native_meeting_id: str,
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Get transcript segments for a meeting. Only returns completed segments.

    Official contract: GET {base}/transcripts/{platform}/{native_meeting_id}
    Segments use `completed: boolean` field to indicate finality.
    Only segments with completed=true are returned.
    """
    base_url, api_key = _check_enabled(settings)
    _validate_platform(platform)
    _sanitize_native_meeting_id(native_meeting_id)

    client = http_client or httpx.AsyncClient(timeout=30.0)
    close_client = http_client is None

    try:
        response = await client.get(
            f"{base_url}/transcripts/{platform}/{native_meeting_id}",
            headers={"X-API-Key": api_key},
        )
        response.raise_for_status()
        data = response.json()
        segments = data.get("segments", data if isinstance(data, list) else [])
        # Filter to completed segments only (completed: boolean per official API)
        return [s for s in segments if s.get("completed") is True]
    except httpx.HTTPStatusError as e:
        raise VexaError(e.response.status_code, _sanitize_error(e.response.text))
    except httpx.RequestError as e:
        raise VexaError(0, str(e))
    finally:
        if close_client:
            await client.aclose()


def _segments_to_transcript(segments: list[dict[str, Any]]) -> str:
    """Convert Vexa transcript segments to a speaker-attributed transcript string."""
    lines: list[str] = []
    for seg in segments:
        speaker = seg.get("speaker", "Unknown")
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _source_ref_for_meeting(platform: str, native_meeting_id: str) -> str:
    """Deterministic source_ref for dedupe based on platform/native_meeting_id."""
    # URL-safe, stable key
    safe_id = re.sub(r"[^a-zA-Z0-9\-_.]", "_", native_meeting_id)
    return f"vexa:{platform}:{safe_id}"


async def import_transcript(
    db: AsyncSession,
    settings: Settings,
    *,
    platform: str,
    native_meeting_id: str,
    meeting_title: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> StagingInboxItem | None:
    """Import completed transcript segments into staging inbox.

    Uses deterministic source_ref based on platform/native_meeting_id for dedupe.
    Returns None if already imported or no completed segments.
    """
    _validate_platform(platform)
    _sanitize_native_meeting_id(native_meeting_id)

    # Check dedupe
    source_ref = _source_ref_for_meeting(platform, native_meeting_id)
    existing = await db.execute(
        select(StagingInboxItem).where(StagingInboxItem.source_ref == source_ref)
    )
    if existing.scalar_one_or_none() is not None:
        return None  # Already imported

    segments = await get_transcript(
        settings, platform=platform, native_meeting_id=native_meeting_id,
        http_client=http_client,
    )

    if not segments:
        return None

    transcript_text = _segments_to_transcript(segments)
    title = meeting_title or f"Vexa meeting ({platform}/{native_meeting_id[:12]})"

    item = StagingInboxItem(
        source="vexa",
        source_ref=source_ref,
        title=title,
        raw_content=transcript_text,
        content_format="name_colon",
        meta={
            "platform": platform,
            "native_meeting_id": native_meeting_id,
            "segment_count": len(segments),
        },
        status="pending_import",
    )
    db.add(item)
    await db.flush()
    return item
