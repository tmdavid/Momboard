# M2 — Conversations, normalizer, jobs, SSE

## T05 — Conversations CRUD + companies/contacts

**Depends on:** T04

**RED** — `tests/test_conversations_api.py`

```python
@pytest.mark.asyncio
async def test_create_conversation_returns_201_and_enqueues_ingest(auth_client):
    r = await auth_client.post("/api/conversations", json={
        "title": "Acme Watches discovery call",
        "happened_at": "2026-08-10T10:00:00Z",
        "interviewer": "david",
        "company": {"name": "Acme Watches"},          # get-or-create by name
        "contacts": [{"name": "Jane Doe", "role": "Brand Manager"}],
        "transcript": "David: hi\nJane: hello", "transcript_format": "name_colon",
        "meta": {"deal_stage": "discovery", "plan": "enterprise"},
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "processing"
    # exactly one queued ingest job exists for it
    ...

@pytest.mark.asyncio
async def test_list_filters(auth_client, seeded_conversations):
    # by company_id, date range, status, meta.deal_stage, free-text q= (title + transcript LIKE)
    ...

@pytest.mark.asyncio
async def test_patch_metadata_and_delete_cascades(auth_client): ...
```

**GREEN**

- Pydantic schemas in `app/api/schemas.py`; routers `app/api/conversations.py`; `ConversationService` in `app/services/`.
- Get-or-create company by (name) case-insensitive; contacts linked via m2m.
- List endpoint: pagination (`limit/offset`), filters as query params, `q=` via LIKE behind `SearchService`.
- Delete cascades utterances/highlights/analyses/notes/jobs (FK ondelete + test).

---

## T06 — Deterministic normalizer + fixtures

**Depends on:** T05 (models only)

**Create the fixtures listed in tasks/README.md now** — hand-written, anonymized, realistic (brand-protection flavored is fine).

**RED** — `tests/test_normalizer.py`

```python
def test_vtt_parsed_to_ordered_utterances_with_timestamps():
    utts = normalize(read_fixture("good_interview.vtt"), fmt="vtt")
    assert utts[0].idx == 0 and utts[0].start_ms is not None
    assert all(u.speaker_label for u in utts)

def test_name_colon_format_parsed_and_speakers_extracted():
    utts = normalize(read_fixture("compliment_disaster.txt"), fmt="name_colon")
    assert {u.speaker_label for u in utts} == {"David", "Customer"}

def test_speaker_side_assignment_from_interviewer_name():
    # interviewer="David" → David's utterances speaker_side="us", others "them"
    ...

def test_messy_paste_raises_NeedsLLMNormalization():
    with pytest.raises(NeedsLLMNormalization):
        normalize(read_fixture("messy_paste.txt"), fmt="auto")

def test_format_autodetection(): ...  # vtt magic header, "^\w+:" density heuristic
```

**GREEN** — pure functions in `app/normalize.py`, no DB, no LLM. The LLM fallback path is T09's problem; here it's just the typed exception.

---

## T07 — Jobs table worker loop

**Depends on:** T05

**RED** — `tests/test_worker.py`

```python
@pytest.mark.asyncio
async def test_worker_picks_up_queued_job_and_marks_done(db_session):
    await enqueue(db_session, kind="noop", payload={})
    await run_worker_once(db_session, handlers={"noop": ok_handler})
    job = ...; assert job.status == "done" and job.started_at and job.finished_at

@pytest.mark.asyncio
async def test_failing_job_retries_3x_then_error(db_session):
    # handler raises; attempts increments; after 3 → status=error, error message stored

@pytest.mark.asyncio
async def test_jobs_processed_fifo_and_not_double_claimed(db_session):
    # claim uses UPDATE ... WHERE status='queued' RETURNING-style guard (works on both dialects)

@pytest.mark.asyncio
async def test_worker_survives_handler_exception_and_continues(db_session): ...
```

**GREEN**

- `app/worker.py`: `run_worker_once()` (testable core) + `worker_loop()` (poll 2s) started via FastAPI lifespan; handler registry `{kind: coroutine}`.
- Claim = atomic UPDATE on `status='queued'` guard; backoff = `min(2**attempts * 5s, 60s)` stored as `run_after` column (add to jobs table in same migration).

---

## T08 — Pipeline chaining + SSE progress

**Depends on:** T06, T07

**RED** — `tests/test_pipeline.py`

```python
@pytest.mark.asyncio
async def test_ingest_success_persists_utterances_and_enqueues_tag(db_session, convo):
    await run_worker_once(...)   # processes ingest
    assert utterance_count(convo) > 0
    assert next_queued_job(convo).kind == "tag"

@pytest.mark.asyncio
async def test_full_chain_with_fake_llm_reaches_done(auth_client, fake_llm):
    # POST conversation → drive worker until quiet → status="ready",
    # highlights exist (suggested), analysis row exists

@pytest.mark.asyncio
async def test_sse_stream_emits_job_transitions(auth_client, convo):
    # GET /api/conversations/{id}/events yields events: ingest.done, tag.running, ...
```

**GREEN**

- Handlers `ingest` (normalize → utterances rows → enqueue tag), placeholders `tag`/`analyze` calling `LLMClient` (real impl lands T10/T12 — for now they must work end-to-end with `FakeLLMClient`).
- Conversation `status` state machine: `processing → ready | failed` (+ `partial` if tag ok but analyze failed).
- SSE endpoint reading job-state changes (simple poll of jobs table inside the generator is fine at this scale).
