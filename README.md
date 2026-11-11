# MomBoard

A Mom Test–based customer conversation repository. MomBoard ingests transcripts, extracts evidence-backed signals, critiques interview quality, supports human review, and provides cross-conversation exploration and synthesis.

## Status

**v0.4** — a redesigned interface, a Hypotheses board you can trust, and a Decisions page that keeps its receipts. v0.3's evidence layer (insights over MCP, evidence-gated intake, custom taxonomy) is complete. The full history is in [`CHANGELOG.md`](CHANGELOG.md); the v0.3 release definition is in [`V0.3.md`](V0.3.md) with design docs under [`docs/design/`](docs/design/).

### Latest additions (v0.4)

- **Hypotheses board by grounding band** — Grounded, Contested, Candidate, Hunch and Refuted, computed from the quotes you have *confirmed* (suggested matches never move a band). Each card says why it sits there and what is still missing; thresholds are settings (`HYPOTHESIS_*`, see below).
- **Evidence check before you save** — scored matches with their source, customer turns only, a segment-aware ranking, and a live "if saved now" band. Detail view with band history, validation questions, add-evidence and archive / restore.
- **Decisions that keep their receipts** — every cited quote is snapshotted, integrity updates when a tag is rejected or a call is deleted, and the page supports owner, area, drafts, editing, search, sort and the linked hypothesis (flagging one that was archived).
- **New interface** — a redesigned shell and pages, and tag filters with the 10 most common tags plus Core / Custom dropdowns.

### Earlier additions (v0.3)

- **Evidence-gated hypothesis intake (T48)** — add a belief and the corpus either backs it with evidence, shows weak matches, or prompts Mom Test questions, so hunches stay honestly labelled.
- **Read-only insight MCP tools (T46)** — hypotheses (with grounding and cited evidence) and decisions exposed over MCP for external agents to build on.
- **Custom taxonomy (T47)** — define your own tags, grouped by category, in Settings.
- **Clari source-call link** — imported conversations link back to the original recording.

### Core capabilities

- Transcript ingestion (pasted text, `Name: text`, WebVTT, audio/Whisper, Google Meet/Drive, Vexa, Clari) through a staging inbox with dedupe
- Database-backed normalize → tag → analyze → hypothesis-link pipeline on a concurrent worker pool with stale-job recovery
- Human review of highlights, conversation notes, and the Library / conversation / explore / synthesis / insights / hypotheses / summaries UI
- Advisor features: pre-call briefs, contact memory + drift, evidence staleness, weekly digest, corpus chat, interview simulator, decision log, segment lenses, quote cards
- Session auth, live Settings status, admin-managed taxonomy, companies/contacts directory
- Pluggable LLM backend — OpenAI, local Ollama, or AWS Bedrock (global, EU-resident by default) — with per-agent model selection
- SQLite/PostgreSQL-compatible schema, Alembic migrations, production Docker/Fly config, rotating backups

For the full per-release feature history, see [`CHANGELOG.md`](CHANGELOG.md).

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

### AWS Bedrock (compliant in-cloud inference)

For teams that require customer data to stay inside their own cloud, MomBoard supports a global Bedrock backend. When `LLM_BACKEND=bedrock`, **every** LLM feature — the normalize/tag/analyze/synthesize pipeline and all the v0.2 advisor features (briefs, digest, corpus chat, simulator, lenses, contact drift, hypothesis linking) — is routed through Amazon Bedrock. No transcript content is sent to OpenAI.

```dotenv
LLM_BACKEND=bedrock
AWS_REGION=eu-central-1
BEDROCK_MODEL_DEFAULT=eu.anthropic.claude-haiku-5-5
```

Credentials are resolved from the standard AWS provider chain (instance role, SSO, or `AWS_*` environment variables); MomBoard never reads or stores access keys. When no credentials resolve, the backend degrades to the same keyless `FakeLLMClient` behavior as OpenAI, so dev and tests still run.

**EU data residency.** The default model ID is the `eu.` cross-Region inference profile for Claude Haiku 5.5, which keeps inference within AWS's EU regions. Pair it with an EU `AWS_REGION` and a [Bedrock VPC (interface) endpoint](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html) so that inference traffic never leaves your account's EU footprint. Do **not** use the `global.` profile if residency matters — it may route outside the EU.

**Per-agent models.** Every agent defaults to `BEDROCK_MODEL_DEFAULT` but can be repointed independently with no code change. For example, keep the high-volume pipeline on cheap Haiku while running the reasoning-heavier agents on Sonnet:

```dotenv
BEDROCK_MODEL_ANALYST=eu.anthropic.claude-sonnet-5-5
BEDROCK_MODEL_SYNTHESIZER=eu.anthropic.claude-sonnet-5-5
BEDROCK_MODEL_BRIEF=eu.anthropic.claude-sonnet-5-5
```

The full set of overridable agent keys is: `normalizer`, `tagger`, `analyst`, `synthesizer`, `hypothesis_linker`, `chat`, `corpus_chat`, `brief`, `digest`, `persona`, `simulator`, `lens`, `drift_checker` (each via `BEDROCK_MODEL_<AGENT>`). Model IDs are config, not code, so you can also swap the default as Anthropic's lineup evolves. As with OpenAI, tests never make real Bedrock calls.

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
| `LLM_BACKEND` | Selects `openai`, `local`, or `bedrock` |
| `OPENAI_API_KEY` | Enables real OpenAI tagging, analysis, and synthesis |
| `OPENAI_BASE_URL` | Optional OpenAI Responses API endpoint |
| `LLM_BASE_URL` | Ollama URL when `LLM_BACKEND=local`; host and Compose values differ |
| `LLM_LOCAL_MODEL` | Local model tag; defaults to `qwen3:8b` |
| `LLM_LOCAL_TIMEOUT` | Per-request timeout for slower local inference; defaults to 300 seconds |
| `LLM_MAX_CONTEXT` | Context budget used to size transcript chunks |
| `LLM_MODEL_*` | OpenAI model selection for each pipeline stage |
| `WORKER_POLL_INTERVAL` | Database queue polling interval |
| `WORKER_MAX_RETRIES` | Attempts before a job becomes terminally failed |
| `HYPOTHESIS_GROUNDED_MIN_SUPPORT` / `_MIN_COMPANIES` / `_MAX_CONTRADICT` | Grounded needs this many confirmed supporting quotes from this many companies, and at most this many contradicting (defaults 3, 2, 1) |
| `HYPOTHESIS_CONTESTED_MIN_EACH` | Contested needs this many confirmed quotes on each side (default 2) |
| `HYPOTHESIS_REFUTED_MIN_CONTRADICT` / `_RATIO` | Refuted needs this many contradicting quotes, and more than ratio × the supporting ones (defaults 3, 2) |

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

### Upgrading to v0.4

v0.4 adds migrations 008–010 (additive; they only add columns and tables). The production container applies them on start. When running from source, stop the app and run `python scripts/migrate_v04.py` — it backs the database up first, runs `alembic upgrade head`, and verifies the result (`--dry-run` previews, `--verify-only` checks a running container's database without changing it). Then rebuild the frontend (`npm ci --prefix web && npm run build --prefix web`).

`scripts/retag_conversations.py` re-tags a date range through the API (dry run by default; it prompts for your password).
