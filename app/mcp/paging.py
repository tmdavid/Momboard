"""Paging for tool results: a default of 20, a maximum of 50, and an opaque cursor."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
_PREFIX = "o:"


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"{_PREFIX}{offset}".encode()).decode().rstrip("=")


def _decode(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        if not raw.startswith(_PREFIX):
            raise ValueError
        offset = int(raw[len(_PREFIX):])
        if offset < 0:
            raise ValueError
        return offset
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ToolError(
            "Invalid cursor. Pass the exact next_cursor from the previous result, or omit it to start over."
        ) from exc


def page(limit: int | None, cursor: str | None) -> tuple[int, int]:
    """Validate ``limit`` and ``cursor``; returns ``(limit, offset)``."""
    if limit is None:
        limit = DEFAULT_LIMIT
    if not 1 <= limit <= MAX_LIMIT:
        raise ToolError(f"limit must be between 1 and {MAX_LIMIT} (got {limit}).")
    offset = 0 if not cursor else _decode(cursor.strip())  # a blank (whitespace) cursor is invalid, not "start"
    return limit, offset


def next_cursor(*, offset: int, limit: int, total: int) -> str | None:
    return encode_cursor(offset + limit) if offset + limit < total else None


def envelope(items: list[Any], *, offset: int, limit: int, total: int) -> dict[str, Any]:
    return {"items": items, "total": total, "next_cursor": next_cursor(offset=offset, limit=limit, total=total)}
