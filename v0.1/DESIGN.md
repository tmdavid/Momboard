# MomBoard — System Design

*A Mom Test–based customer conversation repository. Replaces the spreadsheet + one-GDoc-per-call workflow.*

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 + Alembic · SQLite (→ PostgreSQL later) · OpenAI Responses API · React (Vite) frontend
**Deployment target:** local first, then a small deploy (Fly.io / Railway) for a handful of teammates.

---

## 1. What it does

1. **Ingest** — upload a transcript (paste, .txt, .vtt, .docx) plus metadata (company, contact, date, who ran the call, deal stage…). Later: pull directly from Google Meet.
2. **Tag** — an LLM pipeline annotates the transcript with the Mom Test signal taxonomy (⚡ pain, ➡ workaround, 💰 money, ☆ follow-up, …), producing *highlights* anchored to exact quotes.
3. **Analyze** — per-conversation analysis: top pains, commitments vs. compliments, and a critique of *your* interviewing (did you ask about the past or pitch the future?).
4. **Explore** — filter/search across all conversations by tag, company, date, person; view a "quote wall" per tag; cross-conversation synthesis on demand.
5. **Notes** — a markdown notes panel per conversation (this is what replaces the attached GDoc).

Humans stay in the loop: every AI highlight can be accepted, edited, rejected, or added manually. AI output is a *draft*, never the record of truth until reviewed.

---

## 2. The Mom Test taxonomy (seed data)

| key | emoji | name | what it marks | signal |
|---|---|---|---|---|
| `pain` | ⚡ | Pain / problem | A problem the customer actually has | strong |
| `obstacle` | 🧱 | Obstacle | Something blocking them from solving it | strong |
| `workaround` | ➡️ | Workaround | What they already do to cope (past behavior!) | very strong |
| `emotion_pos` | 😄 | Excitement | Genuine excitement / strong positive emotion | strong |
| `emotion_neg` | 😠 | Anger / embarrassment | Strong negative emotion | strong |
| `context` | 🎯 | Background / context | Facts about their world, team, process | medium |
| `feature_request` | ☐ | Feature request / buying criteria | What they *say* they want — treat skeptically | weak |
| `money` | 💰 | Money / budget | Budget, willingness to pay, buying process | strong |
| `person` | 👤 | Intro / person | A specific person or company to talk to next | medium |
| `followup` | ☆ | Follow-up task | Something *we* must do next | n/a |
| `commitment` | 🤝 | Commitment | Gave up time, reputation, or money (advancement) | very strong |
| `compliment` | 🎈 | Compliment / fluff | "Sounds great, I'd totally use it" — zero signal | **anti-signal** |

The last two are additions beyond the book's note symbols but core to its thesis (commitment & advancement; compliments are lies). The taxonomy lives in a `tags` DB table seeded from this list, so you can extend it (e.g., Red Points–specific tags like `competitor_mention`) without code changes.

---

## 3. Architecture overview

```
┌────────────┐     ┌──────────────────────────────────────────┐
│ React SPA  │────▶│ FastAPI                                   │
│ (Vite)     │◀────│  /api/*  (REST + SSE for job progress)    │
└────────────┘     │                                           │
                   │  ┌──────────────┐   ┌──────────────────┐  │
                   │  │ Service layer │──▶│ SQLAlchemy repos │──▶ SQLite file
                   │  └──────┬───────┘   └──────────────────┘  │  (volume-mounted
                   │         │ enqueue                          │   in prod; swap
                   │  ┌──────▼───────────────────────────────┐ │   to Postgres via
                   │  │ Job worker (async task queue)         │ │   DATABASE_URL)
                   │  │  Pipeline: normalize → tag → analyze  │ │
                   │  │  (OpenAI Responses API, structured    │ │
                   │  │   outputs, per-agent prompts)         │ │
                   │  └───────────────────────────────────────┘ │
                   └──────────────────────────────────────────┘
```

Design rules that keep it simple *and* swappable:

- **One process.** FastAPI serves the API, the built SPA, and runs the job worker as an `asyncio` background task consuming a `jobs` table (poll every 2s). No Redis, no Celery. If you outgrow it, the `jobs` table is already the queue contract — swap the consumer for ARQ/Celery later without touching callers.
- **Repository pattern-lite.** Services never write raw SQL; everything goes through SQLAlchemy Core/ORM with dialect-neutral types. That plus Alembic is the whole Postgres migration story (§8).
- **LLM calls are isolated** in one module (`app/llm/`) with typed request/response models. Agents don't know about the DB; the pipeline orchestrator glues them.

---

## 4. Data model

All PKs are `Integer` autoincrement (SQLite `INTEGER PRIMARY KEY` → Postgres `IDENTITY`; SQLAlchemy handles both from the same model). The one exception is `tags.key`, which keeps a natural string PK (`pain`, `money`, …) so highlights are readable and seeds are stable. Since IDs are guessable, authorization checks on every object access are mandatory (they are anyway — all endpoints are behind auth). Timestamps are UTC `DateTime`. JSON uses SQLAlchemy's `JSON` type (works on SQLite, maps to `JSONB` on Postgres via a variant).

```
companies        contacts           conversations           utterances
─────────        ────────           ─────────────           ──────────
id               id                 id                      id
name             company_id FK      company_id FK ?         conversation_id FK
domain           name               title                   idx (order)
notes            role               happened_at             speaker_label
created_at       email              source (upload|gmeet)   speaker_side (us|them|unknown)
                 created_at         interviewer (str)       text
                                    raw_transcript (text)   start_ms ?  (if timed source)
                                    transcript_format
                                    meta (JSON)             highlights
                                    status                  ──────────
                                    created_at              id
                                                            conversation_id FK
conversation_contacts (m2m)                                 utterance_id FK ?
─────────────────────                                       tag_key FK → tags.key
conversation_id, contact_id                                 quote (verbatim text)
                                                            char_start, char_end ?
tags                    analyses                            note (str ?)
────                    ────────                            confidence (float)
key (PK, str)           id                                  origin (ai|human)
emoji                   conversation_id FK                  status (suggested|accepted|rejected)
name                    kind (conversation|synthesis)       created_by (user_id ?)
description             model, prompt_version               created_at
signal_strength         input_scope (JSON, for synthesis)
sort_order              result (JSON)                       notes
is_active               created_at                          ─────
                                                            id
users                   jobs                                conversation_id FK (unique)
─────                   ────                                body_md (text)
id                      id                                  updated_by, updated_at
email                   kind (ingest|tag|analyze|synthesize)
name                    payload (JSON)
role (admin|member)     status (queued|running|done|error)
created_at              error (str ?), attempts
                        created_at, started_at, finished_at
```

Notes on the choices:

- **`utterances`** — the normalizer splits every transcript into ordered utterances with a speaker. Highlights anchor to an utterance + verbatim quote, which makes the UI trivial (render utterances, decorate the tagged ones) and survives re-formatting. `char_start/char_end` within the utterance are optional precision.
- **`highlights.status`** — the human-in-the-loop switch. AI writes `suggested`; the UI is where you accept/reject. Filters default to `accepted OR suggested` with a visual distinction.
- **`analyses.result` as JSON** — analysis output shape will evolve fast; don't schema-freeze it in SQL. `prompt_version` + `model` recorded on every row so you can re-run and compare.
- **`meta` on conversations** — free-form JSON for whatever your spreadsheet columns are today (deal stage, plan, region, source of lead…). Promote a field to a real column only when you need to index/filter on it heavily.
- **`notes.body_md`** — one markdown doc per conversation. This is the GDoc replacement. Autosaved, `updated_at` for conflict detection (last-write-wins is fine for ≤5 users).

### Search

Start with SQL `LIKE` over `utterances.text` + `highlights.quote` behind a `SearchService` interface. If it feels slow past a few hundred conversations, add SQLite FTS5 (contentless table synced by trigger) — and on Postgres the same interface is implemented with `tsvector`. The interface is the contract; the engine is disposable.

---

## 5. The agent pipeline (OpenAI Responses API)

Three agents run in sequence per conversation, plus one on-demand. Every agent is a single Responses API call with **structured outputs** (`text.format = json_schema, strict: true`) — no free-text parsing, ever. Store `response.id`, model, and prompt version with each result.

### 5.1 Normalizer agent — `ingest`

**In:** raw transcript text + declared format hint.
**Out (schema):** `{ utterances: [{ idx, speaker_label, speaker_side, text }], detected_participants: [...], language }`

Deterministic parsing first: VTT and "Name: text" formats are parsed in Python; the LLM is only invoked for messy pastes (no speaker labels, wall of text) or to classify which speaker is "us" vs "them" given the interviewer name from metadata. Cheap model (e.g. `gpt-5-mini`-class).

### 5.2 Tagger agent — `tag`

**In:** utterances (numbered), taxonomy (from DB, so custom tags flow in automatically), conversation metadata.
**Out (schema):**

```json
{
  "highlights": [{
    "utterance_idx": 42,
    "tag_key": "workaround",
    "quote": "so every Monday I export it to Excel and clean it by hand",
    "confidence": 0.92,
    "rationale": "Describes actual recurring past behavior, not hypothetical"
  }]
}
```

Prompt encodes the book's discipline as hard rules:

- Tag `workaround`/`pain` only for **past or current behavior**, never hypotheticals ("I would…" → not a workaround).
- Compliments get tagged `compliment` explicitly — surfacing fluff is a feature, not noise to drop.
- `commitment` requires an explicit cost: time booked, intro promised, money discussed, pilot agreed.
- Quotes must be **verbatim substrings** of the utterance (validated in code post-response; non-matching quotes are fuzzy-matched or dropped with a warning).
- Long transcripts: chunk by ~80 utterances with 10 overlap; dedupe highlights on (utterance_idx, tag_key).

### 5.3 Analyst agent — `analyze`

**In:** utterances + the accepted/suggested highlights.
**Out (schema):** stored in `analyses.result`:

```json
{
  "summary": "3-5 sentence factual summary",
  "top_pains": [{ "pain": "...", "evidence_highlight_ids": [...], "severity": "high" }],
  "commitments": [{ "what": "...", "type": "time|reputation|money", "next_step": "..." }],
  "compliment_ratio": 0.31,
  "mom_test_critique": {
    "score": 7,
    "good_questions": ["asked how they handle X today"],
    "violations": [{ "utterance_idx": 12, "type": "pitched_the_idea", "better": "ask what they did last time X happened" }]
  },
  "suggested_followups": ["..."],
  "open_questions": ["..."]
}
```

The `mom_test_critique` is the piece no off-the-shelf tool has: it grades the **interviewer**, not the customer — fishing for compliments, pitching too early, future-hypothetical questions, failing to push for commitment.

### 5.4 Synthesizer agent — `synthesize` (on demand)

**In:** a filtered set (e.g. "all ⚡pain highlights from enterprise customers, last quarter") — highlights + minimal context, *not* full transcripts.
**Out:** clustered themes with evidence links, contradiction spotting ("3 said X, 2 do the opposite"), and a "what to validate next" list. Stored as `analyses` row with `kind = synthesis` and the filter recorded in `input_scope`.

### Pipeline mechanics

- `POST /conversations` → creates row → enqueues `ingest` job → on success enqueues `tag` → then `analyze`. Each stage idempotent (re-running replaces prior `suggested` highlights, never touches `accepted`/`rejected` ones).
- Worker retries 3× with exponential backoff; terminal failures land in `jobs.error` and surface in the UI.
- Progress via SSE: `GET /conversations/{id}/events` streams job state changes so the UI shows "Tagging… → Analyzing… → Done".
- Cost control: tagger + analyst on a mid-tier model; normalizer on mini; synthesizer on the big model. All model names in config, not code.

---

## 6. API surface (FastAPI)

```
Auth      POST /auth/login (email+password), session cookie; seed users via CLI
Convos    POST   /conversations                (metadata + transcript → starts pipeline)
          GET    /conversations                (filters: tag, company, contact, date range,
                                                status, q=search, has_commitment…)
          GET    /conversations/{id}           (full: utterances, highlights, analysis, note)
          PATCH  /conversations/{id}           DELETE /conversations/{id}
          POST   /conversations/{id}/reprocess (re-run tag/analyze, e.g. after prompt bump)
          GET    /conversations/{id}/events    (SSE job progress)
Highlights POST  /conversations/{id}/highlights           (manual add)
          PATCH  /highlights/{id}              (accept/reject/edit/retag)
Notes     GET/PUT /conversations/{id}/note     (markdown, autosave)
Explore   GET    /highlights                   (cross-convo, same filters → quote wall)
          GET    /stats                        (tag counts over time, compliment ratios,
                                                critique scores trend)
Synthesis POST   /syntheses  { filters }       GET /syntheses/{id}
Admin     GET/POST/PATCH /tags                 GET/POST /companies /contacts
```

Pydantic models everywhere; OpenAPI docs for free — which also gives coding agents a machine-readable contract to build the frontend against.

---

## 7. Frontend (React + Vite, kept deliberately small)

Four pages:

1. **Library** — the spreadsheet replacement. Table of conversations: date, company, contact, tag-count chips (⚡3 💰1 🤝1 🎈4), critique score, status. Filter bar (tags, company, date, text search). Row click → Conversation. "New conversation" → upload/paste + metadata form.
2. **Conversation** — three-pane: transcript (utterances, speaker-colored, tagged ones decorated with emoji chips; click a chip to accept/reject/edit), right sidebar with the analysis card (summary, pains, commitments, critique), bottom/side toggle for the **markdown notes panel** (the GDoc replacement). Keyboard-first review mode: `j/k` next/prev suggestion, `a` accept, `x` reject.
3. **Explore** — pick tags + filters → quote wall of highlights, each linking back to its spot in the conversation. Button: "Synthesize this view" → runs the synthesizer, renders the themed report.
4. **Insights** — simple charts: highlights per tag over time, compliment-ratio trend (are your interviews getting less fluffy?), critique score trend, commitments pipeline (open follow-ups ☆ across conversations — your action list).

State: TanStack Query against the REST API; no global store needed. Styling: Tailwind. Ship the built SPA from FastAPI's static files — one deployable.

---

## 8. SQLite now → Postgres later

The swap is a config change if you hold these rules from day one:

1. `DATABASE_URL` env var; engine created from it. Dev: `sqlite+aiosqlite:///data/momboard.db`, later `postgresql+asyncpg://…`.
2. Alembic from the first migration. Never `create_all` in prod paths.
3. Portable types only: `Integer` autoincrement PKs (SQLAlchemy emits `IDENTITY` on Postgres automatically), `JSON` (with `JSONB` variant), `DateTime(timezone=True)`, no SQLite-only pragmas in models. No DB-generated defaults that differ across dialects — set defaults in Python.
4. SQLite pragmas (`WAL`, `busy_timeout`) applied via connection event hook, harmless no-op paths for Postgres.
5. Anything engine-specific (FTS5) lives behind a service interface with a per-dialect implementation.
6. CI runs the test suite against **both** SQLite and Postgres (via `testcontainers`) so drift can't sneak in.

Migration day: spin up Postgres, `alembic upgrade head`, copy rows preserving IDs (a 50-line script or `pgloader`), then reset each table's identity sequence to `max(id)+1` (`setval`), flip `DATABASE_URL`.

---

## 9. Config, security, deployment

- **Config:** pydantic-settings; `.env` for `DATABASE_URL`, `OPENAI_API_KEY`, `SESSION_SECRET`, model names, prompt versions.
- **Auth:** email + password (argon2), server-side session cookie, `admin` can manage users/tags. No self-signup. That's enough for ≤5 trusted users; add SSO only if Red Points IT ever asks.
- **Privacy:** transcripts are customer data — deploy in EU region (Fly.io `ams`/`cdg`), volume-encrypted, and use OpenAI API (not consumer ChatGPT) so data isn't trained on; consider their EU data residency options.
- **Deploy:** single Dockerfile (multi-stage: build SPA → copy into Python image). Fly.io with a 1GB volume mounted at `/data` for the SQLite file + uploads. `fly deploy` is the whole CD story. Nightly `sqlite3 .backup` to the volume + optional object-storage upload.

---

## 10. Build plan for coding agents

Milestones sized so each is one agent session with a crisp acceptance test. Later milestones depend only on the *contracts* (schemas, OpenAPI) of earlier ones, so M4–M6 can run in parallel once M1–M3 land.

| # | Milestone | Acceptance criteria |
|---|---|---|
| M0 | Repo scaffold: FastAPI app factory, SQLAlchemy async setup, Alembic, pytest, Docker, CI (lint+test on SQLite & Postgres) | `docker compose up` serves `/healthz`; `alembic upgrade head` works on both DBs |
| M1 | Schema + migrations + seed (tags taxonomy, admin user CLI) | All tables per §4; `python -m app.seed` idempotent |
| M2 | Conversations CRUD + deterministic normalizer (VTT & "Name: text") + jobs table + worker loop | Upload a fixture VTT → utterances rows exist; job lifecycle states correct; SSE emits |
| M3 | LLM module: Responses API client wrapper, structured-output schemas, prompt registry with versions; tagger + verbatim-quote validator | Given a fixture transcript + mocked API, highlights persist as `suggested`; quote validation drops fabricated quotes (unit-tested) |
| M4 | Analyst agent + analyses storage + reprocess endpoint | Fixture conversation gets `analyses` row matching schema §5.3; reprocess preserves accepted/rejected highlights |
| M5 | Frontend: Library + Conversation pages incl. highlight review + notes panel | Full flow clickable against real API; keyboard review works |
| M6 | Explore + quote wall + synthesizer + Insights charts | Filtered synthesis produces stored report with evidence links |
| M7 | Auth, Dockerfile final, Fly.io deploy, backups | Teammate can log in on deployed URL; nightly backup file appears |
| M8 | (Later) Google Meet ingestion: Drive API poll for Meet transcript docs → auto-create conversations | New Meet transcript in a watched Drive folder appears as a conversation within 15 min |

Conventions to give every agent (put in `CLAUDE.md`/`AGENTS.md` at repo root): async everywhere; services thin, repos thinner; every LLM schema has a Pydantic twin + fixture-based test with mocked responses; no new dependency without a one-line justification in the PR; migrations never edited after merge.

### Fixtures to create by hand (worth the hour)

Three real-ish anonymized transcripts: one great interview (lots of ⚡➡🤝), one compliment-heavy disaster (🎈🎈🎈), one messy unlabeled paste. These power tests, prompt iteration, and the demo. Golden-file tests pin tagger prompt regressions: same fixture + prompt version → expected highlight set (allowing confidence drift).

---

## 11. Future ideas (explicitly out of scope now)

Google Meet auto-ingest (M8, via Drive API — Meet saves transcripts as Docs), audio upload + Whisper transcription, Slack digest of new commitments/follow-ups each Friday, contact-level timelines ("everything Acme ever told us"), embedding-based similar-quote search (pgvector once on Postgres), CRM linkage (attach a Salesforce/HubSpot deal id in `meta`).

**And the big one: an MCP server on top of the repository.** Because all reads already go through the service layer, exposing an MCP server (Python `mcp` SDK, streamable-HTTP transport, reusing the same auth) is mostly wiring: tools like `search_conversations(filters)`, `get_conversation(id)`, `get_highlights(tag, company, date_range)`, `get_commitments(open_only)`, `run_synthesis(filters)`. Then any chat app that speaks MCP — Claude, ChatGPT, Slack bots, your IDE — can answer "what pains did enterprise customers mention last quarter?" directly from the repository, with quotes as evidence. The inverse direction also gets cheap: a `create_conversation(transcript, metadata)` tool means any MCP-speaking client can push a transcript in, which is another road to the Google Meet ingestion story. This slots in as M9 with zero schema changes — it's an API consumer like the SPA.
