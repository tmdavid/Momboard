# MomBoard

A Mom Test–based customer conversation repository. MomBoard ingests transcripts, extracts evidence-backed signals, critiques interview quality, supports human review, and provides cross-conversation exploration and synthesis.

## Status

**v0.2** — "From archive to advisor"

The core application (T01–T23, T27–T28) plus v0.2 features are implemented:

- Transcript ingestion for pasted text, `Name: text`, and WebVTT
- Database-backed normalize → tag → analyze → hypothesis-link worker pipeline
- Human review of suggested highlights and manual highlights
- Conversation notes with optimistic concurrency
- Library, conversation, explore, synthesis, insights, and hypotheses UI
- Session authentication, live Settings status, admin-managed taxonomy, and companies/contacts directory
- SQLite/PostgreSQL-compatible schema and Alembic migrations
- Production Docker/Fly configuration and rotating SQLite backups
- **T34 Staging inbox:** pending_import/ignored/imported/parse_error lifecycle, source_ref dedupe
- **T29/T30 Contact memory + drift:** timelines, drift detection, contact/company detail API
- **T38 Pre-call briefs:** compile history + suggest past-behavior questions, 1h cache
- **T24 Google Meet/Drive polling:** Drive Doc parser, fixture-pinned, parse_error retention
- **T41 Evidence staleness:** freshness bands computed read-time, integrated into hypotheses
- **T31 Weekly digest:** pure builder, Slack delivery, idempotent self-rescheduling
- **T42 Corpus chat:** SQL-first retrieval, validated citations, per-user chat storage
- **T25 MCP tools:** 7 tools (search, get, highlights, commitments, synthesis, create, ask_corpus) over stdio; an HTTP helper exists but is not mounted by default
- **T44 Quote cards:** 1600×900 PNG/SVG export with themes, anonymization, rejected guard
- **T35 Audio upload:** Whisper transcription with format/size validation, VTT-formatted output
- **T36 Vexa meeting bot:** configurable integration (VEXA_BASE_URL/VEXA_API_KEY), send/stop/preview/import with speaker-attributed transcript, deterministic dedupe
- **T39 Interview simulator:** persona builder from segment filters, chat loop with Mom Test behaviors, critique via standard worker chain, corpus isolation (simulated excluded from all corpus features)
- **T40 Decision log:** CRUD with evidence receipts, proposed→decided→superseded lifecycle, integrity checks (undermined on contradictions/drifts), automatic refresh in worker jobs, highlight deletion blocked (409) when cited, successor linkage
- **T43 Segment lenses:** compare two filter sets, per-side attribution validated in code, "Compare as lens" flow from Explore page

## Requirements

- Python 3.11
- Node.js 20+ and npm
- SQLite for local/single-node use; PostgreSQL is optional with the `postgres` dependency extra

## Coding-agent deployment

If you are a coding agent crawling this repository, start with [`agent-deployment.md`](agent-deployment.md) and treat it as the deployment contract: preserve existing `.env` and data, choose exactly one runtime mode, install from the project pins and npm lockfile, run Alembic then the idempotent taxonomy seed, build and verify the generated OpenAPI types and SPA, create an admin only from credentials supplied out of band, keep SQLite to one application process, and do not declare success until the health, OpenAPI, SPA, authentication, test, migration, and backup gates in that runbook pass. Production mutations and destructive recovery actions require explicit approval; report sanitized results and remaining warnings rather than guessing past a failure.

## Local setup

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

test -f .env || cp .env.example .env
mkdir -p data

.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed
.venv/bin/python -m app.users create \
  --email admin@example.com \
  --name 'Admin' \
  --role admin

npm ci --prefix web
npm run build --prefix web

.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open:

- Application: <http://127.0.0.1:8000>
- API documentation: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/healthz>

The user command prompts for a password without echoing it. Passing `--password` is supported for automation, but avoid it on shared machines because shell history may retain the value.

For frontend development with hot reload:

```bash
npm run dev --prefix web
```

The production build is served directly by FastAPI from `web/dist`.

## OpenAI configuration

MomBoard uses the OpenAI **Responses API** with strict structured JSON outputs. Tests never make real LLM calls.

1. Create an API key from <https://platform.openai.com/api-keys>.
2. Put it in the local `.env` file:

   ```dotenv
   OPENAI_API_KEY=sk-...
   ```

3. Optionally change the models:

   ```dotenv
   LLM_MODEL_NORMALIZER=gpt-5-mini
   LLM_MODEL_TAGGER=gpt-5-mini
   LLM_MODEL_ANALYST=gpt-5-mini
   LLM_MODEL_SYNTHESIZER=gpt-5-mini
   ```

The selected models must support the Responses API and structured outputs. Restart the application after changing `.env`.

### Running without an API key

Leaving `OPENAI_API_KEY` empty is supported for development:

- Deterministic transcript normalization still runs.
- Conversations still progress through the worker and reach `ready`.
- The tagger returns no AI highlights.
- The analyst stores a clearly marked placeholder analysis.
- Synthesis returns an empty structured report.

After configuring a real key, re-run an existing conversation with `POST /api/conversations/{id}/reprocess` (available through `/docs`). Accepted and rejected highlights are preserved; only AI suggestions are replaced.

### Local model hosting with Ollama

MomBoard optionally supports a local LLM backend via [Ollama](https://ollama.com) with a pinned `qwen3:8b` model — no OpenAI API key required.

When running MomBoard from source, start only the Compose-managed Ollama services:

```bash
docker compose --profile local-llm up -d ollama ollama-bootstrap
```

The bootstrap service pulls `qwen3:8b` on first use and then exits successfully. Configure the source process with:

```dotenv
LLM_BACKEND=local
LLM_BASE_URL=http://127.0.0.1:11434
LLM_LOCAL_MODEL=qwen3:8b
```

Use `LLM_BASE_URL=http://ollama:11434` only when the MomBoard application itself runs in Compose. If your Docker CLI reports `unknown flag: --profile`, use `docker-compose --profile local-llm up -d ollama ollama-bootstrap` instead.

> **Current Compose caveat:** `docker-compose.yml` still hardcodes the relative three-slash URL `sqlite+aiosqlite:///data/momboard.db`. Before starting the full application through Compose, change it to the absolute volume URL `sqlite+aiosqlite:////data/momboard.db`; otherwise it does not target the mounted `/data` database. The standalone Docker/Fly image already uses the correct absolute URL.

See [`local-llm.md`](local-llm.md) for configuration, model overrides, resource requirements, and backend switching.

### Security and customer data

- Never commit `.env` or API keys; `.gitignore` excludes them.
- Use a unique random `SESSION_SECRET` outside local development:

  ```bash
  openssl rand -base64 32
  ```

- Transcripts are customer data. Review your OpenAI account’s retention and regional-processing settings and deploy MomBoard in an approved region.
- Use the API product rather than consumer ChatGPT accounts for application traffic.

## Configuration

Copy `.env.example` to `.env`. Important variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy URL; defaults to local SQLite under `data/` |
| `SESSION_SECRET` | Signs login sessions; must be random in production |
| `LLM_BACKEND` | Selects `openai` or `local` |
| `OPENAI_API_KEY` | Enables real OpenAI tagging, analysis, and synthesis |
| `OPENAI_BASE_URL` | Optional OpenAI Responses API endpoint |
| `LLM_BASE_URL` | Ollama URL when `LLM_BACKEND=local`; host and Compose values differ |
| `LLM_LOCAL_MODEL` | Local model tag; defaults to `qwen3:8b` |
| `LLM_LOCAL_TIMEOUT` | Per-request timeout for slower local inference; defaults to 300 seconds |
| `LLM_MAX_CONTEXT` | Context budget used to size transcript chunks |
| `LLM_MODEL_*` | OpenAI model selection for each pipeline stage |
| `WORKER_POLL_INTERVAL` | Database queue polling interval |
| `WORKER_MAX_RETRIES` | Attempts before a job becomes terminally failed |

See `.env.example` for the complete list and `DEPLOY.md` for production setup, backups, restore, rollback, and PostgreSQL migration.

## Validation

```bash
# Backend
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests alembic scripts
.venv/bin/mypy app

# Database migration consistency
DATABASE_URL=sqlite+aiosqlite:///data/validation.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:///data/validation.db .venv/bin/alembic check

# Generated API contract + frontend
npm run openapi:check --prefix web
npm test --prefix web -- --run
npm run typecheck --prefix web
npm run build --prefix web
```

Docker smoke tests automatically skip when a Docker daemon is unavailable.

## Production

Follow [`agent-deployment.md`](agent-deployment.md) for the deployment gates and `DEPLOY.md` for Fly.io-specific creation, backup, restore, and rollback operations. The production image:

- Builds the React SPA in a Node stage
- Runs FastAPI on Python 3.11 as a non-root user
- Applies Alembic migrations at startup
- Uses a persistent `/data` volume
- Creates online SQLite backups and retains 14 days

Do not run multiple application processes against the same SQLite file. Move to PostgreSQL before scaling horizontally.
