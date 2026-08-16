# M10 — Extensions: prototype ideas, hypotheses, contact memory, weekly digest

All four build on the core (M0–M6 green). Same conventions as `README.md`: LLM always faked in tests, structured outputs with Pydantic twins, migrations via Alembic.

## T26 — Prototype-idea generator (evidence → concept mockups)

**Depends on:** T21 (synthesis)
**Intent:** internal ideation, NOT something you show customers. Given a synthesis, generate 1–3 self-contained HTML concept mockups so that when a relevant moment comes up later, you already have ideas of what might be worth asking about. Each UI element in the mockup is annotated with the evidence that justified it.

**RED** — `tests/test_prototype_gen.py`

```python
@pytest.mark.asyncio
async def test_post_prototypes_enqueues_job_and_returns_202(auth_client, synthesis): ...

@pytest.mark.asyncio
async def test_generator_stores_artifacts_with_rationale(db_session, synthesis, fake_llm):
    await run_prototype_gen(db_session, synthesis.id, llm=fake_llm)
    arts = await artifacts_for(synthesis)
    assert 1 <= len(arts) <= 3
    a = arts[0]
    out = PrototypeOutput.model_validate({"html": a.html, "rationale": a.rationale})
    # every rationale entry maps a concept element to existing highlight ids
    assert all(hid_exists(r.evidence_highlight_ids) for r in out.rationale)

@pytest.mark.asyncio
async def test_html_is_self_contained_and_sanitized(db_session, fake_llm_hostile):
    # no <script src=>, no external fetch()/import, no <iframe>; inline style/script only
    # hostile fixture containing external refs → stripped or rejected

@pytest.mark.asyncio
async def test_artifacts_listed_under_synthesis_and_conversation_context(auth_client): ...
```

**RED (frontend)** — extends the synthesis panel in Explore (see `../prototypes/explore.html`)

```tsx
test("synthesis panel shows 'Generate concept ideas' button after a synthesis exists", ...)
test("generated concepts render as cards with title + 'why this exists' evidence list", ...)
test("concept opens full-screen in a sandboxed iframe (srcdoc, sandbox='')", ...)
```

**GREEN**

- `artifacts` table: id, synthesis_id FK, title, html (text), rationale (JSON), model, prompt_version, created_at.
- Job kind `prototype`; agent prompt: input = synthesis themes + evidence quotes; output schema `PrototypeOutput {title, html, rationale[{element, why, evidence_highlight_ids[]}]}`. Prompt instructs: single-file HTML, inline CSS/JS only, fake data, mobile-ignorant is fine — these are thought sketches.
- Sanitizer pass in Python (allowlist: no external URLs in src/href except `#`, no iframes) — never trust generated HTML; serve only via sandboxed `srcdoc`.
- `POST /api/syntheses/{id}/prototypes`, `GET /api/syntheses/{id}/prototypes`.

---

## T27 — Hypothesis tracking (backend)

**Depends on:** T10
**The conceptual leap: from note archive to validation engine.** A hypothesis is a falsifiable belief ("enterprise brands will pay to kill the Monday export"). Every new conversation's highlights get auto-proposed as supporting or contradicting evidence; humans confirm, and the hypothesis accumulates a verdict over time.

**RED** — `tests/test_hypotheses.py`

```python
@pytest.mark.asyncio
async def test_hypothesis_crud_with_status_lifecycle(auth_client):
    # POST {statement, segment?} → status "open"; PATCH status to supported/refuted/parked
    # statement immutable after evidence exists (PATCH statement → 409) — edit = new hypothesis

@pytest.mark.asyncio
async def test_linker_runs_after_tagging_and_proposes_links(db_session, convo, fake_llm):
    # pipeline: tag job success → enqueues `hypothesis_link` job when open hypotheses exist
    await run_hypothesis_link(db_session, convo.id, llm=fake_llm)
    links = await links_for(convo)
    assert all(l.status == "suggested" and l.stance in ("supports","contradicts") for l in links)
    assert all(l.origin == "ai" for l in links)

@pytest.mark.asyncio
async def test_linker_input_contains_only_open_hypotheses(fake_llm_spy): ...

@pytest.mark.asyncio
async def test_confirm_reject_link_and_evidence_rollup(auth_client, seeded):
    # PATCH link accept → rollup on GET /api/hypotheses/{id}:
    # {supports: {confirmed: 4, suggested: 1}, contradicts: {confirmed: 1, ...},
    #  companies_supporting: 3, last_evidence_at: ...}

@pytest.mark.asyncio
async def test_rollup_counts_only_confirmed_links_toward_verdict_hint(auth_client):
    # verdict_hint: "leaning-supported" when confirmed supports ≥ 3 companies and
    # contradicts from ≤ 1 — a HINT, never an auto status change (humans decide)

@pytest.mark.asyncio
async def test_deleting_highlight_cascades_links(db_session): ...
```

**GREEN**

- Tables: `hypotheses` (id, statement, segment str?, status open|supported|refuted|parked, created_by, created_at, decided_at?), `hypothesis_links` (id, hypothesis_id FK, highlight_id FK, stance, confidence, origin ai|human, status suggested|confirmed|rejected, rationale str).
- Job kind `hypothesis_link` chained after `tag` (skip when no open hypotheses — tested). Agent schema: `LinkerOutput {links: [{hypothesis_id, highlight_id, stance, confidence, rationale}]}`; unknown ids stripped with warning (same pattern as T12).
- Rollup computed in SQL at read time, no denormalized counters.
- Endpoints: `GET/POST/PATCH /api/hypotheses`, `PATCH /api/hypothesis-links/{id}`, `GET /api/hypotheses/{id}` (with rollup + evidence grouped by stance).

---

## T28 — Hypothesis board UI  *(prototype: `../prototypes/hypotheses.html`)*

**Depends on:** T14, T27

**RED**

```tsx
test("board lists hypotheses with status chip and support/contradict meter", ...)
test("meter shows confirmed evidence; suggested evidence shown as hatched extension", ...)
test("card expands to evidence grouped by stance, quotes link to conversations", ...)
test("suggested links render with accept/reject inline (same pattern as highlight review)", ...)
test("'mark supported/refuted' asks for confirmation and records decided_at", ...)
test("new hypothesis composer validates non-empty falsifiable statement (min 15 chars)", ...)
```

**GREEN** — per prototype: card list, evidence meter (fill = confirmed support share; track = same-ramp lighter step), review affordances reusing the highlight-chip pattern from T17.

---

## T29 — Contact-level memory (backend)

**Depends on:** T12

**RED** — `tests/test_contact_memory.py`

```python
@pytest.mark.asyncio
async def test_contact_timeline_merges_conversations_highlights_commitments(auth_client, seeded):
    r = await auth_client.get(f"/api/contacts/{jane.id}/timeline")
    kinds = [e["kind"] for e in r.json()["events"]]
    # chronological, mixed: conversation, highlight, commitment, note_excerpt
    assert kinds == sorted_by_time(kinds_with_timestamps)

@pytest.mark.asyncio
async def test_company_timeline_aggregates_all_its_contacts(auth_client): ...

@pytest.mark.asyncio
async def test_drift_detector_flags_contradiction_with_prior_statement(db_session, fake_llm):
    # fixture: May highlight "legal must approve every takedown";
    # new Aug conversation: "we file directly now"
    await run_drift_check(db_session, new_convo.id, llm=fake_llm)
    d = await drifts_for(jane)
    assert d[0].kind in ("contradiction","change")
    assert d[0].earlier_highlight_id and d[0].later_highlight_id

@pytest.mark.asyncio
async def test_drift_check_skipped_when_contact_has_no_prior_history(fake_llm_spy):
    # zero LLM calls made — tested via spy

@pytest.mark.asyncio
async def test_drift_dismissable_and_dismissed_stays_dismissed_on_rerun(auth_client): ...
```

**GREEN**

- `GET /api/contacts/{id}/timeline` and `GET /api/companies/{id}/timeline` — pure read-model queries, no new write tables.
- `drifts` table (id, contact_id, earlier_highlight_id, later_highlight_id, kind contradiction|change, summary, status open|dismissed|confirmed, created_at). Job kind `drift_check` chained after `analyze` when the contact has prior accepted highlights. Agent input: prior statements (accepted highlights, dated) + new ones; schema `DriftOutput {drifts:[{earlier_highlight_id, later_highlight_id, kind, summary}]}`.
- A drift is *information, not accusation* — "change" is the default kind unless statements are logically incompatible.

---

## T30 — Contact page UI  *(prototype: `../prototypes/contact.html`)*

**Depends on:** T14, T29

**RED**

```tsx
test("header shows contact, role, company, stats (conversations, open follow-ups, last talked)", ...)
test("timeline renders newest-first with kind icons; highlights show tag emoji + quote", ...)
test("drift alerts render at top with both quotes side by side and dismiss/confirm actions", ...)
test("filter timeline by kind (conversations / signals / commitments)", ...)
test("company page shows same timeline across all its contacts, grouped by contact", ...)
```

**GREEN** — per prototype; company names/contacts throughout the app become links to these pages (Library rows, Explore cards).

---

## T31 — Weekly digest

**Depends on:** T19; nicer after T27/T29 (sections degrade gracefully when those tables are absent/empty)

**RED** — `tests/test_digest.py`

```python
def test_digest_builder_is_a_pure_function_matching_golden_file(seeded_snapshot):
    md = build_digest(seeded_snapshot, week_of=date(2026, 8, 10))
    assert md == read_golden("digest_2026-08-10.md")
    # golden covers: new commitments, overdue follow-ups (>14d), compliment-ratio delta,
    # hypothesis movements (newly leaning-supported/contradicted), drift alerts, 1 auto-insight

def test_digest_sections_omitted_when_empty_not_rendered_as_zero(): ...

@pytest.mark.asyncio
async def test_digest_job_posts_to_slack_webhook(respx_mock, db_session):
    await run_digest(db_session, ...)
    assert respx_mock.calls[0].request.url == settings.slack_webhook_url
    # payload is Slack blocks converted from the markdown

@pytest.mark.asyncio
async def test_digest_reschedules_itself_next_monday_0800(db_session):
    await run_digest(db_session, ...)
    nxt = await next_queued_job(kind="digest")
    assert nxt.run_after == next_monday_0800_utc(...)

@pytest.mark.asyncio
async def test_no_duplicate_digest_for_same_week(db_session):
    # idempotency key (iso week) on the job payload; second enqueue is a no-op
```

**GREEN**

- `build_digest(snapshot, week_of) -> str` — pure, all queries done by the caller; this is what makes the golden test trivial.
- The one LLM touch: the single "insight of the week" line, generated from the week's accepted highlights (faked in tests like everything else); the rest is deterministic SQL.
- Delivery: Slack incoming-webhook URL from settings (skip section if unset), optional SMTP later. Self-rescheduling job using the existing `run_after` column — no new scheduler infrastructure.
- `POST /api/digest/preview` returns the markdown for "this week so far" (used by a Settings page button).

---

## T32 — Local / self-hosted LLM backend

**Depends on:** T09 only. Everything speaks to `LLMClient`, so this is an adapter, not a rewrite.
**Goal:** run the whole pipeline with zero data leaving your infrastructure. Transcripts are customer data — this is the privacy-maximalist mode, and also the "no per-token bill" mode.

**RED** — `tests/test_local_llm.py`

```python
def test_backend_selected_by_settings():
    # LLM_BACKEND=openai|local ; local requires LLM_BASE_URL; per-agent model names
    # still come from settings (LLM_MODEL_TAGGER can be "qwen3:32b")

@pytest.mark.asyncio
async def test_local_client_sends_openai_compatible_chat_request(respx_mock):
    # POST {base_url}/v1/chat/completions with response_format json_schema
    # (vLLM guided decoding) — assert schema forwarded, no OpenAI auth header required

@pytest.mark.asyncio
async def test_ollama_native_fallback_uses_format_field(respx_mock):
    # LLM_LOCAL_FLAVOR=ollama → POST {base_url}/api/chat with format=<json schema>

@pytest.mark.asyncio
async def test_schema_violation_triggers_one_repair_retry_then_LLMSchemaError(respx_mock):
    # local models fail schemas more often than OpenAI strict mode:
    # on validation error, re-prompt once with the validation errors appended;
    # second failure raises — job retry machinery (T07) takes over

@pytest.mark.asyncio
async def test_long_transcript_respects_local_context_budget():
    # chunker (T11) reads max_context from settings; local default 32k →
    # smaller chunks than the OpenAI path; asserted via fake tokenizer

def test_all_agent_prompts_have_no_openai_specific_assumptions():
    # prompt registry lint: no "as GPT-…" phrasing, schemas ≤ the size local
    # guided decoding handles; runs in CI
```

**GREEN**

- `app/llm/local.py`: `LocalLLMClient(LLMClient)` targeting any OpenAI-compatible server (vLLM, llama.cpp server, LM Studio, LiteLLM proxy) via `LLM_BASE_URL`, plus an `ollama` flavor using Ollama's native `format` parameter for schema-constrained output.
- Repair-retry loop (validate → re-prompt with errors → validate → raise) lives in the shared client base so both backends get it; OpenAI strict mode just never triggers it.
- `docker-compose.local-llm.yml` example service (vLLM with a Qwen3 model + `--guided-decoding-backend xgrammar`), documented in DEPLOY.md.
- Settings: `LLM_BACKEND`, `LLM_BASE_URL`, `LLM_LOCAL_FLAVOR`, `LLM_MAX_CONTEXT` — plus **per-agent backend overrides** (`LLM_BACKEND_TAGGER=local`, `LLM_BACKEND_SYNTHESIZER=openai`), so hybrid setups are one env line per agent.

### CPU-inference profile (weak/no GPU, ample system RAM)

Viable because the pipeline is **async background jobs — tokens/second barely matters**; quality and RAM headroom are the real constraints. A ≤2 GB GPU contributes nothing meaningful — run pure CPU (llama.cpp can offload a few layers with `-ngl`, but at this VRAM it's noise; don't complicate the setup for it). Add to the RED set:

```python
def test_per_agent_backend_override_routes_calls_independently(respx_mock):
    # tagger → local base_url, synthesizer → api.openai.com, in the same pipeline run

@pytest.mark.asyncio
async def test_context_budget_from_settings_drives_chunk_size():
    # LLM_MAX_CONTEXT=8192 → chunker sizes chunks so prompt + chunk + schema,
    # measured by tokenizer, stays under budget (works for any budget value)

def test_taxonomy_prompt_has_compact_mode():
    # LLM_PROMPT_COMPACT=1 renders one-line tag definitions and trims few-shots —
    # useful when the context budget is small or CPU prefill is slow
```

Runbook notes for DEPLOY.md — llama.cpp `llama-server` or Ollama (both OpenAI-compatible; both schema-constrain JSON), **Q4_K_M quants**, model picked by RAM headroom:

| System RAM free for the model | Pick | Why |
|---|---|---|
| ~6–10 GB | Qwen3-8B (~5 GB) | best small dense tagger |
| ~10–16 GB | Qwen3-14B (~9 GB) | comfortably good tagging + decent analysis |
| ~18 GB+ | **Qwen3-30B-A3B (~18 GB)** or gpt-oss-20b (~13 GB) | **MoE = the CPU sweet spot**: only ~3B params active per token, so it runs at small-model speed with big-model quality |

Set `--ctx-size 8192–16384` (RAM permitting), single slot. The MoE tier is the interesting one for CPU boxes: prefill is still slow on long transcripts (minutes per conversation — fine for a background job), but quality approaches API-tier tagging. Below the MoE tier, keep the hybrid override (local tagger, API analyst/synthesizer). Measure, don't guess: T33's eval report is the go/no-go.

---

## T33 — Model eval harness (pick your model with data, not vibes)

**Depends on:** T10, T32

**RED** — `tests/test_eval_harness.py`

```python
def test_eval_runs_tagger_on_golden_fixtures_and_scores_against_expected():
    # for each fixture transcript: expected highlights (hand-labeled) vs produced;
    # per-tag precision/recall + verbatim-quote validity rate + schema failure rate

def test_report_written_as_markdown_table_per_model():
    # evals/report.md: rows = models (gpt-5-mini, qwen3:32b, llama3.3:70b, …),
    # cols = P/R per tag family, quote validity %, schema fail %, latency, cost/1k tokens

def test_eval_never_runs_in_ci_against_live_endpoints():
    # CI uses recorded responses; live mode behind `python -m app.eval --live`
```

**GREEN** — `python -m app.eval --models qwen3:32b,gpt-5-mini --live` runs the real backends against `tests/fixtures/transcripts/`, writes `evals/report.md`. The hand-labeled expected highlights ARE the spec for "good tagging" — 30 minutes of labeling effort that pays for itself on every model/prompt change forever.

---

### Suggested order

T27 → T28 (the validation engine is the point), then T29 → T30 (cheap, mostly read-models), then T31 (small, high perceived value), then T26 (the fun one — needs good syntheses to shine). T32/T33 whenever privacy or cost makes them urgent — they only touch `app/llm/`.
