# MomBoard

A Mom Test–based customer conversation repository. MomBoard ingests transcripts, extracts evidence-backed signals, critiques interview quality, supports human review, and provides cross-conversation exploration and synthesis.

## Status

The core application (T01–T23) is implemented:

- Transcript ingestion for pasted text, `Name: text`, and WebVTT
- Database-backed normalize → tag → analyze worker pipeline
- Human review of suggested highlights and manual highlights
- Conversation notes with optimistic concurrency
- Library, conversation, explore, synthesis, and insights UI
- Session authentication and admin-managed taxonomy
- SQLite/PostgreSQL-compatible schema and Alembic migrations
- Production Docker/Fly configuration and rotating SQLite backups

Not yet implemented:

- **T24 Google Meet ingestion:** Drive API polling and automatic import
- **T25 MCP server:** tools for external MCP clients

These items are tracked in `tasks/M6-M9-explore-deploy-future.md`.

## Requirements

- Python 3.11
- Node.js 20+ and npm
- SQLite for local use; PostgreSQL is optional

## Local setup

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

cp .env.example .env
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
   LLM_MODEL_NORMALIZER=gpt-4o-mini
   LLM_MODEL_TAGGER=gpt-4o
   LLM_MODEL_ANALYST=gpt-4o
   LLM_MODEL_SYNTHESIZER=gpt-4o
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
| `OPENAI_API_KEY` | Enables real tagging, analysis, and synthesis |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible API endpoint |
| `LLM_MODEL_*` | Model selection for each pipeline stage |
| `WORKER_POLL_INTERVAL` | Database queue polling interval |
| `WORKER_MAX_RETRIES` | Attempts before a job becomes terminally failed |

See `.env.example` for the complete list and `DEPLOY.md` for production setup, backups, restore, rollback, and PostgreSQL migration.

## Validation

```bash
# Backend
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests alembic
.venv/bin/mypy app

# Database migration consistency
DATABASE_URL=sqlite+aiosqlite:///data/validation.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:///data/validation.db .venv/bin/alembic check

# Frontend
npm test --prefix web -- --run
npm run typecheck --prefix web
npm run build --prefix web
```

Docker smoke tests automatically skip when a Docker daemon is unavailable.

## Production

Use `DEPLOY.md` for the full Fly.io runbook. The production image:

- Builds the React SPA in a Node stage
- Runs FastAPI on Python 3.11 as a non-root user
- Applies Alembic migrations at startup
- Uses a persistent `/data` volume
- Creates online SQLite backups and retains 14 days

Do not run multiple application processes against the same SQLite file. Move to PostgreSQL before scaling horizontally.
