# Changelog

All notable changes to MomBoard, newest first. The README shows only the current
status and latest additions; this file is the full history.

## v0.4 — Decisions, Hypotheses board, new UI (2026-11-11)

A redesigned interface, a Hypotheses board you can trust, and a Decisions page that keeps
its receipts. Migrations **008–010** (run automatically by the container; for a
from-source install use `python scripts/migrate_v04.py`).

**Hypotheses**
- **Grounding bands follow clear rules** (confirmed quotes only; suggested matches never
  move a band): *Grounded* = 3+ supporting quotes from 2+ companies and at most 1
  contradicting; *Contested* = 2+ supporting and 2+ contradicting; *Refuted* = 3+
  contradicting and more than 2x the supporting; *Candidate* = some confirmed evidence but
  not enough; *Hunch* = none. Thresholds are settings (`HYPOTHESIS_GROUNDED_MIN_SUPPORT`,
  `HYPOTHESIS_GROUNDED_MIN_COMPANIES`, `HYPOTHESIS_GROUNDED_MAX_CONTRADICT`,
  `HYPOTHESIS_CONTESTED_MIN_EACH`, `HYPOTHESIS_REFUTED_MIN_CONTRADICT`,
  `HYPOTHESIS_REFUTED_RATIO`) and are served at `GET /api/hypotheses/band-rules`. Every card
  has a one-sentence `grounding_reason` that says what is still missing.
- **Board by band** (Grounded / Contested / Candidate / Hunch / Refuted) with segment, band
  and pending-suggestion filters, a "How bands work" explainer, and archive / restore
  ("Show archived"). The board loads every page of results.
- **Evidence check before saving**: matches show a score, source and reason; strong matches
  are pre-ticked, weaker ones sit under a divider; "If saved now" previews the band.
  Customer turns only (our reps and compliments are excluded), minimum confidence, a
  verification pass, and at most one match per call unless the second quote says the
  opposite. With a segment set, in-segment matches rank first and others are marked
  "Outside the <segment> segment" (not pre-ticked, not counted in the preview). Companies
  have no structured segment, so the model judges from the company name and notes and says
  "unknown" rather than guess.
- **Detail view**: edit (the belief is locked once quotes are linked), accept / reject
  evidence, add evidence by searching quotes, validation questions you can tick off as
  asked, and **band history** with the quote behind each change. "Cite in decision" and
  Explore's "Link to hypothesis" connect it to the rest of the app.
- Rejecting a quote's tag **invalidates** the hypothesis links to it, and the band
  re-derives. The auto-linker now ignores our reps, never re-suggests a pair you already
  decided, and drops suggestions under 0.6 confidence.
- API: `GET /api/hypotheses` now returns `{items, total}` with `band`, `segment`, `status`,
  `has_pending`, `sort` and paging (**breaking**: it was a bare list); `archived` status;
  `/history`, `/segments`, `/band-rules`, and `PATCH .../questions/{id}`.

**Decisions**
- **Receipts survive**: each cited quote is snapshotted (quote, company, call, date), so a
  decision still reads correctly after a Retag. Integrity is stored and updated when a
  cited tag is rejected or a call is deleted. *Deleting a highlight that a decision cites is
  now allowed* (it used to be blocked); the receipt is flagged instead.
- The page uses the full API: owner and area, a Draft status (Propose once a quote is
  cited), edit, add / remove cited quotes, search and sort, quote counts, the linked
  hypothesis with its band, and "Superseded by <title>". A decision that cites an
  **archived hypothesis** is flagged ("Belief archived") but not marked undermined.
- `GET /api/users` lists teammate names (id and name only) for the owner picker.

**Interface**
- New design system and app shell (header, sidebar) with every page restyled: Library,
  Conversation, Explore, Insights, Hypotheses, Decisions, Practice, Summaries, Settings.
  Preset filters in Library; a clearer Practice layout. Removed on purpose: the global
  search box, the Help popover and the "Compare as lens" button in Explore.
- Tag filters: the 10 most common tags in one row and the Core / Custom dropdowns on their
  own row below, flipping to open leftwards near the window edge.

**Fixes and housekeeping**
- Fixed a crash (HTTP 500) on the Hypotheses list and detail when a hypothesis had a
  confirmed quote from a dated call: freshness compared timezone-aware and naive times.
- One release number: the app, `/healthz`, the MCP server, `pyproject.toml` and the web
  package all report **0.4.0** (they had stayed at 0.2.0), with a test that fails if they
  drift apart.
- Ops scripts: `scripts/migrate_v04.py` (backup, migrate and verify; also `--verify-only`
  inside a container) and `scripts/retag_conversations.py` (bulk re-tag a date range
  through the API; dry run by default).

**Behaviour changes to know about**
- A hypothesis with one confirmed quote is now a *Candidate* (it used to read as Grounded),
  and one with only suggested links is a *Hunch*, with a "to review" badge.
- Strong intake matches start ticked (they used to start unticked).
- A quote can't be linked twice to the same hypothesis (409).

## v0.3 — "From advisor to collaborator"

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

- **T47 Custom taxonomy, first-class** — teams define their own tags (key, emoji,
  description, signal strength) in Settings; new tags flow into the tagger prompt and apply
  on reprocess. Tags have an `origin` (core / custom) and a free-form `category`
  (migration 007); the filters group them as Core and Custom with categories, and Settings
  lets you reorder them.

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
