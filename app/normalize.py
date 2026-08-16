"""Deterministic transcript normalizer.

Handles VTT and "Name: text" formats without LLM.
Raises NeedsLLMNormalization for messy pastes that need AI help.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.llm.client import LLMClient


class NeedsLLMNormalization(Exception):  # noqa: N818 — spec-defined name
    """Raised when a transcript cannot be deterministically parsed."""

    pass


@dataclass
class NormalizedUtterance:
    """A single utterance extracted from a transcript."""

    idx: int
    speaker_label: str
    speaker_side: str  # "us", "them", "unknown"
    text: str
    start_ms: int | None = None


def _parse_vtt(raw: str, interviewer: str | None = None) -> list[NormalizedUtterance]:
    """Parse WebVTT format transcript."""
    lines = raw.strip().split("\n")
    utterances: list[NormalizedUtterance] = []
    idx = 0

    # Skip WEBVTT header
    i = 0
    while i < len(lines) and not re.match(r"\d{2}:\d{2}", lines[i]):
        i += 1

    current_time_ms: int | None = None
    current_speaker: str | None = None
    current_text_parts: list[str] = []

    while i < len(lines):
        line = lines[i].strip()

        # Timestamp line: 00:00:01.000 --> 00:00:04.000
        time_match = re.match(
            r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}", line
        )
        if time_match:
            # Save previous utterance if exists
            if current_speaker and current_text_parts:
                text = " ".join(current_text_parts).strip()
                if text:
                    side = _assign_side(current_speaker, interviewer)
                    utterances.append(
                        NormalizedUtterance(
                            idx=idx,
                            speaker_label=current_speaker,
                            speaker_side=side,
                            text=text,
                            start_ms=current_time_ms,
                        )
                    )
                    idx += 1
                    current_text_parts = []

            h, m, s, ms = (
                int(time_match.group(1)),
                int(time_match.group(2)),
                int(time_match.group(3)),
                int(time_match.group(4)),
            )
            current_time_ms = h * 3600000 + m * 60000 + s * 1000 + ms
            i += 1
            continue

        # Cue number line (just digits) — skip
        if re.match(r"^\d+$", line):
            i += 1
            continue

        # Empty line — utterance boundary
        if not line:
            i += 1
            continue

        # Content line — may start with speaker label "<v Speaker>"
        v_match = re.match(r"<v\s+([^>]+)>(.*)", line)
        if v_match:
            new_speaker = v_match.group(1).strip()
            text_part = re.sub(r"</v>", "", v_match.group(2)).strip()

            if new_speaker != current_speaker and current_speaker and current_text_parts:
                text = " ".join(current_text_parts).strip()
                if text:
                    side = _assign_side(current_speaker, interviewer)
                    utterances.append(
                        NormalizedUtterance(
                            idx=idx,
                            speaker_label=current_speaker,
                            speaker_side=side,
                            text=text,
                            start_ms=current_time_ms,
                        )
                    )
                    idx += 1
                    current_text_parts = []

            current_speaker = new_speaker
            if text_part:
                current_text_parts.append(text_part)
        else:
            # Plain text line — could have "Speaker: text" format within VTT
            colon_match = re.match(r"^([A-Za-z][A-Za-z\s]{0,30}):\s+(.+)", line)
            if colon_match:
                new_speaker = colon_match.group(1).strip()
                text_part = colon_match.group(2).strip()

                if new_speaker != current_speaker and current_speaker and current_text_parts:
                    text = " ".join(current_text_parts).strip()
                    if text:
                        side = _assign_side(current_speaker, interviewer)
                        utterances.append(
                            NormalizedUtterance(
                                idx=idx,
                                speaker_label=current_speaker,
                                speaker_side=side,
                                text=text,
                                start_ms=current_time_ms,
                            )
                        )
                        idx += 1
                        current_text_parts = []

                current_speaker = new_speaker
                if text_part:
                    current_text_parts.append(text_part)
            else:
                # Plain text without speaker — default to "Speaker" for Whisper-style VTT
                if current_speaker is None:
                    current_speaker = "Speaker"
                if line:
                    current_text_parts.append(line)

        i += 1

    # Don't forget the last utterance
    if current_speaker and current_text_parts:
        text = " ".join(current_text_parts).strip()
        if text:
            side = _assign_side(current_speaker, interviewer)
            utterances.append(
                NormalizedUtterance(
                    idx=idx,
                    speaker_label=current_speaker,
                    speaker_side=side,
                    text=text,
                    start_ms=current_time_ms,
                )
            )

    return utterances


def _parse_name_colon(raw: str, interviewer: str | None = None) -> list[NormalizedUtterance]:
    """Parse 'Name: text' format transcript."""
    lines = raw.strip().split("\n")

    # Some labeled exports begin with a metadata block such as Call/Date/Interviewer,
    # separated from dialogue by a blank line. Do not treat those fields as speakers.
    first_blank = next((i for i, line in enumerate(lines) if not line.strip()), None)
    if first_blank is not None and first_blank >= 2:
        metadata_keys = {
            "call",
            "company",
            "date",
            "interviewee",
            "interviewer",
            "location",
            "participants",
            "title",
        }
        preamble_labels: list[str] = []
        for line in lines[:first_blank]:
            match = re.match(r"^([A-Za-z][A-Za-z0-9\s._-]{0,40}):\s+.+", line.strip())
            if match:
                preamble_labels.append(match.group(1).strip().lower())
        if len(preamble_labels) == first_blank and all(
            label in metadata_keys for label in preamble_labels
        ):
            lines = lines[first_blank + 1 :]

    utterances: list[NormalizedUtterance] = []
    idx = 0
    current_speaker: str | None = None
    current_text_parts: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Match "Speaker: text" pattern
        colon_match = re.match(r"^([A-Za-z][A-Za-z0-9\s._-]{0,40}):\s+(.+)", line)
        if colon_match:
            # Save previous
            if current_speaker and current_text_parts:
                text = " ".join(current_text_parts).strip()
                if text:
                    side = _assign_side(current_speaker, interviewer)
                    utterances.append(
                        NormalizedUtterance(
                            idx=idx,
                            speaker_label=current_speaker,
                            speaker_side=side,
                            text=text,
                        )
                    )
                    idx += 1
                    current_text_parts = []

            current_speaker = colon_match.group(1).strip()
            current_text_parts = [colon_match.group(2).strip()]
        else:
            # Continuation line
            if current_speaker:
                current_text_parts.append(line)

    # Last one
    if current_speaker and current_text_parts:
        text = " ".join(current_text_parts).strip()
        if text:
            side = _assign_side(current_speaker, interviewer)
            utterances.append(
                NormalizedUtterance(
                    idx=idx,
                    speaker_label=current_speaker,
                    speaker_side=side,
                    text=text,
                )
            )

    return utterances


def _assign_side(speaker: str, interviewer: str | None) -> str:
    """Assign speaker side based on interviewer name."""
    if not interviewer:
        return "unknown"
    if speaker.lower().strip() == interviewer.lower().strip():
        return "us"
    # Also check if the interviewer name is contained in the speaker label
    if interviewer.lower() in speaker.lower():
        return "us"
    return "them"


def _detect_format(raw: str) -> str:
    """Auto-detect transcript format."""
    lines = raw.strip().split("\n")

    # Check for VTT header
    if lines and "WEBVTT" in lines[0]:
        return "vtt"

    # Check for timestamp patterns
    if any(re.match(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->", line) for line in lines[:20]):
        return "vtt"

    # Check for "Name: text" density
    colon_lines = sum(
        1 for line in lines[:50] if re.match(r"^[A-Za-z][A-Za-z0-9\s._-]{0,40}:\s+.+", line.strip())
    )
    non_empty = sum(1 for line in lines[:50] if line.strip())
    if non_empty > 0 and colon_lines / non_empty > 0.3:
        return "name_colon"

    # Can't determine — needs LLM
    return "unknown"


def normalize(
    raw: str, fmt: str = "auto", interviewer: str | None = None
) -> list[NormalizedUtterance]:
    """Normalize a transcript into structured utterances.

    Args:
        raw: Raw transcript text
        fmt: Format hint — "vtt", "name_colon", or "auto"
        interviewer: Name of the interviewer for side assignment

    Returns:
        List of normalized utterances

    Raises:
        NeedsLLMNormalization: When format can't be determined or parsed
    """
    if fmt == "auto":
        fmt = _detect_format(raw)

    if fmt == "vtt":
        result = _parse_vtt(raw, interviewer)
        if not result:
            raise NeedsLLMNormalization("VTT parsing produced no utterances")
        return result
    elif fmt in {"name_colon", "labeled"}:
        result = _parse_name_colon(raw, interviewer)
        if not result:
            raise NeedsLLMNormalization("Name:colon parsing produced no utterances")
        return result
    else:
        raise NeedsLLMNormalization(
            f"Cannot deterministically parse transcript with format '{fmt}'"
        )


async def normalize_with_llm_fallback(
    raw: str,
    interviewer: str | None,
    llm_client: LLMClient,
    fmt: str = "auto",
) -> list[NormalizedUtterance]:
    """Normalize a transcript, falling back to LLM if deterministic parsing fails.

    Args:
        raw: Raw transcript text.
        interviewer: Name of the interviewer for side assignment.
        llm_client: An LLM client implementing the structured() protocol.
        fmt: Format hint — "vtt", "name_colon", or "auto".

    Returns:
        List of normalized utterances (from deterministic or LLM path).
    """
    from app.llm.schemas import NormalizerOutput

    try:
        return normalize(raw, fmt=fmt, interviewer=interviewer)
    except NeedsLLMNormalization:
        pass

    # Fall back to LLM normalization
    input_data = {
        "interviewer": interviewer or "Unknown",
        "transcript": raw,
    }
    result, _envelope = await llm_client.structured("normalizer", input_data, NormalizerOutput)

    # Convert LLM output to NormalizedUtterance list
    utterances: list[NormalizedUtterance] = []
    for u in result.utterances:
        utterances.append(
            NormalizedUtterance(
                idx=u.idx,
                speaker_label=u.speaker_label,
                speaker_side=u.speaker_side,
                text=u.text,
            )
        )
    return utterances
