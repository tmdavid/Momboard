"""Strip contact emails and phone numbers from free text before it leaves MomBoard.

Quotes and transcripts are customer speech and can contain someone's email or number. Tool output
must never carry those (they are not needed to cite a source), so they are replaced by a marker.
Ordinary numbers (prices, counts, dates, versions) are left alone: a candidate is treated as a phone
number only when it has at least nine digits.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_PHONE_CANDIDATE = re.compile(r"(?<![\w.,])\+?\(?\d[\d\s().\-]{6,}\d(?![\w])")
_MIN_PHONE_DIGITS = 9
_DATE_LIKE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")


def _phone(match: re.Match[str]) -> str:
    text = match.group(0)
    if _DATE_LIKE.match(text.strip()):
        return text
    digits = sum(ch.isdigit() for ch in text)
    if digits < _MIN_PHONE_DIGITS or digits > 15:
        return text
    # "1,234,567"-style grouped numbers have no phone separators: leave them.
    if re.fullmatch(r"\d{1,3}(,\d{3})+", text.strip()):
        return text
    return "[phone removed]"


def redact(text: str | None) -> str | None:
    if not text:
        return text
    text = _EMAIL.sub("[email removed]", text)
    return _PHONE_CANDIDATE.sub(_phone, text)
