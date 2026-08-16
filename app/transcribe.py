"""Audio/video transcription via OpenAI Whisper API."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Whisper supports these formats per OpenAI docs
SUPPORTED_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB (Whisper API limit)


class TranscriptionError(Exception):
    """Raised when transcription fails."""

    pass


async def transcribe_audio(
    file_content: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    language: str | None = None,
    response_format: str = "verbose_json",
) -> str:
    """Transcribe audio/video bytes via OpenAI Whisper API.

    Args:
        file_content: Raw file bytes.
        filename: Original filename (used for format detection).
        content_type: MIME type of the file.
        language: Optional ISO-639-1 language code (e.g. "en", "es").
        response_format: Whisper output format. Default "verbose_json" for timestamps.

    Returns:
        Transcript text formatted as "Speaker: text" lines (from verbose_json)
        or raw text (from other formats).

    Raises:
        TranscriptionError: If the API call fails or the file is invalid.
    """
    settings = get_settings()

    if not settings.openai_api_key:
        raise TranscriptionError("OPENAI_API_KEY is not configured")

    if len(file_content) > MAX_FILE_SIZE:
        raise TranscriptionError(
            f"File exceeds {MAX_FILE_SIZE // (1024 * 1024)} MB Whisper limit"
        )

    base_url = settings.openai_base_url.rstrip("/")
    url = f"{base_url}/audio/transcriptions"

    data: dict[str, str] = {
        "model": "whisper-1",
        "response_format": response_format,
    }
    if language:
        data["language"] = language

    files = {"file": (filename, file_content, content_type)}

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data=data,
                files=files,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = e.response.text if e.response else str(e)
            logger.error("Whisper API error: %s", detail)
            raise TranscriptionError(f"Whisper API returned {e.response.status_code}: {detail}")
        except httpx.RequestError as e:
            logger.error("Whisper API request failed: %s", e)
            raise TranscriptionError(f"Request to Whisper API failed: {e}")

    if response_format == "verbose_json":
        result = response.json()
        return _format_verbose_json(result)
    else:
        return str(response.text)


def _format_verbose_json(result: dict) -> str:
    """Convert Whisper verbose_json to a simple timestamped transcript.

    Whisper doesn't do speaker diarization, so we output segments with timestamps
    that the normalizer can handle.
    """
    segments = result.get("segments", [])
    if not segments:
        # Fallback to plain text
        return str(result.get("text", ""))

    lines: list[str] = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if not text:
            continue
        start = segment.get("start", 0)
        # Format as VTT-like for the normalizer to handle
        start_h = int(start // 3600)
        start_m = int((start % 3600) // 60)
        start_s = int(start % 60)
        start_ms = int((start % 1) * 1000)
        end = segment.get("end", start)
        end_h = int(end // 3600)
        end_m = int((end % 3600) // 60)
        end_s = int(end % 60)
        end_ms = int((end % 1) * 1000)
        lines.append(
            f"{start_h:02d}:{start_m:02d}:{start_s:02d}.{start_ms:03d} --> "
            f"{end_h:02d}:{end_m:02d}:{end_s:02d}.{end_ms:03d}"
        )
        lines.append(text)
        lines.append("")

    return "WEBVTT\n\n" + "\n".join(lines)
