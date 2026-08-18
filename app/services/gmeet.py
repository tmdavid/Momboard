"""T24: Google Meet/Drive polling — auto-ingest transcript Docs from Drive.

Design:
- Service account authenticates to Drive API
- Polls a configured folder for new Google Docs (Meet transcripts)
- Parses the Doc content into transcript format
- Dedupes via T34 staging inbox (source_ref = Drive doc ID)
- Parse errors retained in inbox with status='parse_error'
- No live API calls in tests — uses recorded fixtures
"""

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services import DuplicateSourceRefError, submit_to_inbox

logger = logging.getLogger(__name__)

# Google Meet transcript Doc format: lines like "Speaker Name\nTimestamp\nText"
MEET_TRANSCRIPT_PATTERN = re.compile(
    r"^(.+?)\n(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\n(.+?)(?=\n\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def parse_meet_doc(content: str) -> tuple[str, str | None]:
    """Parse a Google Meet transcript Doc into name:text format.

    Returns (parsed_transcript, error_or_none).
    If parsing fails entirely, returns ("", error_message).
    """
    matches = MEET_TRANSCRIPT_PATTERN.findall(content)
    if not matches:
        # Try simpler line-based parsing
        lines = content.strip().split("\n")
        if len(lines) < 3:
            return "", f"Could not parse Meet Doc: too short ({len(lines)} lines)"

        # Attempt "Name\nText" pattern (alternate lines)
        parsed_lines = []
        i = 0
        while i < len(lines) - 1:
            name = lines[i].strip()
            # Skip timestamp-like lines
            if re.match(r"^\d{1,2}:\d{2}", name):
                i += 1
                continue
            text = lines[i + 1].strip()
            if name and text and not re.match(r"^\d{1,2}:\d{2}", text):
                parsed_lines.append(f"{name}: {text}")
                i += 2
            else:
                i += 1

        if parsed_lines:
            return "\n".join(parsed_lines), None
        return "", "Could not parse Meet Doc: no speaker patterns found"

    # Standard Meet format
    parsed_lines = []
    for speaker, _timestamp, text in matches:
        clean_text = text.strip().replace("\n", " ")
        parsed_lines.append(f"{speaker.strip()}: {clean_text}")

    return "\n".join(parsed_lines), None


async def poll_drive_for_transcripts(
    db: AsyncSession,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Poll Google Drive for new Meet transcript Docs.

    Uses the Drive API via httpx (no google-api-python-client dependency).
    Requires settings: GDRIVE_FOLDER_ID, GDRIVE_SERVICE_ACCOUNT_JSON

    Returns list of inbox items created.
    """

    import httpx

    folder_id = getattr(settings, "gdrive_folder_id", "")
    sa_json_path = getattr(settings, "gdrive_service_account_json", "")

    if not folder_id or not sa_json_path:
        logger.debug("Drive polling skipped: no folder_id or service account configured")
        return []

    # Authenticate with service account (JWT → access token)
    access_token = await _get_drive_access_token(sa_json_path)
    if not access_token:
        logger.error("Failed to obtain Drive access token")
        return []

    results: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        # List files in the folder (Google Docs only, ordered by modified time)
        # Paginate through all pages using nextPageToken
        list_url = "https://www.googleapis.com/drive/v3/files"
        headers = {"Authorization": f"Bearer {access_token}"}
        page_token: str | None = None
        all_files: list[dict[str, Any]] = []

        while True:
            params: dict[str, str] = {
                "q": f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document'",
                "orderBy": "modifiedTime desc",
                "pageSize": "20",
                "fields": "files(id,name,modifiedTime),nextPageToken",
            }
            if page_token:
                params["pageToken"] = page_token

            resp = await client.get(list_url, params=params, headers=headers, timeout=30)
            if resp.status_code != 200:
                logger.error("Drive files.list failed: %s %s", resp.status_code, resp.text[:200])
                break

            data = resp.json()
            files = data.get("files", [])
            all_files.extend(files)

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        # Dedupe files by id (in case of overlap between pages)
        seen_ids: set[str] = set()
        unique_files: list[dict[str, Any]] = []
        for f in all_files:
            if f["id"] not in seen_ids:
                seen_ids.add(f["id"])
                unique_files.append(f)

        for file_info in unique_files:
            doc_id = file_info["id"]
            doc_name = file_info.get("name", "Untitled")

            # Export as plain text
            export_url = f"https://www.googleapis.com/drive/v3/files/{doc_id}/export"
            export_resp = await client.get(
                export_url,
                params={"mimeType": "text/plain"},
                headers=headers,
                timeout=30,
            )
            if export_resp.status_code != 200:
                logger.warning("Failed to export doc %s: %s", doc_id, export_resp.status_code)
                continue

            raw_content = export_resp.text

            # Parse the transcript
            parsed, parse_error = parse_meet_doc(raw_content)

            # Submit to staging inbox (dedupe on doc_id)
            try:
                if parse_error:
                    item = await submit_to_inbox(
                        db,
                        source="gmeet",
                        source_ref=f"gdrive:{doc_id}",
                        title=doc_name,
                        raw_content=raw_content,
                        content_format="gdoc_raw",
                        meta={"doc_id": doc_id, "modified_time": file_info.get("modifiedTime")},
                        status="parse_error",
                        parse_error=parse_error,
                    )
                else:
                    item = await submit_to_inbox(
                        db,
                        source="gmeet",
                        source_ref=f"gdrive:{doc_id}",
                        title=doc_name,
                        raw_content=parsed,
                        content_format="name_colon",
                        meta={"doc_id": doc_id, "modified_time": file_info.get("modifiedTime")},
                    )
                results.append({"id": item.id, "doc_id": doc_id, "status": item.status})
            except DuplicateSourceRefError:
                # Already seen this doc — skip
                continue

    await db.flush()
    return results


async def _get_drive_access_token(sa_json_path: str) -> str | None:
    """Get an access token from a service account JSON key file.

    Uses a simple JWT assertion flow without google-auth dependency.
    """
    import json
    import time

    import httpx

    try:
        with open(sa_json_path) as f:
            sa_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Cannot read service account: %s", e)
        return None

    # Build JWT
    private_key = sa_data.get("private_key", "")
    client_email = sa_data.get("client_email", "")
    token_uri = sa_data.get("token_uri", "https://oauth2.googleapis.com/token")

    if not private_key or not client_email:
        logger.error("Service account JSON missing required fields")
        return None

    now = int(time.time())

    # Sign with RSA using PyJWT if available
    try:
        import jwt as pyjwt  # type: ignore[import-not-found]
        token = pyjwt.encode(
            {
                "iss": client_email,
                "scope": "https://www.googleapis.com/auth/drive.readonly",
                "aud": token_uri,
                "iat": now,
                "exp": now + 3600,
            },
            private_key,
            algorithm="RS256",
        )
    except ImportError:
        # Fallback: cannot sign JWT without a library
        logger.warning("PyJWT not installed — Drive auth unavailable")
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": token,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            token_value: str | None = resp.json().get("access_token")
            return token_value
        logger.error("Token exchange failed: %s", resp.text[:200])
        return None
