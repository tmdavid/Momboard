"""Tests for the Clari Copilot -> MomBoard ingestion transcript converter.

These focus on the pure, I/O-free helpers in scripts/clari_ingest.py so the
defensive field-name handling is pinned. No network calls.
"""

import argparse
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import respx
from httpx import Response

# Load the script module by path (scripts/ is not a package).
_SPEC = importlib.util.spec_from_file_location(
    "clari_ingest",
    Path(__file__).resolve().parent.parent / "scripts" / "clari_ingest.py",
)
assert _SPEC and _SPEC.loader
clari_ingest = importlib.util.module_from_spec(_SPEC)
# Register before exec so @dataclass can resolve the module via __module__.
sys.modules["clari_ingest"] = clari_ingest
_SPEC.loader.exec_module(clari_ingest)

convert_transcript = clari_ingest.convert_transcript
build_conversation_body = clari_ingest.build_conversation_body
build_participant_map = clari_ingest.build_participant_map
call_happened_at_of = clari_ingest.call_happened_at_of
call_title_of = clari_ingest.call_title_of
account_name_of = clari_ingest.account_name_of
source_ref_for = clari_ingest.source_ref_for
Config = clari_ingest.Config
run = clari_ingest.run


# --------------------------------------------------------------------------------
# Clari real-model tests: speakers referenced by numeric personId, resolved
# against the call's users (us) / externalParticipants (them).
# --------------------------------------------------------------------------------

# A realistic call-details shape based on the live API.
CLARI_CALL = {
    "call": {
        "id": "call-real",
        "title": "Kick off Call: Example Co / Our Team",
        "time": "2026-08-20T14:00:00.000Z",
        "status": "POST_PROCESSING_DONE",
        "account_name": "Example Brands",
        "users": [
            {"personId": 0, "userEmail": "alex.kim@acme-vendor.example"},
            {"personId": 3, "userEmail": "sam.lee@acme-vendor.example"},
        ],
        "externalParticipants": [
            {"personId": 4, "email": "jordan.doe@example.com"},
            {"personId": 9, "email": None},
        ],
        "transcript": [
            {"personId": 4, "text": "Can we add trademarks as well?", "start": 0},
            {"personId": 3, "text": "Yes, based on legal direction.", "start": 24},
            {"personId": 3, "text": "These are the three to start with.", "start": 40},
            {"personId": 9, "text": "Sounds good to me.", "start": 60},
        ],
    }
}


def test_participant_map_sides():
    pmap = build_participant_map(CLARI_CALL["call"])
    assert pmap[0].side == "us" and pmap[0].name == "Alex Kim"
    assert pmap[3].side == "us" and pmap[3].name == "Sam Lee"
    assert pmap[4].side == "them" and pmap[4].name == "Jordan Doe"
    assert pmap[9].side == "them" and pmap[9].name == "Participant 9"


def test_convert_resolves_personid_and_sides():
    result = convert_transcript(CLARI_CALL)
    assert result.utterance_count == 3  # two consecutive Sam Lee segments merge
    assert result.text == (
        "Jordan Doe: Can we add trademarks as well?\n"
        "Sam Lee: Yes, based on legal direction. These are the three to start with.\n"
        "Participant 9: Sounds good to me."
    )
    assert result.us_speakers == ["Sam Lee"]
    assert result.them_speakers == ["Jordan Doe", "Participant 9"]


def test_convert_unknown_personid_falls_back_to_indexed_label():
    # personId not in the participant map -> stable "Speaker N" label, side unknown.
    details = {"call": {"users": [], "externalParticipants": [],
                        "transcript": [{"personId": 7, "text": "Who am I?"}]}}
    result = convert_transcript(details)
    assert result.text == "Speaker 7: Who am I?"
    assert result.us_speakers == [] and result.them_speakers == []


def test_build_body_derives_interviewer_and_contacts_from_sides():
    conv = convert_transcript(CLARI_CALL)
    body = build_conversation_body(
        {"id": "call-real"}, CLARI_CALL, conv, call_id="call-real", interviewer=None
    )
    # Interviewer auto-derived from the internal speaker.
    assert body["interviewer"] == "Sam Lee"
    # Contacts built from external (them) speakers, not the junk contact_names.
    assert body["contacts"] == [{"name": "Jordan Doe"}, {"name": "Participant 9"}]
    assert body["company"] == {"name": "Example Brands"}
    assert body["meta"]["clari_us_speakers"] == ["Sam Lee"]
    assert body["meta"]["clari_them_speakers"] == ["Jordan Doe", "Participant 9"]
    assert body["meta"]["clari_status"] == "POST_PROCESSING_DONE"


def test_build_body_explicit_interviewer_overrides_derived():
    conv = convert_transcript(CLARI_CALL)
    body = build_conversation_body(
        {"id": "call-real"}, CLARI_CALL, conv, call_id="call-real", interviewer="Custom Rep"
    )
    assert body["interviewer"] == "Custom Rep"


def test_build_body_ignores_junk_contact_names_fallback():
    # When no external speakers resolved, fall back to contact_names but drop junk.
    call = {
        "id": "c",
        "contact_names": [" SalesloftNull", "Real Person"],
        "users": [],
        "externalParticipants": [],
    }
    details = {"call": {"transcript": [{"personId": 0, "text": "Hi."}], **call}}
    conv = convert_transcript(details)
    body = build_conversation_body(call, details, conv, call_id="c", interviewer=None)
    assert body["contacts"] == [{"name": "Real Person"}]


def test_convert_basic_speaker_text():
    details = {
        "transcript": [
            {"speaker": "Jane Rep", "text": "Hi there, thanks for joining."},
            {"speaker": "John Buyer", "text": "Happy to be here."},
        ]
    }
    result = convert_transcript(details)
    assert result.utterance_count == 2
    assert result.speakers == ["Jane Rep", "John Buyer"]
    assert result.text == (
        "Jane Rep: Hi there, thanks for joining.\nJohn Buyer: Happy to be here."
    )


def test_convert_merges_consecutive_same_speaker():
    details = {
        "transcript": [
            {"speaker": "Jane", "text": "First thought."},
            {"speaker": "Jane", "text": "Second thought."},
            {"speaker": "John", "text": "My turn."},
        ]
    }
    result = convert_transcript(details)
    assert result.utterance_count == 2
    assert result.text == "Jane: First thought. Second thought.\nJohn: My turn."


def test_convert_person_name_and_sentence_aliases():
    # Alternate field names: person_name / sentence, nested under transcription.
    details = {
        "transcription": {
            "sentences": [
                {"person_name": "Rep A", "sentence": "Alias fields still parse."},
                {"person_name": "Cust B", "sentence": "Yes they do."},
            ]
        }
    }
    result = convert_transcript(details)
    assert result.utterance_count == 2
    assert result.speakers == ["Rep A", "Cust B"]


def test_convert_words_list_text():
    details = {
        "segments": [
            {"speaker": "Rep", "words": [{"word": "hello"}, {"word": "world"}]},
            {"speaker": "Cust", "text": ["nice", "to", "meet", "you"]},
        ]
    }
    result = convert_transcript(details)
    assert result.text == "Rep: hello world\nCust: nice to meet you"


def test_convert_nested_under_call():
    details = {"call": {"transcript": [{"speaker": "X", "text": "Nested payload."}]}}
    result = convert_transcript(details)
    assert result.utterance_count == 1
    assert result.text == "X: Nested payload."


def test_convert_missing_speaker_uses_default_label():
    details = {"transcript": [{"text": "No speaker field here."}]}
    result = convert_transcript(details)
    assert result.text == "Speaker: No speaker field here."


def test_convert_sanitizes_colon_in_speaker():
    # A colon in the speaker label would corrupt the "Name: text" grammar.
    details = {"transcript": [{"speaker": "Rep: East", "text": "Hello."}]}
    result = convert_transcript(details)
    assert result.text == "Rep East: Hello."


def test_convert_skips_empty_text_segments():
    details = {
        "transcript": [
            {"speaker": "Rep", "text": ""},
            {"speaker": "Rep", "text": "   "},
            {"speaker": "Cust", "text": "Only this survives."},
        ]
    }
    result = convert_transcript(details)
    assert result.utterance_count == 1
    assert result.text == "Cust: Only this survives."


def test_convert_empty_when_no_transcript():
    result = convert_transcript({"summary": "no transcript key at all"})
    assert result.utterance_count == 0
    assert result.text == ""
    assert result.speakers == []


def test_happened_at_epoch_millis():
    iso = call_happened_at_of({"call_time": 1_756_000_000_000})
    assert iso is not None
    parsed = datetime.fromisoformat(iso)
    assert parsed.tzinfo is not None
    # Round-trips to the same instant in UTC.
    assert parsed.astimezone(UTC).year == 2025


def test_happened_at_iso_with_z():
    iso = call_happened_at_of({"started_at": "2026-08-15T10:30:00Z"})
    assert iso == "2026-08-15T10:30:00+00:00"


def test_happened_at_uses_clari_time_field():
    # Confirmed against the live API: /calls uses "time".
    iso = call_happened_at_of({"time": "2026-08-15T10:30:00Z"})
    assert iso == "2026-08-15T10:30:00+00:00"


def test_title_fallback_to_call_id():
    assert call_title_of({}, "abc123") == "Clari call abc123"
    assert call_title_of({"title": "Discovery — Acme"}, "abc123") == "Discovery — Acme"


def test_account_name_from_dict_or_string():
    assert account_name_of({"account_name": "Acme Corp"}) == "Acme Corp"
    assert account_name_of({"account": {"name": "Beta LLC"}}) == "Beta LLC"
    assert account_name_of({}) is None


def test_build_conversation_body_shape():
    call = {
        "id": "call-1",
        "title": "Discovery call",
        "time": "2026-08-01T09:00:00Z",
        "account_name": "Acme",
        "contact_names": ["John Buyer", "Jane Buyer"],
        "deal_name": "Acme Q3",
        "deal_stage_before_call": "Discovery",
        "status": "PROCESSED",
        "call_review_page_url": "https://copilot.clari.com/call/call-1",
    }
    details = {"call": {"transcript": [{"speaker": "Jane", "text": "Hello."}]}}
    converted = convert_transcript(details)
    body = build_conversation_body(
        call, details, converted, call_id="call-1", interviewer="Jane"
    )
    assert body["title"] == "Discovery call"
    assert body["transcript_format"] == "name_colon"
    assert body["transcript"] == "Jane: Hello."
    assert body["interviewer"] == "Jane"
    assert body["company"] == {"name": "Acme"}
    assert body["happened_at"] == "2026-08-01T09:00:00+00:00"  # from confirmed "time" field
    assert body["contacts"] == [{"name": "John Buyer"}, {"name": "Jane Buyer"}]
    assert body["meta"]["source"] == "clari"
    assert body["meta"]["source_ref"] == source_ref_for("call-1")
    assert body["meta"]["clari_call_id"] == "call-1"
    assert body["meta"]["clari_speakers"] == ["Jane"]
    assert body["meta"]["clari_status"] == "PROCESSED"
    assert body["meta"]["deal_name"] == "Acme Q3"
    assert body["meta"]["deal_stage"] == "Discovery"
    assert body["meta"]["clari_review_url"] == "https://copilot.clari.com/call/call-1"


def test_build_conversation_body_reads_metadata_from_details_call():
    # When only the summary carries the id but details.call holds metadata,
    # the merged view must still populate title/account/date.
    call = {"id": "call-2"}
    details = {
        "call": {
            "title": "Nested title",
            "account_name": "Beta LLC",
            "time": "2026-07-15T12:00:00Z",
            "transcript": [{"speaker": "A", "text": "Hi."}],
        }
    }
    converted = convert_transcript(details)
    body = build_conversation_body(call, details, converted, call_id="call-2", interviewer=None)
    assert body["title"] == "Nested title"
    assert body["company"] == {"name": "Beta LLC"}
    assert body["happened_at"] == "2026-07-15T12:00:00+00:00"
    assert "interviewer" not in body


# --------------------------------------------------------------------------------
# Integration tests for run(): mock both Clari and MomBoard HTTP with respx.
# --------------------------------------------------------------------------------

CLARI = "https://clari.test"
MOMBOARD = "http://momboard.test"


def _cfg() -> Config:
    return Config(
        clari_base_url=CLARI,
        clari_api_key="k",
        clari_api_password="p",
        momboard_base_url=MOMBOARD,
        momboard_email="admin@example.com",
        momboard_password="pw",
    )


def _args(**overrides):
    base = dict(
        date_from="2026-08-01",
        date_to="2026-08-31",
        call_id=None,
        max_calls=50,
        max_scan=5000,
        all_statuses=True,  # tests provide their own calls; don't status-filter
        interviewer=None,
        dry_run=False,
        force=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


@respx.mock
def test_run_imports_new_call():
    respx.get(f"{CLARI}/calls").mock(
        return_value=Response(200, json={"calls": [{"id": "c1", "title": "Discovery"}]})
    )
    respx.get(f"{CLARI}/call-details").mock(
        return_value=Response(
            200, json={"transcript": [{"speaker": "Jane", "text": "Hello."}]}
        )
    )
    respx.post(f"{MOMBOARD}/auth/login").mock(
        return_value=Response(200, json={"id": 1, "email": "admin@example.com", "role": "admin"})
    )
    # No existing conversation with this source_ref.
    respx.get(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(200, json={"items": [], "total": 0, "limit": 200, "offset": 0})
    )
    create = respx.post(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(201, json={"id": 42, "title": "Discovery", "status": "processing"})
    )

    stats = run(_args(), _cfg())

    assert stats.imported == 1
    assert stats.skipped_existing == 0
    assert stats.errors == 0
    # Verify the payload MomBoard received.
    sent = create.calls.last.request
    import json as _json

    body = _json.loads(sent.content)
    assert body["transcript"] == "Jane: Hello."
    assert body["transcript_format"] == "name_colon"
    assert body["meta"]["source_ref"] == "clari:c1"


@respx.mock
def test_run_skips_already_imported():
    respx.get(f"{CLARI}/calls").mock(
        return_value=Response(200, json={"calls": [{"id": "c1", "title": "Discovery"}]})
    )
    respx.post(f"{MOMBOARD}/auth/login").mock(
        return_value=Response(200, json={"id": 1, "email": "admin@example.com", "role": "admin"})
    )
    # Existing conversation already carries the source_ref -> should skip.
    respx.get(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(
            200,
            json={
                "items": [{"id": 7, "meta": {"source_ref": "clari:c1"}}],
                "total": 1,
                "limit": 200,
                "offset": 0,
            },
        )
    )
    create_route = respx.post(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(201, json={"id": 99})
    )

    stats = run(_args(), _cfg())

    assert stats.skipped_existing == 1
    assert stats.imported == 0
    assert not create_route.called  # never attempted a create


@respx.mock
def test_run_dry_run_makes_no_momboard_calls():
    respx.get(f"{CLARI}/calls").mock(
        return_value=Response(200, json={"calls": [{"id": "c1", "title": "Discovery"}]})
    )
    respx.get(f"{CLARI}/call-details").mock(
        return_value=Response(200, json={"transcript": [{"speaker": "Jane", "text": "Hi."}]})
    )
    login = respx.post(f"{MOMBOARD}/auth/login").mock(return_value=Response(200, json={}))
    create = respx.post(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(201, json={})
    )

    stats = run(_args(dry_run=True), _cfg())

    assert stats.imported == 1  # counted as "would import"
    assert not login.called
    assert not create.called


@respx.mock
def test_run_single_call_id_skips_listing():
    calls_route = respx.get(f"{CLARI}/calls").mock(return_value=Response(200, json={"calls": []}))
    respx.get(f"{CLARI}/call-details").mock(
        return_value=Response(200, json={"transcript": [{"speaker": "A", "text": "One call."}]})
    )
    respx.post(f"{MOMBOARD}/auth/login").mock(return_value=Response(200, json={}))
    respx.get(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.post(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(201, json={"id": 5, "title": "Clari call c9", "status": "processing"})
    )

    stats = run(_args(call_id="c9"), _cfg())

    assert stats.imported == 1
    assert not calls_route.called  # --call-id must not list


@respx.mock
def test_run_skips_call_with_empty_transcript():
    respx.get(f"{CLARI}/calls").mock(
        return_value=Response(200, json={"calls": [{"id": "c1"}]})
    )
    respx.get(f"{CLARI}/call-details").mock(
        return_value=Response(200, json={"summary": "no transcript"})
    )
    respx.post(f"{MOMBOARD}/auth/login").mock(return_value=Response(200, json={}))
    respx.get(f"{MOMBOARD}/api/conversations").mock(
        return_value=Response(200, json={"items": []})
    )

    stats = run(_args(), _cfg())

    assert stats.skipped_empty == 1
    assert stats.imported == 0


@respx.mock
def test_clari_page_retries_transient_502(monkeypatch):
    """A transient 502 on /calls is retried rather than aborting the import."""
    # Avoid real backoff sleeps.
    monkeypatch.setattr(clari_ingest.time, "sleep", lambda _s: None)

    route = respx.get(f"{CLARI}/calls").mock(
        side_effect=[
            Response(502, text="bad gateway"),
            Response(200, json={"calls": [{"id": "c1", "status": "X"}], "pagination": {}}),
        ]
    )
    with clari_ingest.ClariClient(_cfg()) as clari:
        page, _pagination = clari._page(0, 100)
    assert route.call_count == 2
    assert page and page[0]["id"] == "c1"


@respx.mock
def test_clari_page_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(clari_ingest.time, "sleep", lambda _s: None)
    respx.get(f"{CLARI}/calls").mock(return_value=Response(503, text="down"))
    with clari_ingest.ClariClient(_cfg()) as clari:
        try:
            clari._page(0, 100)
            raise AssertionError("expected HTTPStatusError")
        except Exception as exc:  # noqa: BLE001
            assert "503" in str(exc)
