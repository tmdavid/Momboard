# M6 — Explore, synthesis, insights · M7 — Deploy · M8/M9 — Meet + MCP

## T19 — Cross-conversation highlights + stats endpoints

**Depends on:** T13

**RED** — `tests/test_explore_api.py`

```python
@pytest.mark.asyncio
async def test_highlights_endpoint_filters_by_tag_company_daterange_status(auth_client, seeded): ...
@pytest.mark.asyncio
async def test_highlight_items_include_conversation_context(auth_client):
    # each item: quote, tag, confidence, conversation {id,title,happened_at}, company, contact
@pytest.mark.asyncio
async def test_default_excludes_rejected_includes_accepted_and_suggested(auth_client): ...
@pytest.mark.asyncio
async def test_stats_tag_counts_by_month_and_critique_score_trend(auth_client, seeded):
    r = await auth_client.get("/api/stats")
    body = r.json()
    assert "tag_counts_by_month" in body and "critique_trend" in body
    assert "compliment_ratio_trend" in body and "open_followups" in body
```

**GREEN** — `GET /api/highlights` (paginated, joined context), `GET /api/stats` (SQL group-bys; month bucketing done dialect-portably in Python or `func.strftime`/`date_trunc` behind a small helper).

---

## T20 — Explore page + quote wall  *(prototype: `../prototypes/explore.html`)*

**Depends on:** T14, T19

**RED**

```tsx
test("quote cards render emoji, verbatim quote, company · contact · date", ...)
test("card click navigates to conversation anchored at the utterance", ...)
test("tag filter chips update results; active filters summarized in a bar", ...)
test("'Synthesize this view' disabled under 5 highlights, shows count", ...)
test("synthesis result renders themes with evidence quotes as expandable groups", ...)
```

**GREEN** — per prototype: filter rail, responsive card grid, synthesis panel.

---

## T21 — Synthesizer agent + endpoints

**Depends on:** T12, T19

**RED** — `tests/test_synthesis.py`

```python
@pytest.mark.asyncio
async def test_post_synthesis_stores_filters_in_input_scope_and_runs_job(auth_client, fake_llm): ...
@pytest.mark.asyncio
async def test_synthesizer_input_is_highlights_not_full_transcripts(fake_llm_spy):
    # prompt payload contains quotes+context, asserts no utterance dump
@pytest.mark.asyncio
async def test_result_validates_as_SynthesizerOutput_and_evidence_ids_exist(db_session): ...
@pytest.mark.asyncio
async def test_contradictions_section_present_in_schema(): ...
```

**GREEN** — `POST /api/syntheses {filters}` → job `synthesize` → `analyses(kind="synthesis")`; schema: `themes[{name, summary, evidence_highlight_ids, strength}], contradictions[], validate_next[]`.

---

## T22 — Insights page  *(prototype: `../prototypes/insights.html`)*

**Depends on:** T14, T19

**RED**

```tsx
test("renders four panels: tag volume over time, compliment ratio, critique trend, open follow-ups", ...)
test("tag volume series toggle by clicking legend entries", ...)
test("open follow-ups list links to source conversations and shows age", ...)
test("empty/insufficient-data states render guidance copy, not broken charts", ...)
```

**GREEN** — per prototype. Charts: Recharts (matches the prototype's visual spec: monochrome-plus-accent palette, no gridline clutter, direct labeling where possible).

---

## T23 — Production Dockerfile, deploy, backups

**Depends on:** everything above green

**RED**

```python
def test_docker_image_builds_and_serves_spa_and_api():  # via testcontainers on the built image
def test_backup_script_produces_restorable_sqlite_copy(tmp_path):
    # runs `sqlite3 src .backup dst`, opens dst, sanity-counts tables
```

**GREEN** — multi-stage Dockerfile (node build → python runtime), `fly.toml` (EU region, 1GB volume at `/data`), nightly backup via scheduled machine or in-process cron writing `/data/backups/` with 14-day rotation, `SESSION_SECRET`/`OPENAI_API_KEY` as secrets. Write `DEPLOY.md` runbook (first deploy, user creation, backup restore, the Postgres migration steps from DESIGN.md §8).

---

## T24 — (Later) Google Meet auto-ingest

Sketch only — do not build until the core is in daily use. Drive API service account + watched folder; poller job kind `gmeet_poll` (every 15 min) listing new Meet transcript Docs; map Doc → `create_conversation(transcript, meta={source:"gmeet", doc_id})`; dedupe on `doc_id`. TDD the poller against recorded Drive API fixtures.

## T25 — (Later) MCP server

Python `mcp` SDK, streamable HTTP, same session auth (or PAT table). Tools: `search_conversations`, `get_conversation`, `get_highlights`, `get_commitments`, `run_synthesis`, `create_conversation`. Every tool is a thin wrapper over the existing service layer — RED tests assert tool schemas and that results match the REST equivalents byte-for-byte on the same filters.
