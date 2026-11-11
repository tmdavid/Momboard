# Changelog

All notable changes to MomBoard, newest first. The README shows only the current
status and latest additions; this file is the full history.

## v0.4 — Decisions, Hypotheses board, new UI (in progress)

- **Hypothesis grounding bands use the PRD rules** (confirmed links only; suggested matches
  never move a band): *Grounded* = 3+ supporting quotes from 2+ companies and at most 1
  contradicting; *Contested* = 2+ supporting and 2+ contradicting; *Refuted* = 3+
  contradicting and more than 2x the supporting; *Candidate* = some confirmed evidence but
  not enough; *Hunch* = none. **Behaviour change:** one confirmed quote used to read as
  Grounded; it is now a Candidate, and a hypothesis with only suggested links is a Hunch
  (with a "to review" badge). Thresholds are settings (`HYPOTHESIS_GROUNDED_MIN_SUPPORT`,
  `HYPOTHESIS_GROUNDED_MIN_COMPANIES`, `HYPOTHESIS_GROUNDED_MAX_CONTRADICT`,
  `HYPOTHESIS_CONTESTED_MIN_EACH`, `HYPOTHESIS_REFUTED_MIN_CONTRADICT`,
  `HYPOTHESIS_REFUTED_RATIO`), exposed at `GET /api/hypotheses/band-rules`. Each card
  carries a one-sentence `grounding_reason` that says what is still missing.
- **Decisions page uses the full Decisions API**: owner and area, a Draft status
  (Propose once a quote is cited), edit title/rationale/owner/area, add or remove cited
  quotes, search and sort, a per-row quote count, the linked hypothesis with its band,
  and "Superseded by <title>". A decision citing an **archived hypothesis** is flagged
  ("Belief archived", with a re-check prompt) but is not marked undermined; restoring the
  hypothesis clears the flag. `GET /api/users` returns teammate names (id + name only).
- **Hypothesis intake matching**: when the belief names a segment, matches from that
  segment rank first and others say "Outside the <segment> segment" (and are not
  pre-ticked or counted in "If saved now"); at most one match per conversation unless the
  second quote takes the opposite stance. There is no structured segment on companies, so
  the model judges from the company name and notes and answers "unknown" rather than guess.
- Hypotheses board: archived hypotheses can be viewed and restored ("Show archived"); the
  board loads every page of results instead of the first 200.
- Hypotheses: grounding-band board, scored evidence check, detail view with band history,
  validation questions, add-evidence and archive; list API returns `{items, total}`.
  Migration 010. Decisions: evidence snapshots and reactive integrity (migrations 008, 009).

## v0.3 — "From advisor to collaborator" (in progress)

The corpus becomes a grounded boundary: it **feeds other tools** (insights over MCP)
and **gates what enters it** (hand-entered beliefs must cite call evidence or be
flagged as hunches). See [`V0.3.md`](V0.3.md) and [`docs/design/`](docs/design/).

Shipped:

- **T48 Evidence-gated hypothesis intake** — a manual "add a belief" front door to the
  hypothesis board that matches the corpus for evidence. A read-only **2D grounding
  band** (`grounded` / `contested` / `refuted` / `candidate` / `hunch`) is computed at
  read time from confirmed vs. suggested support/contradict links — support and
  contradiction are independent axes, so a belief can be *contested*. Intake preview
  (`POST /api/hypotheses/intake`) scores corpus matches and, when evidence is thin,
  generates past-behavior Mom Test questions; commit (`/intake/commit`) saves the belief
  `origin=human` with human-confirmed evidence links. UI: "Check evidence first" with
  opt-in per-quote confirmation (heavy judgment, zero-effort retrieval). Adds
  `hypotheses.origin` (migration 006).
- **T46 Read-only insight MCP tools** — `list_hypotheses` / `get_hypothesis` (grounding
  band + strength counts + cited evidence quotes) and `list_decisions` / `get_decision`
  (status, integrity + reasons, cited quotes) on the MCP server, so an external agent
  can draft docs/prototypes on verifiable, honestly-labelled evidence. MomBoard stays
  the evidence layer; drafting happens in the external design surface.
- **Clari source-call link** — conversations imported from Clari show a "View in Clari"
  link back to the original recording (from `meta.clari_review_url`).

Remaining: T47 (first-class custom taxonomy).

## v0.2 — "From archive to advisor"

Made the repository talk back — prep before calls, nudges, cited answers, practice.

- **T34 Staging inbox** — pending_import/ignored/imported/parse_error lifecycle, source_ref dedupe
- **T29/T30 Contact memory + drift** — timelines, drift detection, contact/company detail API
- **T38 Pre-call briefs** — compile history + suggest past-behavior questions, 1h cache
- **T24 Google Meet/Drive polling** — Drive Doc parser, fixture-pinned, parse_error retention
- **T41 Evidence staleness** — freshness bands computed read-time, integrated into hypotheses
- **T31 Weekly digest** — pure builder, Slack delivery, idempotent self-rescheduling
- **T42 Corpus chat** — SQL-first retrieval, validated citations, per-user chat storage
- **T25 MCP tools** — tools over stdio; an HTTP helper exists but is not mounted by default
- **T44 Quote cards** — 1600×900 PNG/SVG export with themes, anonymization, rejected guard
- **T35 Audio upload** — Whisper transcription with format/size validation, VTT-formatted output
- **T36 Vexa meeting bot** — configurable integration, send/stop/preview/import, deterministic dedupe
- **T39 Interview simulator** — persona builder from segment filters, Mom Test chat loop, corpus isolation
- **T40 Decision log** — evidence receipts, proposed→decided→superseded lifecycle, integrity checks, 409 on cited-highlight delete
- **T43 Segment lenses** — compare two filter sets, per-side attribution validated in code
- **T45 Saved syntheses + Summaries** — fire-and-forget synthesis jobs, a Summaries page, a `saved` flag with live job status
- **Conversation sorting** — list by date or Mom Test critique score, unscored last
- **Clari Copilot import** — on-demand `scripts/clari_ingest.py`, idempotent via `source_ref` dedupe
- **Concurrent worker pool** — configurable concurrency with startup recovery of stale jobs
- **Pluggable LLM backend** — OpenAI, local Ollama, or AWS Bedrock (global, EU-resident by default), with per-agent model selection

## v0.1 — core application (T01–T23, T27–T28)

The foundation: store, tag, and review customer conversations.

- Transcript ingestion for pasted text, `Name: text`, and WebVTT
- Database-backed normalize → tag → analyze → hypothesis-link pipeline
- Human review of suggested highlights and manual highlights
- Conversation notes with optimistic concurrency
- Library, conversation, explore, synthesis, insights, and hypotheses UI
- Session authentication, admin-managed taxonomy, companies/contacts directory
- SQLite/PostgreSQL-compatible schema and Alembic migrations
- Production Docker/Fly configuration and rotating SQLite backups
