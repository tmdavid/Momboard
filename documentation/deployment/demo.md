# MomBoard — Demo Deployment & Data Guide

A self-contained guide for standing up MomBoard as an **internal demo** on SQLite and
getting customer-conversation data into it. For the full deployment contract see
[`agent-deployment.md`](agent-deployment.md); for Fly.io operations see [`deploy.md`](deploy.md);
for local LLM hosting see [`local-llm.md`](local-llm.md).

This guide assumes: single node, SQLite, one application process.

---

## 1. Deploy with Docker Compose (recommended for a demo)

Docker Compose builds the React frontend and FastAPI backend into one container, serves
on port **8000**, persists data to `./data`, and restarts automatically.

### 1.1 One-time fix before first run

`docker-compose.yml` currently sets a **relative** SQLite URL that does not point at the
mounted `/data` volume:

```yaml
- DATABASE_URL=sqlite+aiosqlite:///data/momboard.db   # 3 slashes = relative (wrong)
```

Change it to the **absolute** path (four slashes) so data persists in the volume:

```yaml
- DATABASE_URL=sqlite+aiosqlite:////data/momboard.db  # 4 slashes = absolute (correct)
```

> The standalone Docker/Fly image already uses the correct absolute URL; this fix only
> applies to Compose.

### 1.2 Configure environment

```bash
test -f .env || cp .env.example .env

# Required outside local dev — signs login sessions:
echo "SESSION_SECRET=$(openssl rand -base64 32)" >> .env

# Optional — enables real AI tagging/analysis/synthesis.
# Leave empty to run with deterministic normalization + placeholder analysis.
# echo "OPENAI_API_KEY=sk-..." >> .env
```

### 1.3 Bring it up

```bash
docker compose up -d --build
```

### 1.4 Create an admin so people can log in

```bash
docker compose exec app python -m app.users create \
  --email admin@yourco.com --name 'Admin' --role admin
```

The command prompts for a password without echoing it.

### 1.5 Open it

- Application: <http://127.0.0.1:8000>
- API docs (Swagger): <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/healthz>

### 1.6 Let coworkers reach it

Run Compose on a shared internal host and share `that-host:8000`, or front it with an
internal reverse proxy / Tailscale. Avoid exposing it raw to the public internet.

### Alternative runtimes

- **Plain `docker run`** — the standalone `Dockerfile` serves on port **8080** and runs
  Alembic migrations automatically at startup:

  ```bash
  docker build -t momboard .
  docker run -d -p 8080:8080 -v "$(pwd)/data:/data" --env-file .env momboard
  ```

- **Fly.io** — `fly.toml` is pre-configured (Paris `cdg`, persistent `momboard_data`
  volume). Use this only if you want a hosted URL. See [`deploy.md`](deploy.md).

---

## 2. Get data in

All ingestion creates a **conversation**, which is then processed by the worker pipeline
(normalize → tag → analyze) until it reaches `ready`. Every method below requires being
logged in (session cookie) or, for scripts, admin credentials.

### 2.1 Paste or type in the UI (simplest)

Use the application's **new conversation** screen to paste transcript text. Three input
formats are supported:

- **Pasted free text**
- **`Name: text`** — one utterance per line, e.g. `Jane: What tools do you use today?`
- **WebVTT** (`.vtt` caption format)

Leave the format on auto-detect, or pick it explicitly.

### 2.2 REST API — `POST /api/conversations`

For scripted/bulk text ingestion. Request body (`ConversationCreate`):

| Field | Required | Notes |
|---|---|---|
| `title` | yes | Conversation title |
| `transcript` | yes | Raw transcript text |
| `transcript_format` | no | `auto` (default), `name_colon`, or `vtt` |
| `happened_at` | no | ISO-8601 timestamp |
| `interviewer` | no | Rep/"us" name; drives speaker-side attribution |
| `company` | no | `{ "name": "...", "domain": "..." }` |
| `contacts` | no | `[ { "name": "...", "role": "..." } ]` ("them") |
| `meta` | no | Arbitrary JSON; use `source_ref` for dedupe |

Returns `201` with the new conversation `id` and `status: processing`. Explore the live
schema at `/docs`.

### 2.3 Audio / video upload — `POST /api/conversations/upload`

Multipart form upload; transcribed via OpenAI Whisper (**requires `OPENAI_API_KEY`**).

- Form fields: `file` (required), `title` (required), `interviewer` (optional),
  `language` (optional ISO-639-1, e.g. `en`, `es`).
- Supported extensions: `.mp3 .mp4 .mpeg .mpga .m4a .wav .webm .ogg`
- Max size: **25 MB** (Whisper API limit).
- Output is stored as VTT-formatted, speaker-attributed text.

### 2.4 Clari Copilot import — `scripts/clari_ingest.py`

A **user-run** script (not a webhook) that pulls recorded calls from Clari Copilot,
converts each transcript to `Name: text`, and creates conversations via the MomBoard API.
Re-runs are safe: each conversation is stamped with `meta.source_ref = "clari:<call_id>"`
and already-imported calls are skipped.

Configure via env vars or `.env`:

```dotenv
CLARI_API_KEY=...
CLARI_API_PASSWORD=...          # sent as X-Api-Password (CLARI_API_SECRET is an alias)
# CLARI_BASE_URL defaults to https://rest-api.copilot.clari.com

MOMBOARD_BASE_URL=http://127.0.0.1:8000
MOMBOARD_EMAIL=admin@yourco.com
MOMBOARD_PASSWORD=...
```

Usage:

```bash
# Preview the latest call only (fast, no writes)
.venv/bin/python scripts/clari_ingest.py --dry-run --max-calls 1

# Preview the 50 newest recorded calls (default cap)
.venv/bin/python scripts/clari_ingest.py --dry-run

# Import a date window
.venv/bin/python scripts/clari_ingest.py --from 2026-08-01 --to 2026-08-31

# Import a single call by id
.venv/bin/python scripts/clari_ingest.py --call-id 665f...abc

# Re-import even if already present
.venv/bin/python scripts/clari_ingest.py --call-id 665f...abc --force
```

Speaker sides are usually inferred automatically (internal `users` → "us", external
participants → "them"); pass `--interviewer "Name"` to force attribution. See the script's
module docstring for Clari API quirks (status clustering, client-side date filtering).

> When MomBoard runs in Docker Compose (port 8000), run this script from the host against
> `MOMBOARD_BASE_URL=http://127.0.0.1:8000`.

### 2.5 Other built-in ingestion paths

- **Staging inbox** (`/api/inbox`) — pending_import/ignored/imported lifecycle with
  `source_ref` dedupe.
- **Vexa meeting bot** (`/api/vexa/import`) — speaker-attributed meeting transcripts.
- **Google Meet/Drive polling** — Drive Doc parser (fixture-pinned).

---

## 3. Running without an OpenAI key

Supported for a no-cost demo:

- Deterministic transcript normalization still runs; conversations reach `ready`.
- The tagger returns no AI highlights; the analyst stores a marked placeholder; synthesis
  returns an empty report.
- **Audio upload (2.3) does not work** without a key — it depends on Whisper.

After adding a real key later, backfill a conversation with
`POST /api/conversations/{id}/reprocess`. Accepted/rejected highlights are preserved;
only AI suggestions are replaced.

To use a local model instead of OpenAI, see [`local-llm.md`](local-llm.md) (Ollama +
`qwen3:8b`, ~8 GB RAM).

---

## 4. Demo caveats

- **SQLite = one application process.** Do not scale to multiple app containers or add
  Uvicorn workers. Move to PostgreSQL first if you need horizontal scale.
- **Customer data.** Transcripts are customer data. If you set `OPENAI_API_KEY`, review
  your OpenAI account's retention and regional-processing settings.
- **Secrets.** Never commit `.env`, API keys, or admin passwords.
- **Backups.** The container writes rotating SQLite backups under `/data/backups`, which
  share the application volume — not a substitute for an off-site copy.
