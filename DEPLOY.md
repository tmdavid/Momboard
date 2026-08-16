# MomBoard — Deployment Runbook

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

```bash
# From project root
fly apps create momboard

# Create persistent volume (1GB, Paris region)
fly volumes create momboard_data --region cdg --size 1
```

### Set Secrets

```bash
# Always required (never commit this value)
fly secrets set SESSION_SECRET="$(openssl rand -base64 32)"

# Required for real tagging, analysis, and synthesis
fly secrets set OPENAI_API_KEY="sk-your-key-here"

# Optional: override defaults
fly secrets set LLM_MODEL_TAGGER="gpt-4o"
```

MomBoard can start without `OPENAI_API_KEY`, but it then uses deterministic development fallbacks: no AI highlights, placeholder analysis, and empty synthesis. For production customer interviews, configure a key and verify that the selected models support the Responses API and strict structured outputs.

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

## 3. Create Admin User

After the first deploy, open an interactive console and run the implemented user CLI:

```bash
fly ssh console --app momboard

# Inside the machine:
cd /app
python -m app.users create \
  --email admin@example.com \
  --name 'Admin' \
  --role admin
```

The command prompts for the password twice without echoing it. Do not pass `--password` in an interactive production shell because it can remain in shell history. User creation is idempotent by email.

---

## 4. Health Verification

```bash
# Check application health
fly status
curl -s https://momboard.fly.dev/healthz | jq

# Expected response:
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

```bash
fly ssh console --app momboard

# Stop the app process (Fly will restart it)
# Copy backup over the live database
cp /data/backups/momboard_20260815_190000.db /data/momboard.db

# Exit — Fly restarts the machine, migrations run on startup
exit
```

For a more controlled restore:

```bash
# Scale down to zero
fly scale count 0

# Restore via SFTP
fly ssh sftp shell
> put local_backup.db /data/momboard.db
> exit

# Scale back up (migrations run on start)
fly scale count 1
```

---

## 6. Rollback

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

When scaling beyond a single machine or needing concurrent write throughput:

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

### 4. Switch Database URL

```bash
fly secrets set DATABASE_URL="postgresql+asyncpg://user:pass@momboard-pg.flycast:5432/momboard"

# Add asyncpg dependency (already in optional deps)
# Rebuild with: pip install ".[postgres]"
fly deploy
```

### 5. Verify

```bash
curl -s https://momboard.fly.dev/healthz | jq
# Test API endpoints manually
```

### 6. Remove SQLite Volume (Optional)

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
| `OPENAI_API_KEY` | For real AI output | empty | OpenAI API key; empty uses no-highlight/placeholder fallbacks |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///data/momboard.db` | Database connection string |
| `ENV` | No | `production` | Environment name |
| `PORT` | No | `8080` | HTTP port |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | OpenAI-compatible API base |
| `LLM_MODEL_NORMALIZER` | No | `gpt-4o-mini` | Model for transcript normalization |
| `LLM_MODEL_TAGGER` | No | `gpt-4o` | Model for highlight extraction |
| `LLM_MODEL_ANALYST` | No | `gpt-4o` | Model for conversation analysis |
| `LLM_MODEL_SYNTHESIZER` | No | `gpt-4o` | Model for cross-conversation synthesis |
| `WORKER_POLL_INTERVAL` | No | `2.0` | Background worker poll interval (seconds) |
| `WORKER_MAX_RETRIES` | No | `3` | Max job retries before permanent failure |
