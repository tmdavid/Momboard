"""Deep links back into MomBoard, so a model can cite its sources."""

from __future__ import annotations

import re
from typing import Any

_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")
_SCHEMES = {"http", "https"}


def _clean(base: str) -> str:
    return base.rstrip("/")


def base_url(configured: str, scope: dict[str, Any]) -> str:
    """The public address of this MomBoard.

    ``PUBLIC_BASE_URL`` wins. Otherwise it is derived from the request, honouring a reverse proxy's
    ``X-Forwarded-*`` headers but only when they are well-formed (no markup, no odd schemes).
    """
    if configured.strip():
        return _clean(configured.strip())
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    scheme = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if scheme not in _SCHEMES:
        scheme = scope.get("scheme", "http") if scope.get("scheme") in _SCHEMES else "http"
    host = headers.get("x-forwarded-host", "").split(",")[0].strip()
    if not _HOST.match(host):
        host = headers.get("host", "").strip()
    if not _HOST.match(host):
        host = "localhost"
    return f"{scheme}://{host}"


def conversation(base: str, conversation_id: int) -> str:
    return f"{_clean(base)}/conversations/{conversation_id}"


def quote(base: str, conversation_id: int, highlight_id: int) -> str:
    return f"{conversation(base, conversation_id)}?highlight={highlight_id}"


def hypothesis(base: str, hypothesis_id: int) -> str:
    return f"{_clean(base)}/hypotheses?hypothesis={hypothesis_id}"


def decision(base: str, decision_id: int) -> str:
    return f"{_clean(base)}/decisions?decision={decision_id}"


def summary(base: str, synthesis_id: int) -> str:
    return f"{_clean(base)}/summaries?summary={synthesis_id}"
