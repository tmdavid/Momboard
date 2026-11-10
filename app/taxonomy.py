"""Custom-taxonomy helpers shared by the API, seed, and tooling.

Kept dependency-free (stdlib ``difflib`` only) so the private tag-import script
can reuse the same near-duplicate detection the backend uses.
"""
from __future__ import annotations

from difflib import SequenceMatcher

# Two category labels at or above this similarity are flagged as likely
# duplicates (e.g. "channel" vs "channels", "pricing" vs "price").
NEAR_DUPLICATE_THRESHOLD = 0.82


def normalize_category(value: str | None) -> str | None:
    """Normalize a free-text category: trim, collapse case. ``None``/blank -> None."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def find_near_duplicate_category(
    candidate: str, existing: list[str], *, threshold: float = NEAR_DUPLICATE_THRESHOLD
) -> str | None:
    """Return an existing category that is a near-duplicate of ``candidate``.

    An exact (case-insensitive) match is NOT a near-duplicate — it is the same
    category and should be reused silently. Returns the first existing label
    whose similarity meets ``threshold`` but is not an exact match, else None.
    """
    cand = normalize_category(candidate)
    if cand is None:
        return None
    best: tuple[float, str] | None = None
    for other in existing:
        norm = normalize_category(other)
        if norm is None or norm.casefold() == cand.casefold():
            continue
        score = _similarity(cand, norm)
        if score >= threshold and (best is None or score > best[0]):
            best = (score, other)
    return best[1] if best else None
