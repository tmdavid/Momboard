"""What the audit log records about a call: argument names and short values, never transcript text."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import McpCall

RETENTION_DAYS = 90
MAX_VALUE_CHARS = 40
MAX_SUMMARY_CHARS = 120
MAX_LIST_ITEMS = 5
_SECRET_KEYS = re.compile(r"token|secret|password|authorization|key", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _short(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        shown = ",".join(_short(v) for v in value[:MAX_LIST_ITEMS])
        return f"[{shown}{',…' if len(value) > MAX_LIST_ITEMS else ''}]"
    text = _CONTROL.sub(" ", str(value))
    return text if len(text) <= MAX_VALUE_CHARS else text[: MAX_VALUE_CHARS - 1] + "…"


def summarize_args(arguments: dict[str, Any] | None) -> str:
    """``name=value`` pairs, with long values cut so free text and transcripts cannot end up here."""
    parts = []
    for name, value in (arguments or {}).items():
        if value is None or value == "" or value == []:
            continue
        parts.append(f"{name}=***" if _SECRET_KEYS.search(name) else f"{name}={_short(value)}")
    summary = " ".join(parts)
    return summary if len(summary) <= MAX_SUMMARY_CHARS else summary[: MAX_SUMMARY_CHARS - 1] + "…"


async def record(
    db: AsyncSession,
    *,
    token_id: int | None,
    token_prefix: str | None,
    tool: str,
    arguments: dict[str, Any] | None,
    status: str,
    duration_ms: int,
    result_count: int | None = None,
) -> None:
    db.add(
        McpCall(
            token_id=token_id,
            token_prefix=token_prefix,
            tool=tool[:100],
            args_summary=summarize_args(arguments),
            status=status,
            duration_ms=max(0, int(duration_ms)),
            result_count=result_count,
        )
    )
    await db.flush()


async def prune(db: AsyncSession, *, days: int = RETENTION_DAYS) -> int:
    """Delete audit rows older than ``days`` (90 by default). Returns how many were removed."""
    result = await db.execute(delete(McpCall).where(McpCall.created_at < datetime.now(UTC) - timedelta(days=days)))
    return int(result.rowcount or 0)
