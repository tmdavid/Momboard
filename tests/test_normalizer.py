"""T06: Deterministic normalizer tests."""

from pathlib import Path

import pytest

from app.normalize import NeedsLLMNormalization, normalize

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_vtt_parsed_to_ordered_utterances_with_timestamps():
    utts = normalize(read_fixture("good_interview.vtt"), fmt="vtt", interviewer="David")
    assert len(utts) > 0
    assert utts[0].idx == 0
    assert utts[0].start_ms is not None
    assert all(u.speaker_label for u in utts)
    # Check ordering
    for i, u in enumerate(utts):
        assert u.idx == i


def test_vtt_speakers_extracted():
    utts = normalize(read_fixture("good_interview.vtt"), fmt="vtt", interviewer="David")
    speakers = {u.speaker_label for u in utts}
    assert "David" in speakers
    assert "Maria" in speakers


def test_name_colon_format_parsed_and_speakers_extracted():
    utts = normalize(read_fixture("compliment_disaster.txt"), fmt="name_colon", interviewer="David")
    speakers = {u.speaker_label for u in utts}
    assert "David" in speakers
    assert "Customer" in speakers
    assert len(utts) == 14  # 14 lines of dialogue


def test_speaker_side_assignment_from_interviewer_name():
    utts = normalize(read_fixture("good_interview.vtt"), fmt="vtt", interviewer="David")
    david_utts = [u for u in utts if u.speaker_label == "David"]
    maria_utts = [u for u in utts if u.speaker_label == "Maria"]
    assert all(u.speaker_side == "us" for u in david_utts)
    assert all(u.speaker_side == "them" for u in maria_utts)


def test_messy_paste_raises_needs_llm():
    with pytest.raises(NeedsLLMNormalization):
        normalize(read_fixture("messy_paste.txt"), fmt="auto")


def test_format_autodetection_vtt():
    raw = read_fixture("good_interview.vtt")
    utts = normalize(raw, fmt="auto", interviewer="David")
    assert len(utts) > 0


def test_format_autodetection_name_colon():
    raw = read_fixture("compliment_disaster.txt")
    utts = normalize(raw, fmt="auto", interviewer="David")
    assert len(utts) > 0


def test_empty_input_raises():
    with pytest.raises(NeedsLLMNormalization):
        normalize("", fmt="auto")


def test_unknown_format_raises():
    with pytest.raises(NeedsLLMNormalization):
        normalize("just some random text without any structure", fmt="unknown")
