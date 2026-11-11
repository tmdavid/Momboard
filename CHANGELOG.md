# Changelog

All notable changes to MomBoard, newest first. The README shows only the current
status and latest additions; this file is the full history.

## v0.5 — Better tags, better matches, a calmer interface (2026-11-11)

Tagging that stops mistaking our own reps for customers, hypothesis matching that can find
quotes nobody tagged, a staged way to retag the whole library, and a round of interface fixes.
Migrations **011** and **012** (run automatically by the container; for a from-source install use
`python scripts/migrate_db.py`, which replaces `scripts/migrate_v04.py` and now reads the expected
revision from the migration files). **Retagging is a separate, deliberate step** — see
[`documentation/guides/retag-rollout.md`](documentation/guides/retag-rollout.md); nothing is retagged automatically.

**Tagging quality**
- **Your company** (Settings): name, aliases and email domains. Speakers matching them are marked
  as ours, and the company is described to every prompt so the models know whose side is whose.
  `GET`/`PUT /api/settings/company` (`PUT` is admin only).
- **Customer turns only.** Evidence tags are applied to customer speech only; Follow-up and
  Commitment may come from either side. Filler (greetings, "mm-hm") is skipped, and a quote gets
  one tag, not several. Tagger prompt is now `tagger-v2`.
- **Per-tag confidence floor** (`min_confidence`, default 0.5) plus a "don't tag when" hint and an
  example for every tag, editable in Settings. Library tag counts and filters, Explore, Insights
  and hypothesis matching hide suggestions under their tag's floor. Accepted and manual
  highlights always show. Explore sorts strongest first, shows at most 3 quotes per call, and has
  a "Show low-confidence" switch.
- **Measuring the tagger**: `scripts/eval_tagger.py` scores the tagger against a hand-tagged test
  set and exits non-zero below the gate ([`documentation/guides/tagger-evaluation.md`](documentation/guides/tagger-evaluation.md)).
- **Taxonomy versioning**: each call records the taxonomy version and when it was tagged; adding
  or reactivating a tag bumps the version, and Library / Explore say when results are partial
  because calls have not been retagged yet. `GET /api/taxonomy/status` and `/stale`.

**Hypothesis matching**
- **Two stages.** Stage 1 gathers candidates from *all* customer speech (not only tagged quotes)
  using the belief's own words plus LLM-suggested search terms; stage 2 judges them strictly with
  a verification pass. Up to 10 matches, at most 2 per call (the second only if it says the
  opposite). Untagged quotes you confirm are saved as accepted `context` highlights so they can
  back the belief. *This uses keyword retrieval, not embeddings: the app has no embedding model.*
- `scripts/eval_matching.py` checks matching against a list of beliefs you know are in the data
  ([`documentation/guides/matching-evaluation.md`](documentation/guides/matching-evaluation.md)).

**Retagging the library**
- `POST /api/taxonomy/retag` (admin only, dry run supported) queues calls in batches; the Settings
  page shows progress, an estimated duration, and a dry-run preview before anything is queued.
  A retag **keeps** highlights a person accepted or rejected and any suggestion that a decision
  cites or a confirmed hypothesis link uses. Before/after snapshots (`/snapshot`, `/compare`) and
  `scripts/retag_rollout.py` run the staged rollout: test set, then a 100-call pilot, a cost
  check, then resumable batches.

**Claude can read MomBoard (MCP server and API tokens)**
- **API tokens** (Settings → API tokens): `mb_` plus 32 random bytes, shown once, stored as a SHA-256 hash with an
  8-character prefix. Read-only by default, expiring in 30/90/365 days or never, 10 active per user; members manage
  their own, admins see and revoke all. A token acts as its owner and never exceeds their role; a read token can
  only make safe requests, no token can manage tokens, and every failure is the same 401. `Authorization: Bearer`
  also works on the REST API. `POST/GET /api/tokens`, `POST /api/tokens/{id}/revoke`.
- **An MCP server at `/mcp`** (Streamable HTTP, stateless; **off unless `MCP_ENABLED=true`**) with **13 read-only
  tools**: `list_tags`, `search_conversations`, `get_conversation`, `get_transcript`, `search_highlights`,
  `list_summaries`, `get_summary`, `list_hypotheses`, `get_hypothesis`, `list_decisions`, `get_decision`,
  `get_insights` and the no-save preview `check_hypothesis_evidence`. Tools call the same handlers as the app, so
  the per-tag confidence floor and permissions match; quotes are customer speech only; every item has a `url`
  that opens the source in MomBoard (the Conversation, Hypotheses, Decisions and Summaries pages now honour
  `?highlight=`, `?hypothesis=`, `?decision=` and `?summary=`).
- **Privacy**: contact emails and phone numbers are never returned, including inside quotes and transcripts
  (replaced with `[email removed]` / `[phone removed]`). Everything a tool returns is sent to the AI service the
  client uses, so confirm your agreement covers customer transcripts first.
- **Operations**: 60 tool calls a minute per token (HTTP 429 with `Retry-After`), 30-second tool timeout, 1 MB
  requests, an audit row per call in `mcp_calls` (token prefix, tool, short argument summary, outcome, duration;
  kept 90 days). Settings → **Connect to Claude** gives the exact URL, the header, Team-plan steps and a Claude
  Desktop config (with the `mcp-remote` bridge pinned to one version). Guide:
  [`documentation/deployment/mcp.md`](documentation/deployment/mcp.md).
- New optional filters on shared endpoints (company name, score range, minimum confidence, customer-only on
  `/api/conversations`, `/api/highlights` and `/api/stats`); existing callers are unaffected.
- **Not built**: write tools (`create_hypothesis`, `create_decision`) and OAuth. A connector shared across a Team
  plan has one identity, so writes wait for per-person sign-in. `MCP_ALLOW_WRITE` is reserved and does nothing yet.

**Interface**
- Tag filters: a "Most used" label; the Custom dropdown opens a category flyout on hover or click
  that is wide enough to read, closes with Escape (flyout first, then menu) and returns focus.
- Library: a message that distinguishes an empty library from filters that match nothing, a
  "Strong pains" preset (pain + workaround), compliments never in a row's top three signals,
  **a preview panel** when you click a row (summary, top pains, score, follow-ups, how many tag
  suggestions are waiting; the company name still opens the company page), **rows grouped by day**
  ("Today · Tue 10 Nov · 7 calls"; a day cut by a page edge says how many are *shown*), and four
  **headline cards** (total conversations, average score, pains captured, compliment ratio) that
  link to the page behind each number.
- Conversation: one "Review AI tags · N left" bar with a progress bar and "Accept all ≥ 0.9 (n)",
  Accept / Reject next to every suggested tag, and a transcript that fills the available width.
- Insights: trends are **weekly lines** with a point per week, "Trends appear after two weeks of
  calls" until then, and "Signal volume by tag" (it is a total). Trends follow the date the call
  happened, so a retag cannot flatten them. The headline score and ratio are now averages over
  every call (they used to show the newest bucket). Labels say counts include suggested highlights
  above the confidence floor.
- Practice: "Last score" shows the latest finished session instead of staying empty after a reload.
- Everywhere: one formatter, so numbers read `1,234` and dates `14 Sep 2026` (never a raw ISO
  string). A test fails if a page formats them by hand again.

**Behaviour changes to know about**
- The new tagger is stricter, so **tag counts will drop** once calls are retagged. Until then,
  old and new results sit side by side.
- Suggestions under a tag's floor are hidden in Library, Explore and Insights, but still appear in
  the conversation's review bar (judging them is what review is for).
- The match limit is now at most 2 per call (it was 1 unless the second was opposite), 10 overall.
- `GET /api/stats` now buckets `critique_trend` / `compliment_ratio_trend` **by week** (`date` is
  the Monday, `YYYY-MM-DD`) instead of by month, and adds `avg_critique_score` and
  `avg_compliment_ratio`. `tag_counts_by_month` is unchanged.
- `GET /api/highlights` gains `floor`, `sort=recent|confidence` and `per_call_cap`.
- Clicking a Library row opens the preview panel; "Open conversation" goes to the full page.

**Not done here**
- The hand-tagged test set and known-beliefs list contain customer text, so only the harnesses and
  synthetic examples are in the repo; you build the real ones. The pilot, cost and quality gates
  run against your data and LLM, so they are yours to run.
- Companies still have no structured segment field; the model judges segment from the company
  name and notes.

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
flagged as hunches). Design notes: [`documentation/design/`](documentation/design/).

The bet: MomBoard does not try to *be* a design or planning tool. It is the **evidence layer**
those tools stand on, so everything a reviewer needs to trust an AI-drafted epic (the quote, the
call, the hypothesis it supports) is reachable by the agent doing the drafting. The principles
behind this are in [`documentation/design/principles.md`](documentation/design/principles.md).

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

Not built in v0.3: Zoom ingestion (T37, no demand yet) and a model evaluation harness (T33; users
already choose models per agent). The original T26 idea of MomBoard generating concept mockups was
replaced on purpose by exposing evidence over MCP, so external design tools do the mockups.

## v0.2 — "From archive to advisor"

Made the repository talk back — prep before calls, nudges, cited answers, practice. Where v0.1
answered "what did customers say?", v0.2 answers "what should I do next?": before the call
(briefs), in practice (simulator), after it (hypotheses, decisions) and continuously
(staleness, digest, chat).

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
