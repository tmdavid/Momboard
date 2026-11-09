#!/usr/bin/env python3
"""Ingest Clari Copilot calls into MomBoard as conversations.

This is a **user-run** script (no webhook). You trigger it on demand; it pulls
recorded calls from Clari Copilot over a date range, converts each transcript
into MomBoard's ``Name: text`` format, and creates a conversation via the
MomBoard API. MomBoard's normal ingest pipeline (normalize -> tag -> analyze)
then runs on each new conversation.

Runs are safe to repeat: each conversation is stamped with
``meta.source_ref = "clari:<call_id>"`` and already-imported calls are skipped.

--------------------------------------------------------------------------------
Data flow
--------------------------------------------------------------------------------
    Clari  GET /calls?from=&to=            -> list of call ids + metadata
    Clari  GET /call-details?id=<call_id>  -> transcript + speakers per call
                     |
                     v  (convert transcript array -> "Name: text")
    MomBoard POST /auth/login              -> session cookie
    MomBoard GET  /api/conversations?q=    -> dedupe check (meta.source_ref)
    MomBoard POST /api/conversations       -> create + enqueue ingest job

--------------------------------------------------------------------------------
Configuration (environment variables, or a .env file in the project root)
--------------------------------------------------------------------------------
    CLARI_API_KEY         Clari Copilot API key      (sent as X-Api-Key)
    CLARI_API_PASSWORD    Clari Copilot API password (sent as X-Api-Password)
                          (CLARI_API_SECRET is accepted as an alias)
    CLARI_BASE_URL        Optional; defaults to https://rest-api.copilot.clari.com

    MOMBOARD_BASE_URL     Optional; defaults to http://127.0.0.1:8000
    MOMBOARD_EMAIL        MomBoard login email
    MOMBOARD_PASSWORD     MomBoard login password

Secrets are read from the environment. Avoid passing them as CLI flags on shared
machines because shell history may retain the value.

--------------------------------------------------------------------------------
Usage
--------------------------------------------------------------------------------
    # Preview the latest call only (fast; no writes):
    .venv/bin/python scripts/clari_ingest.py --dry-run --max-calls 1

    # Preview the 50 newest calls (default cap):
    .venv/bin/python scripts/clari_ingest.py --dry-run

    # Import a specific window (client-side filtered on the call `time` field):
    .venv/bin/python scripts/clari_ingest.py --from 2026-08-01 --to 2026-08-31

    # Import a single call by id:
    .venv/bin/python scripts/clari_ingest.py --call-id 665f...abc

    # Re-import even if already present:
    .venv/bin/python scripts/clari_ingest.py --call-id 665f...abc --force

    # Mark the calling rep(s) as "us" so speaker sides are attributed:
    .venv/bin/python scripts/clari_ingest.py --interviewer "Jane Rep"

Notes on Clari's /calls endpoint (observed against the live API):
  * The `from`/`to` and `status` query params were observed NOT to filter
    server-side; filtering is done client-side by this script.
  * Results are CLUSTERED BY STATUS, not sorted by time. In a large workspace the
    recorded calls (status POST_PROCESSING_DONE) form one contiguous block far
    down the list (e.g. ~240k deep). This script binary-searches to the start of
    that block instead of scanning every non-recorded call.
  * By default only recorded calls (POST_PROCESSING_DONE) are considered, since
    most calls (bot denied/disabled, scheduled, disqualified) have no transcript.
    Use --all-statuses to override.
  * Transcript segments look like {text, start, end, personId, annotations}. The
    speaker is the numeric `personId`, resolved against the call's participant
    lists: `users` (internal reps -> "us") and `externalParticipants` (customer
    -> "them"). Display names are derived from participant emails. The
    interviewer and contacts are inferred from this us/them split, so you usually
    do NOT need --interviewer.

Exit codes: 0 on success (including "nothing to do"), 1 on configuration or
fatal API errors.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

DEFAULT_CLARI_BASE_URL = "https://rest-api.copilot.clari.com"
DEFAULT_MOMBOARD_BASE_URL = "http://127.0.0.1:8000"
SOURCE_REF_PREFIX = "clari:"

# Clari call statuses that indicate a recording was processed and a transcript
# should exist. The /calls endpoint cannot filter by status server-side, so we
# filter client-side. Most calls in a workspace are non-recorded (bot denied,
# scheduled, disqualified, etc.) and carry an empty transcript.
RECORDED_STATUSES = frozenset({"POST_PROCESSING_DONE"})

# Field-name candidates for defensive parsing. Clari's public docs do not pin an
# exact transcript schema and it has varied across accounts/versions, so we probe
# a small set of well-known aliases rather than hard-coding one shape.
_TRANSCRIPT_CONTAINER_KEYS = ("transcript", "transcription", "transcripts", "segments")
_SEGMENT_LIST_KEYS = ("segments", "sentences", "entries", "monologues", "results", "items")
_SPEAKER_KEYS = (
    "speaker_name",
    "speaker",
    "person_name",
    "person",
    "name",
    "speaker_label",
    "user_name",
    "participant",
)
_TEXT_KEYS = ("text", "sentence", "transcript", "content", "value", "words")
_START_MS_KEYS = ("start_ms", "startMs", "start_time_ms", "offset_ms")
_START_S_KEYS = ("start", "start_time", "startTime", "ts", "timestamp", "time")
_CALL_ID_KEYS = ("id", "call_id", "callId", "_id", "uuid")
_CALL_TITLE_KEYS = ("title", "name", "call_title", "subject", "meeting_title")
_CALL_DATE_KEYS = (
    "time",  # confirmed: Clari /calls uses "time"
    "call_time",
    "callTime",
    "started_at",
    "start_time",
    "date",
    "created_at",
    "recorded_at",
    "scheduled_at",
)
_ACCOUNT_NAME_KEYS = ("account_name", "account", "company", "company_name", "deal_account")


# --------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file for keys that are not already set.

    Intentionally tiny (no python-dotenv dependency). Ignores comments, blank
    lines, and malformed entries. Existing environment values win.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    clari_base_url: str
    clari_api_key: str
    clari_api_password: str
    momboard_base_url: str
    momboard_email: str
    momboard_password: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            clari_base_url=os.environ.get("CLARI_BASE_URL", DEFAULT_CLARI_BASE_URL).rstrip("/"),
            clari_api_key=os.environ.get("CLARI_API_KEY", ""),
            # Clari's password value is documented as "API Password" (sent as the
            # X-Api-Password header). Accept CLARI_API_SECRET as an alias too.
            clari_api_password=(
                os.environ.get("CLARI_API_PASSWORD")
                or os.environ.get("CLARI_API_SECRET")
                or ""
            ),
            momboard_base_url=os.environ.get(
                "MOMBOARD_BASE_URL", DEFAULT_MOMBOARD_BASE_URL
            ).rstrip("/"),
            momboard_email=os.environ.get("MOMBOARD_EMAIL", ""),
            momboard_password=os.environ.get("MOMBOARD_PASSWORD", ""),
        )

    def validate(self, *, need_momboard: bool) -> list[str]:
        """Return a list of human-readable problems (empty means OK)."""
        problems: list[str] = []
        if not self.clari_api_key:
            problems.append("CLARI_API_KEY is not set")
        if not self.clari_api_password:
            problems.append("CLARI_API_PASSWORD is not set")
        if need_momboard:
            if not self.momboard_email:
                problems.append("MOMBOARD_EMAIL is not set")
            if not self.momboard_password:
                problems.append("MOMBOARD_PASSWORD is not set")
        return problems


# --------------------------------------------------------------------------------
# Transcript conversion (pure, unit-testable, no I/O)
# --------------------------------------------------------------------------------


@dataclass
class ConvertedTranscript:
    text: str  # "Name: text" formatted, one utterance per line
    speakers: list[str] = field(default_factory=list)
    utterance_count: int = 0
    us_speakers: list[str] = field(default_factory=list)
    them_speakers: list[str] = field(default_factory=list)


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _name_from_email(email: str) -> str:
    """Derive a human-ish display name from an email local-part.

    'jordan.doe@example.com' -> 'Jordan Doe'
    Falls back to the raw local-part if it doesn't look name-like.
    """
    local = email.split("@", 1)[0]
    parts = [p for p in local.replace("_", ".").replace("-", ".").split(".") if p]
    if not parts:
        return email
    # Skip machine-y locals (all digits / very long tokens).
    words = [p.capitalize() for p in parts if not p.isdigit()]
    return " ".join(words) if words else local


@dataclass
class Participant:
    name: str
    side: str  # "us" | "them"
    email: str | None = None


def build_participant_map(call: dict[str, Any]) -> dict[int, Participant]:
    """Map Clari ``personId`` -> Participant using the call's participant lists.

    Internal ``users`` are the interviewing team ("us"); ``externalParticipants``
    are the customer ("them"). Clari transcript segments reference speakers only
    by this numeric ``personId``.
    """
    mapping: dict[int, Participant] = {}

    def _add(entries: Any, side: str) -> None:
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            pid = entry.get("personId")
            if not isinstance(pid, int):
                continue
            email = entry.get("userEmail") or entry.get("email")
            if isinstance(email, str) and "@" in email:
                name = _name_from_email(email)
            else:
                name = f"{'Rep' if side == 'us' else 'Participant'} {pid}"
                email = None
            mapping[pid] = Participant(name=name, side=side, email=email)

    _add(call.get("users"), "us")
    _add(call.get("externalParticipants"), "them")
    return mapping


def _coerce_text(value: Any) -> str:
    """Turn a segment's text field into a clean single-line string.

    Handles the plain-string case and the "list of word objects" case
    (``[{"word": "hi"}, ...]`` or ``["hi", "there"]``).
    """
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        words: list[str] = []
        for item in value:
            if isinstance(item, str):
                words.append(item)
            elif isinstance(item, dict):
                w = _first_present(item, ("word", "text", "value"))
                if isinstance(w, str):
                    words.append(w)
        return " ".join(" ".join(words).split())
    return ""


def _extract_segments(details: dict[str, Any]) -> list[dict[str, Any]]:
    """Locate the list of transcript segments inside a call-details payload.

    Tries a container key holding a list, a container key holding a dict that
    itself holds a list, or a top-level list under a known key.
    """
    # Case 1: a top-level key is directly the segment list.
    for key in _TRANSCRIPT_CONTAINER_KEYS + _SEGMENT_LIST_KEYS:
        value = details.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value

    # Case 2: a container key holds a dict with a nested segment list.
    for key in _TRANSCRIPT_CONTAINER_KEYS:
        container = details.get(key)
        if isinstance(container, dict):
            for inner in _SEGMENT_LIST_KEYS:
                value = container.get(inner)
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return value

    # Case 3: sometimes call-details is nested under "call".
    call = details.get("call")
    if isinstance(call, dict):
        return _extract_segments(call)

    return []


def _segment_start_ms(seg: dict[str, Any]) -> int | None:
    ms = _first_present(seg, _START_MS_KEYS)
    if isinstance(ms, int | float):
        return int(ms)
    seconds = _first_present(seg, _START_S_KEYS)
    if isinstance(seconds, int | float):
        return int(float(seconds) * 1000)
    return None


def convert_transcript(
    details: dict[str, Any],
    *,
    participants: dict[int, Participant] | None = None,
    unknown_label: str = "Speaker",
) -> ConvertedTranscript:
    """Convert a Clari call-details payload into MomBoard ``Name: text`` format.

    Clari transcript segments reference the speaker by numeric ``personId``,
    resolved against ``participants`` (built with ``build_participant_map``). When
    a segment carries an explicit string speaker field instead, that is used as a
    fallback (keeps the parser robust to schema variation).

    Consecutive utterances by the same speaker are merged. Segments with no usable
    text are dropped. Speaker labels are sanitized so they don't break the
    ``Name: text`` grammar. ``us_speakers``/``them_speakers`` capture side
    attribution derived from the participant map.
    """
    if participants is None:
        call = details.get("call")
        participants = build_participant_map(call if isinstance(call, dict) else details)

    segments = _extract_segments(details)
    lines: list[str] = []
    seen_speakers: list[str] = []
    us_speakers: list[str] = []
    them_speakers: list[str] = []
    count = 0

    current_speaker: str | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal count
        if current_speaker and current_parts:
            text = " ".join(current_parts).strip()
            if text:
                lines.append(f"{current_speaker}: {text}")
                count += 1

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = _coerce_text(_first_present(seg, _TEXT_KEYS))
        if not text:
            continue

        speaker, side = _resolve_speaker(seg, participants, unknown_label)
        if speaker not in seen_speakers:
            seen_speakers.append(speaker)
            if side == "us" and speaker not in us_speakers:
                us_speakers.append(speaker)
            elif side == "them" and speaker not in them_speakers:
                them_speakers.append(speaker)

        if speaker != current_speaker:
            flush()
            current_speaker = speaker
            current_parts = [text]
        else:
            current_parts.append(text)

    flush()
    return ConvertedTranscript(
        text="\n".join(lines),
        speakers=seen_speakers,
        utterance_count=count,
        us_speakers=us_speakers,
        them_speakers=them_speakers,
    )


def _resolve_speaker(
    seg: dict[str, Any],
    participants: dict[int, Participant],
    unknown_label: str,
) -> tuple[str, str]:
    """Return (speaker_label, side) for a segment. side is 'us'|'them'|'unknown'."""
    pid = seg.get("personId")
    if isinstance(pid, int) and pid in participants:
        p = participants[pid]
        return _sanitize_speaker(p.name, unknown_label), p.side
    # Fallback: an explicit string speaker field (schema robustness).
    raw_speaker = _first_present(seg, _SPEAKER_KEYS)
    if raw_speaker is not None:
        return _sanitize_speaker(raw_speaker, unknown_label), "unknown"
    # Last resort: label by personId so distinct speakers stay distinct.
    if isinstance(pid, int):
        return f"Speaker {pid}", "unknown"
    return unknown_label, "unknown"


def _sanitize_speaker(raw: Any, unknown_label: str) -> str:
    if not isinstance(raw, str):
        return unknown_label
    # Collapse whitespace and strip characters that would corrupt the
    # "Name: text" grammar the MomBoard normalizer relies on.
    cleaned = " ".join(raw.replace(":", " ").split())
    return cleaned or unknown_label


# --------------------------------------------------------------------------------
# Call metadata helpers (pure)
# --------------------------------------------------------------------------------


def call_id_of(call: dict[str, Any]) -> str | None:
    value = _first_present(call, _CALL_ID_KEYS)
    return str(value) if value is not None else None


def call_title_of(call: dict[str, Any], call_id: str) -> str:
    value = _first_present(call, _CALL_TITLE_KEYS)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"Clari call {call_id}"


def call_happened_at_of(call: dict[str, Any]) -> str | None:
    """Return an ISO-8601 timestamp string suitable for MomBoard, or None."""
    value = _first_present(call, _CALL_DATE_KEYS)
    if value is None:
        return None
    # Epoch (seconds or milliseconds).
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            # Accept trailing "Z".
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.isoformat()
        except ValueError:
            return text  # Pass through; MomBoard will validate/ignore.
    return None


def account_name_of(call: dict[str, Any]) -> str | None:
    value = _first_present(call, _ACCOUNT_NAME_KEYS)
    if isinstance(value, dict):
        value = _first_present(value, ("name", "title"))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def source_ref_for(call_id: str) -> str:
    return f"{SOURCE_REF_PREFIX}{call_id}"


# --------------------------------------------------------------------------------
# Clari client
# --------------------------------------------------------------------------------


class ClariClient:
    def __init__(self, cfg: Config, *, timeout: float = 60.0) -> None:
        self._client = httpx.Client(
            base_url=cfg.clari_base_url,
            headers={
                "X-Api-Key": cfg.clari_api_key,
                "X-Api-Password": cfg.clari_api_password,
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    def __enter__(self) -> ClariClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def _get_with_retry(
        self, path: str, params: dict[str, Any], *, retries: int = 4
    ) -> httpx.Response:
        """GET with retry/backoff on transient failures (5xx, 429, timeouts).

        Clari occasionally returns 502/503 during deep pagination; a single
        transient error must not abort a long import. 4xx (other than 429) are
        raised immediately since they won't succeed on retry.
        """
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self._client.get(path, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"{resp.status_code} from {path}",
                        request=resp.request,
                        response=resp,
                    )
                    if attempt < retries - 1:
                        time.sleep(2**attempt)  # 1s, 2s, 4s
                        continue
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                    continue
        assert last_exc is not None
        raise last_exc

    def _page(self, skip: int, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        resp = self._get_with_retry("/calls", {"limit": limit, "skip": skip})
        payload = resp.json()
        if isinstance(payload, dict):
            return (payload.get("calls") or [], payload.get("pagination") or {})
        return (payload or [], {})

    def _status_at(self, skip: int) -> str | None:
        page, _ = self._page(skip, 1)
        return page[0].get("status") if page and isinstance(page[0], dict) else None

    def _seek_status_start(self, target: str, total: int) -> int | None:
        """Binary-search the first index whose call has status ``target``.

        Clari's /calls list is clustered/ordered by status (observed stable), so
        recorded calls (e.g. POST_PROCESSING_DONE) sit in one contiguous block
        ~240k deep. Rather than linearly scanning past hundreds of thousands of
        non-recorded calls, we locate the block boundary with ~log2(total) probes.

        Returns the first skip index of the block, or None if not found.
        """
        # Coarse scan to land anywhere inside the target block.
        step = max(total // 60, 1000)
        anchor: int | None = None
        for skip in range(0, total, step):
            if self._status_at(skip) == target:
                anchor = skip
                break
        if anchor is None:
            return None
        # Binary-search the lower boundary of the contiguous block.
        lo, hi = 0, anchor
        while lo < hi:
            mid = (lo + hi) // 2
            if self._status_at(mid) == target:
                hi = mid
            else:
                lo = mid + 1
        return lo

    def list_calls(
        self,
        from_date: str | None,
        to_date: str | None,
        *,
        max_calls: int | None = None,
        statuses: set[str] | None = None,
        max_scan: int = 5000,
    ) -> list[dict[str, Any]]:
        """List calls matching the filters, up to ``max_calls``.

        Observed behaviour of Clari's ``/calls`` (see module docstring):
          * ``from``/``to`` query params do NOT filter server-side.
          * Results are ordered/clustered by STATUS, not by time. Recorded calls
            (``POST_PROCESSING_DONE``) form one contiguous block far down the list
            (~240k deep in a large workspace).
          * The workspace can hold hundreds of thousands of calls.

        Strategy: when filtering by a single status, binary-search to the start of
        that status block and page from there (fast). Otherwise scan from the top.
        Either way we bound the crawl with ``max_calls`` (matches collected) and
        ``max_scan`` (calls examined past the start point). Date filtering is
        applied client-side on the ``time`` field.
        """
        # Determine a starting skip.
        start_skip = 0
        if statuses is not None and len(statuses) == 1:
            _, pagination = self._page(0, 1)
            total = pagination.get("matched")
            if isinstance(total, int) and total > 0:
                target = next(iter(statuses))
                found = self._seek_status_start(target, total)
                if found is not None:
                    start_skip = found

        collected: list[dict[str, Any]] = []
        skip = start_skip
        page_size = 100
        scanned = 0

        while scanned < max_scan:
            page, pagination = self._page(skip, page_size)
            hit_other_status = False
            for call in page:
                if not isinstance(call, dict):
                    continue
                scanned += 1
                if statuses is not None and call.get("status") not in statuses:
                    # When we seeked into a single-status block, leaving it means
                    # we've exhausted the recorded calls -> stop.
                    if start_skip > 0:
                        hit_other_status = True
                        break
                    continue
                iso = call_happened_at_of(call)
                day = iso[:10] if iso else None
                if from_date and day and day < from_date:
                    continue
                if to_date and day and day > to_date:
                    continue
                collected.append(call)
                if max_calls is not None and len(collected) >= max_calls:
                    return collected[:max_calls]

            if hit_other_status:
                break
            has_more = pagination.get("hasMore")
            next_skip = pagination.get("nextPageSkip")
            if not has_more or not page:
                break
            skip = next_skip if isinstance(next_skip, int) else skip + page_size
            if skip > 1_000_000:  # hard safety stop
                break

        return collected

    def get_call_details(self, call_id: str) -> dict[str, Any]:
        resp = self._get_with_retry("/call-details", {"id": call_id})
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected call-details payload for {call_id}: {type(payload)}")
        return payload


# --------------------------------------------------------------------------------
# MomBoard client
# --------------------------------------------------------------------------------


class MomBoardClient:
    def __init__(self, cfg: Config, *, timeout: float = 60.0) -> None:
        self._cfg = cfg
        self._client = httpx.Client(base_url=cfg.momboard_base_url, timeout=timeout)

    def __enter__(self) -> MomBoardClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def login(self) -> None:
        resp = self._client.post(
            "/auth/login",
            json={"email": self._cfg.momboard_email, "password": self._cfg.momboard_password},
        )
        if resp.status_code == 401:
            raise RuntimeError("MomBoard login failed: invalid credentials")
        resp.raise_for_status()
        # The session cookie is stored on the client cookie jar automatically.

    def fetch_existing_source_refs(self, prefix: str = SOURCE_REF_PREFIX) -> set[str]:
        """Return the set of existing conversation ``meta.source_ref`` values.

        The list endpoint's ``q=`` free-text search only matches title/transcript,
        NOT the ``meta`` JSON, so we cannot prefilter by source_ref. Instead we
        page the full conversation list once and collect source_refs from ``meta``.
        Only refs starting with ``prefix`` (e.g. "clari:") are returned.
        """
        refs: set[str] = set()
        offset = 0
        limit = 200
        while True:
            resp = self._client.get(
                "/api/conversations", params={"limit": limit, "offset": offset}
            )
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("items", [])
            for item in items:
                meta = item.get("meta") or {}
                ref = meta.get("source_ref") if isinstance(meta, dict) else None
                if isinstance(ref, str) and ref.startswith(prefix):
                    refs.add(ref)
            total = payload.get("total", 0)
            offset += limit
            if offset >= total or not items:
                break
        return refs

    def create_conversation(self, body: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.post("/api/conversations", json=body)
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result


# --------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------


def build_conversation_body(
    call: dict[str, Any],
    details: dict[str, Any],
    converted: ConvertedTranscript,
    *,
    call_id: str,
    interviewer: str | None,
) -> dict[str, Any]:
    """Assemble the MomBoard ConversationCreate payload for one call.

    ``call`` is the summary object from /calls; ``details`` is the /call-details
    payload (transcript nested under ``details['call']``). We merge the nested
    call object so metadata is available regardless of which response carried it.
    """
    merged: dict[str, Any] = {}
    if isinstance(details.get("call"), dict):
        merged.update(details["call"])
    merged.update(call)  # summary values win where both exist

    meta: dict[str, Any] = {
        "source": "clari",
        "source_ref": source_ref_for(call_id),
        "clari_call_id": call_id,
        "clari_speakers": converted.speakers,
        "clari_us_speakers": converted.us_speakers,
        "clari_them_speakers": converted.them_speakers,
    }
    # Confirmed-present Clari fields worth keeping for filtering/context.
    for src_key, meta_key in (
        ("status", "clari_status"),
        ("disposition", "clari_disposition"),
        ("call_review_page_url", "clari_review_url"),
        ("deal_name", "deal_name"),
        ("deal_stage_before_call", "deal_stage"),
        ("deal_value", "deal_value"),
        ("type", "clari_call_type"),
    ):
        value = merged.get(src_key)
        if value not in (None, "", [], {}):
            meta[meta_key] = value

    body: dict[str, Any] = {
        "title": call_title_of(merged, call_id),
        "transcript": converted.text,
        "transcript_format": "name_colon",
        "meta": meta,
    }
    happened_at = call_happened_at_of(merged)
    if happened_at:
        body["happened_at"] = happened_at

    # Interviewer ("us"): prefer an explicit override, else the first internal
    # speaker resolved from the transcript. This drives MomBoard's side
    # assignment in the normalizer.
    resolved_interviewer = interviewer or (
        converted.us_speakers[0] if converted.us_speakers else None
    )
    if resolved_interviewer:
        body["interviewer"] = resolved_interviewer

    account = account_name_of(merged)
    if account:
        body["company"] = {"name": account}

    # Contacts ("them"): prefer the external participants resolved from the
    # transcript/participant map (real names). Clari's contact_names field was
    # observed to contain junk ("SalesloftNull"), so only use it as a fallback.
    raw_contacts = list(converted.them_speakers)
    if not raw_contacts:
        contact_names = merged.get("contact_names")
        if isinstance(contact_names, list):
            raw_contacts = [
                n.strip()
                for n in contact_names
                if isinstance(n, str) and n.strip() and "null" not in n.lower()
            ]
    # Dedupe case-insensitively: MomBoard resolves contacts by name and enforces a
    # UNIQUE (conversation_id, contact_id) link, so duplicate names in one payload
    # (e.g. two participants mapping to the same display name) would 500 the create.
    contacts: list[dict[str, Any]] = []
    seen_contact_keys: set[str] = set()
    for name in raw_contacts:
        key = name.strip().lower()
        if key and key not in seen_contact_keys:
            seen_contact_keys.add(key)
            contacts.append({"name": name})
    if contacts:
        body["contacts"] = contacts
    return body


def default_date_range(days: int = 30) -> tuple[str, str]:
    today = date.today()
    start = today - timedelta(days=days)
    return start.isoformat(), today.isoformat()


@dataclass
class RunStats:
    considered: int = 0
    imported: int = 0
    skipped_existing: int = 0
    skipped_empty: int = 0
    errors: int = 0


def run(args: argparse.Namespace, cfg: Config) -> RunStats:
    stats = RunStats()
    momboard: MomBoardClient | None = None

    try:
        existing_refs: set[str] = set()
        if not args.dry_run:
            momboard = MomBoardClient(cfg)
            momboard.login()
            print(f"Logged in to MomBoard at {cfg.momboard_base_url} as {cfg.momboard_email}")
            if not args.force:
                existing_refs = momboard.fetch_existing_source_refs()
                print(f"{len(existing_refs)} Clari conversation(s) already in MomBoard.")

        with ClariClient(cfg) as clari:
            if args.call_id:
                call_ids = [args.call_id]
                calls_by_id: dict[str, dict[str, Any]] = {args.call_id: {}}
            else:
                from_date, to_date = args.date_from, args.date_to
                cap = args.max_calls
                statuses = None if args.all_statuses else RECORDED_STATUSES
                status_note = (
                    "any status" if args.all_statuses
                    else f"recorded only ({', '.join(sorted(RECORDED_STATUSES))})"
                )
                print(
                    f"Listing Clari calls from {from_date} to {to_date} "
                    f"(max {cap}, {status_note}, scanning up to {args.max_scan}) ..."
                )
                calls = clari.list_calls(
                    from_date,
                    to_date,
                    max_calls=cap,
                    statuses=statuses,
                    max_scan=args.max_scan,
                )
                calls_by_id = {}
                call_ids = []
                for call in calls:
                    cid = call_id_of(call)
                    if cid:
                        calls_by_id[cid] = call
                        call_ids.append(cid)
                print(f"Found {len(call_ids)} matching call(s) to consider.")

            for cid in call_ids:
                stats.considered += 1
                call = calls_by_id.get(cid, {})
                source_ref = source_ref_for(cid)

                if not args.dry_run and not args.force:
                    if source_ref in existing_refs:
                        stats.skipped_existing += 1
                        print(f"  skip (already imported): {source_ref}")
                        continue

                try:
                    details = clari.get_call_details(cid)
                except httpx.HTTPStatusError as exc:
                    stats.errors += 1
                    print(f"  error fetching {cid}: {exc}", file=sys.stderr)
                    continue

                converted = convert_transcript(details)
                if converted.utterance_count == 0:
                    stats.skipped_empty += 1
                    # Surface the Clari status so common causes (e.g. the
                    # recording bot being denied entry -> BOTJOIN_DENIED) are
                    # visible rather than looking like a parser failure.
                    nested = details.get("call") if isinstance(details.get("call"), dict) else {}
                    status = call.get("status") or nested.get("status") or "unknown"
                    print(f"  skip (no transcript, status={status}): {source_ref}")
                    continue

                body = build_conversation_body(
                    call, details, converted, call_id=cid, interviewer=args.interviewer
                )

                if args.dry_run:
                    print(
                        f"  would import {source_ref}: '{body['title']}' "
                        f"({converted.utterance_count} utterances, "
                        f"speakers={converted.speakers})"
                    )
                    stats.imported += 1
                    continue

                assert momboard is not None
                try:
                    created = momboard.create_conversation(body)
                except httpx.HTTPStatusError as exc:
                    stats.errors += 1
                    detail = _http_error_detail(exc)
                    print(f"  error creating conversation for {cid}: {detail}", file=sys.stderr)
                    continue
                stats.imported += 1
                existing_refs.add(source_ref)
                print(
                    f"  imported {source_ref} -> conversation #{created.get('id')} "
                    f"('{created.get('title')}', status={created.get('status')})"
                )
    finally:
        if momboard is not None:
            momboard.__exit__()

    return stats


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        payload = exc.response.json()
        if isinstance(payload, dict) and "detail" in payload:
            return f"{exc.response.status_code} {payload['detail']}"
    except Exception:
        pass
    return str(exc)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clari_ingest",
        description="Ingest Clari Copilot calls into MomBoard as conversations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default_from, default_to = default_date_range()
    parser.add_argument(
        "--from",
        dest="date_from",
        default=default_from,
        help=f"Start date yyyy-MM-dd (default: {default_from}, 30 days ago).",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        default=default_to,
        help=f"End date yyyy-MM-dd (default: {default_to}, today).",
    )
    parser.add_argument(
        "--call-id",
        dest="call_id",
        default=None,
        help="Import a single call by its Clari call id (ignores --from/--to).",
    )
    parser.add_argument(
        "--max-calls",
        dest="max_calls",
        type=int,
        default=50,
        help=(
            "Maximum number of matching calls to import. The Clari workspace can "
            "hold hundreds of thousands of calls, so this caps the result set. "
            "Use --max-calls 1 to grab just the latest recorded call. Default: 50."
        ),
    )
    parser.add_argument(
        "--max-scan",
        dest="max_scan",
        type=int,
        default=5000,
        help=(
            "Maximum number of calls to examine while searching for matches. "
            "Recorded calls are a small fraction of the workspace and are not "
            "time-ordered, so we scan up to this many. Default: 5000."
        ),
    )
    parser.add_argument(
        "--all-statuses",
        dest="all_statuses",
        action="store_true",
        help=(
            "Consider calls of any status, not just recorded/transcribed ones. "
            f"By default only {sorted(RECORDED_STATUSES)} are considered."
        ),
    )
    parser.add_argument(
        "--interviewer",
        default=os.environ.get("CLARI_INTERVIEWER"),
        help="Rep/interviewer name; used to attribute speaker sides (us/them).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be imported without writing to MomBoard.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Import even if a conversation with the same source_ref exists.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Load .env from the project root (parent of scripts/) for convenience.
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    problems = cfg.validate(need_momboard=not args.dry_run)
    if problems:
        print("Configuration error(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nSet the required environment variables (see the module docstring) "
            "or add them to .env.",
            file=sys.stderr,
        )
        return 1

    try:
        stats = run(args, cfg)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1

    print(
        "\nDone. "
        f"considered={stats.considered} "
        f"imported={stats.imported} "
        f"skipped_existing={stats.skipped_existing} "
        f"skipped_empty={stats.skipped_empty} "
        f"errors={stats.errors}"
    )
    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
