# MomBoard — Deployment Runbook

> Coding agents: read [`docs/agent-deployment.md`](docs/agent-deployment.md) first. This file covers Fly.io operations after local installation and verification. Creating or changing applications, volumes, secrets, machines, scaling, restores, rollbacks, and production data requires explicit operator approval.

## Pre-deploy gate

Run locally before any Fly mutation:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests alembic scripts
.venv/bin/mypy app
npm run openapi:check --prefix web
npm test --prefix web -- --run
npm run typecheck --prefix web
npm run build --prefix web
docker build -t momboard:preflight .
fly config validate
```

Record failures and Docker-dependent skips. Do not deploy from a dirty or failing build unless the operator explicitly accepts the exact risk.

## Architecture Overview

- **Runtime:** Python 3.11, FastAPI, SQLite (WAL mode) on Fly.io
- **Volume:** 1 GB persistent at `/data` (database + backups)
- **Region:** `cdg` (Paris, EU)
- **Process model:** Single process (uvicorn + async background worker + backup scheduler)

---

## 1. Initial Fly.io Setup

### Prerequisites

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Authenticate
fly auth login
```

### Create Application

Fly application names are global. Choose a unique name, confirm the target Fly organization/account with the operator, and replace `momboard` in `fly.toml`, hostnames, image names, and commands below. Do not run these creation commands without explicit approval.

```bash
fly auth whoami

# From project root; replace with the approved globally unique name
fly apps create momboard

# Create persistent volume (1GB, Paris region)
fly volumes create momboard_data --app momboard --region cdg --size 1
```

### Set Secrets

Secret writes restart Fly machines and require explicit approval. Never paste secret values into an agent transcript or commit them.

```bash
# Always required (never commit this value)
fly secrets set SESSION_SECRET="$(openssl rand -base64 32)"

# OpenAI production backend
fly secrets set LLM_BACKEND=openai OPENAI_API_KEY="sk-your-key-here"

# Optional: override the current gpt-5-mini defaults
fly secrets set LLM_MODEL_TAGGER="gpt-5-mini"
```

MomBoard can start without `OPENAI_API_KEY`, but it then uses deterministic development fallbacks: no AI highlights, placeholder analysis, and empty synthesis. For production customer interviews, configure a key and verify that the selected models support the Responses API and strict structured outputs. A local Ollama sidecar is not included in `fly.toml`; do not select `LLM_BACKEND=local` on Fly until a separately provisioned, reachable Ollama service has been approved and secured.

---

## 2. Deploy

```bash
# First deploy (creates machines, applies migrations)
fly deploy

# Subsequent deploys
fly deploy

# Watch logs during deploy
fly logs --app momboard
```

The entrypoint automatically runs `alembic upgrade head` before starting uvicorn. This is safe for SQLite: the single-process architecture guarantees no concurrent migration attempts.

---

## 3. Seed Taxonomy and Create Admin User

The container entrypoint applies migrations but does not seed tags or create an admin. After the first deploy, open an interactive console, run the idempotent seed, and create the implemented user CLI account:

```bash
fly ssh console --app momboard

# Inside the machine:
cd /app
python -m app.seed
python -m app.users create \
  --email admin@example.com \
  --name 'Admin' \
  --role admin
```

The command prompts for the password twice without echoing it. Do not pass `--password` in an interactive production shell because it can remain in shell history. User creation is idempotent by email.

---

## 4. Health Verification

```bash
# Check application health and application surfaces
fly status --app momboard
base_url=https://momboard.fly.dev
curl -fsS "$base_url/healthz" | jq
curl -fsS "$base_url/openapi.json" >/dev/null
curl -fsS "$base_url/" | grep -q '<div id="root"></div>'
test "$(curl -sS -o /dev/null -w '%{http_code}' "$base_url/api/me")" = 401

# Expected health response:
# {"status": "ok", "version": "0.1.0"}
```

The Dockerfile includes a `HEALTHCHECK` and `fly.toml` configures Fly's HTTP check on `/healthz` with a 30s grace period at startup.

---

## 5. Backups

### How It Works

The application runs an in-process backup scheduler:
- **First backup:** 60 seconds after startup
- **Interval:** Every 24 hours
- **Method:** SQLite online backup API (`sqlite3.backup()`) — safe with concurrent reads/writes
- **Storage:** `/data/backups/momboard_YYYYMMDD_HHMMSS.db`
- **Retention:** 14 days (older backups are automatically deleted)

These backups share the application's `/data` volume. They protect against many application-level mistakes but not volume loss. Regularly download an integrity-checked backup to approved off-site storage; a production deployment is not recovery-ready until that copy has been verified.

### Verify Backups

```bash
fly ssh console --app momboard

# List backups
ls -la /data/backups/

# Verify latest backup integrity
sqlite3 /data/backups/momboard_20260815_190000.db "PRAGMA integrity_check; SELECT count(*) FROM conversations;"
```

### Manual Backup

```bash
fly ssh console --app momboard

python -c "
from app.backup import perform_backup
path = perform_backup('/data/momboard.db')
print(f'Backup created: {path}')
"
```

### Download Backup

```bash
# From your local machine
fly ssh sftp get /data/backups/momboard_20260815_190000.db ./local_backup.db
```

### Restore from Backup

A restore replaces production data and requires explicit approval naming the application, volume, source backup, and recovery point. Never copy over `/data/momboard.db` while MomBoard is running.

1. Download the candidate backup and verify it locally with `sqlite3 local_backup.db 'PRAGMA integrity_check;'`.
2. Download a second, current pre-restore backup from production and retain it off-site.
3. Put the application into an approved maintenance window and stop the only application machine. Confirm no process has the SQLite file open.
4. Attach the volume to a Fly recovery machine or use Fly's current volume recovery workflow, upload the verified database as `/data/momboard.db`, and preserve file ownership.
5. Remove the recovery machine, start exactly one application machine, and watch migrations/logs.
6. Run the complete health/API/SPA/auth verification gate and verify expected data with the operator.

Fly machine and volume identifiers are deployment-specific. Resolve them with `fly machines list --app momboard` and `fly volumes list --app momboard`; do not guess identifiers or automate a restore from this template alone.

---

## 6. Rollback

A production rollback changes running code and may make the schema incompatible. Obtain explicit approval for the target release, create/download a current backup first, and keep the deployment at one machine while SQLite is active.

### Rollback to Previous Release

```bash
# List recent deployments
fly releases

# Rollback to a specific release
fly deploy --image registry.fly.io/momboard:deployment-XXXXX

# Or re-deploy previous commit
git checkout <previous-sha>
fly deploy
```

### Rollback Database Migration

```bash
fly ssh console --app momboard

cd /app
# Check current revision
python -m alembic current

# Downgrade one step
python -m alembic downgrade -1

# Exit; restart to pick up old code
exit
```

> ⚠️ Only downgrade if you're also deploying the matching code version.

---

## 7. SQLite → PostgreSQL Migration

When scaling beyond a single machine or needing concurrent write throughput, plan and test a PostgreSQL migration. The SQLAlchemy schema is PostgreSQL-compatible, but the current Dockerfile runs `pip install .` and therefore does **not** install the `postgres` optional dependency (`asyncpg`). Do not set a PostgreSQL `DATABASE_URL` on the current image. First change the image install step to `pip install --no-cache-dir '.[postgres]'`, rebuild it, and validate migrations plus application tests against PostgreSQL.

### 1. Provision PostgreSQL

```bash
fly postgres create --name momboard-pg --region cdg
fly postgres attach --app momboard momboard-pg
```

### 2. Export SQLite Data

```bash
fly ssh console --app momboard

# Dump the SQLite database
sqlite3 /data/momboard.db .dump > /data/dump.sql
```

### 3. Import to PostgreSQL

```bash
# Download the dump
fly ssh sftp get /data/dump.sql ./dump.sql

# Convert SQLite SQL to PostgreSQL-compatible SQL
# (Manual fixups: AUTOINCREMENT → SERIAL, datetime formats, boolean literals)
# Or use pgloader:
pgloader sqlite:///path/to/local_backup.db postgresql://user:pass@host/momboard
```

### 4. Build a PostgreSQL-capable Image and Switch URL

Update the Dockerfile install command to include `.[postgres]`, build/test the resulting image, deploy that image while still on SQLite, and only then set the approved PostgreSQL URL:

```bash
# After changing and validating the Dockerfile
fly deploy
fly secrets set DATABASE_URL="postgresql+asyncpg://user:pass@momboard-pg.flycast:5432/momboard"
```

Do not place the real connection string in source control or an agent report.

### 5. Verify

```bash
curl -s https://momboard.fly.dev/healthz | jq
# Test API endpoints manually
```

### 6. Remove SQLite Volume (Optional)

This permanently destroys the volume and is not part of normal migration cleanup. Run it only after an approved retention period, verified PostgreSQL operation, and verified off-site backups, with explicit confirmation of the volume name immediately before execution.

```bash
fly volumes destroy momboard_data
```

---

## 8. Monitoring & Troubleshooting

```bash
# Live logs
fly logs --app momboard

# SSH into running machine
fly ssh console --app momboard

# Check disk usage
fly ssh console -C "df -h /data"

# Database size
fly ssh console -C "ls -lh /data/momboard.db"
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SESSION_SECRET` | Yes | — | Random 32+ char string for session signing |
| `LLM_BACKEND` | No | `openai` | Selects `openai` or `local` |
| `OPENAI_API_KEY` | For real OpenAI output | empty | Empty uses no-highlight/placeholder fallbacks |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///data/momboard.db` | Async SQLAlchemy connection string |
| `ENV` | No | `production` in image | Environment name |
| `PORT` | No | `8080` in image | HTTP port; Compose overrides this through `.env` and expects 8000 |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | Responses API base URL |
| `LLM_BASE_URL` | For local backend | empty | Ollama API URL reachable from the application |
| `LLM_LOCAL_FLAVOR` | No | `ollama` | Local provider implementation |
| `LLM_LOCAL_MODEL` | No | `qwen3:8b` | Model tag shared by local LLM stages |
| `LLM_LOCAL_TIMEOUT` | No | `300` | Per-request timeout in seconds for local inference |
| `LLM_MAX_CONTEXT` | No | `32768` | Context budget used for transcript chunking |
| `LLM_MODEL_NORMALIZER` | No | `gpt-5-mini` | OpenAI normalizer fallback model |
| `LLM_MODEL_TAGGER` | No | `gpt-5-mini` | OpenAI highlight extraction model |
| `LLM_MODEL_ANALYST` | No | `gpt-5-mini` | OpenAI conversation analysis model |
| `LLM_MODEL_SYNTHESIZER` | No | `gpt-5-mini` | OpenAI cross-conversation synthesis model |
| `WORKER_POLL_INTERVAL` | No | `2.0` | Background worker poll interval (seconds) |
| `WORKER_MAX_RETRIES` | No | `3` | Max job retries before permanent failure |

The standard Fly configuration does not provision Ollama. For Fly production, use OpenAI unless an external/private Ollama service has been separately approved, secured, monitored, and made reachable.
