# Coding-Agent Deployment Runbook

This is the canonical runbook for a coding agent that must turn a fresh MomBoard checkout into a verified deployment. Use it instead of inferring commands from individual configuration files. `README.md` is the short human entry point; `DEPLOY.md` contains the Fly.io operations detail.

## Operating contract

A coding agent should:

1. Work from the repository root and inspect `git status --short` before changing anything.
2. Never overwrite an existing `.env`, database, volume, backup, or admin account.
3. Keep secrets out of source control, command output, summaries, and logs.
4. Use one application process with SQLite. Do not add Uvicorn workers or scale to multiple machines until PostgreSQL is configured and the production image includes the `postgres` optional dependency.
5. Run migrations before seed/user commands. `python -m app.seed` is idempotent.
6. Treat production creation, deployment, secret changes, restores, rollbacks, volume deletion, and scaling as approval-gated actions.
7. Stop on a failed migration, test, health check, or model bootstrap. Report the failing command and relevant sanitized output instead of continuing blindly.

## Choose one mode

| Goal | Mode | Application URL | LLM |
|---|---|---|---|
| Fastest code/edit loop | Source | `http://127.0.0.1:8000` | Fake fallback, OpenAI, or host Ollama |
| Reproducible local deployment | Docker Compose | `http://127.0.0.1:8000` | Fake fallback, OpenAI, or Compose Ollama |
| Internet-accessible single-node production | Fly.io | Configured Fly hostname | OpenAI by default |

Do not mix source and Compose processes against the same SQLite file at the same time.

## Preflight

```bash
pwd
git status --short

PYTHON="${PYTHON:-python3.11}"
command -v "$PYTHON"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11); print(sys.version)'
node --version
npm --version
```

For container mode, also run:

```bash
docker --version
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose version
else
  docker compose version
fi
```

If Python 3.11+, Node 20+, npm, or the selected container runtime is unavailable, stop and report the missing prerequisite.

## Mode A: deploy from source

### 1. Install idempotently

```bash
PYTHON="${PYTHON:-python3.11}"
test -d .venv || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm ci --prefix web

test -f .env || cp .env.example .env
mkdir -p data
```

Do not replace an existing `.env`. For a new non-development environment, replace the placeholder session secret without printing the generated value:

```bash
python - <<'PY'
from base64 import b64encode
from os import urandom
from pathlib import Path

path = Path('.env')
text = path.read_text()
placeholder = 'SESSION_SECRET=change-me-in-production-use-a-random-32-char-string'
if placeholder not in text:
    raise SystemExit('Refusing to overwrite a non-placeholder SESSION_SECRET')
secret = b64encode(urandom(32)).decode()
path.write_text(text.replace(placeholder, f'SESSION_SECRET={secret}'))
PY
```

### 2. Choose the LLM backend

No API key is required for a UI/integration smoke test. With an empty `OPENAI_API_KEY`, deterministic normalization runs, tagging returns no AI suggestions, and analysis/synthesis use explicit placeholders.

For OpenAI, set these in `.env` without echoing the key:

```dotenv
LLM_BACKEND=openai
OPENAI_API_KEY=...
```

For Ollama running on the host:

```dotenv
LLM_BACKEND=local
LLM_BASE_URL=http://127.0.0.1:11434
LLM_LOCAL_MODEL=qwen3:8b
LLM_MAX_CONTEXT=8192
```

Then start/pull with your host Ollama installation. For Compose-managed Ollama, use Mode B and the container URL `http://ollama:11434`.

### 3. Prepare the database and frontend

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed
npm run openapi:check --prefix web
npm run build --prefix web
```

Create an admin only when credentials were supplied out of band. Referencing an environment variable keeps the literal password out of shell history:

```bash
: "${MOMBOARD_ADMIN_EMAIL:?Set MOMBOARD_ADMIN_EMAIL}"
: "${MOMBOARD_ADMIN_PASSWORD:?Set MOMBOARD_ADMIN_PASSWORD}"
.venv/bin/python -m app.users create \
  --email "$MOMBOARD_ADMIN_EMAIL" \
  --name "${MOMBOARD_ADMIN_NAME:-Admin}" \
  --role admin \
  --password "$MOMBOARD_ADMIN_PASSWORD"
unset MOMBOARD_ADMIN_PASSWORD
```

For a human-operated terminal, omit `--password` and use the non-echoing prompt. The automation form avoids shell-history literals but the password can be visible briefly to privileged process inspection. The command is idempotent by email; it does not rotate the password of an existing account.

### 4. Start

For an attached development process:

```bash
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

For an agent-managed background smoke deployment:

```bash
if test -f data/momboard.pid && kill -0 "$(cat data/momboard.pid)" 2>/dev/null; then
  echo 'MomBoard is already running'
else
  nohup .venv/bin/uvicorn app.main:create_app --factory \
    --host 127.0.0.1 --port 8000 --workers 1 \
    >data/momboard.log 2>&1 &
  echo $! > data/momboard.pid
fi
```

Stop only the PID recorded by this checkout:

```bash
test ! -f data/momboard.pid || kill "$(cat data/momboard.pid)"
rm -f data/momboard.pid
```

## Mode B: deploy with Docker Compose

### 1. Configure

```bash
test -f .env || cp .env.example .env
mkdir -p data
```

Keep `PORT=8000` in `.env`; the Compose port mapping and health check expect the container to listen on 8000. Do not use the Dockerfile's standalone default of 8080 for this Compose file.

Choose one LLM configuration:

```dotenv
# No-key smoke mode
LLM_BACKEND=openai
OPENAI_API_KEY=
```

```dotenv
# OpenAI
LLM_BACKEND=openai
OPENAI_API_KEY=...
```

```dotenv
# Compose Ollama
LLM_BACKEND=local
LLM_BASE_URL=http://ollama:11434
LLM_LOCAL_MODEL=qwen3:8b
LLM_MAX_CONTEXT=8192
```

### 2. Validate and start

Set a helper matching the installed Compose implementation:

```bash
if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE='docker-compose'
else
  COMPOSE='docker compose'
fi
$COMPOSE config -q
$COMPOSE up -d --build
```

For local Ollama, start the profile instead:

```bash
$COMPOSE --profile local-llm up -d --build
$COMPOSE logs -f ollama-bootstrap
```

The first model pull is several gigabytes and may take minutes. Wait for `ollama-bootstrap` to exit successfully. Do not treat an exited bootstrap container as a failure when its exit code is 0.

### 3. Seed and create an admin

Migrations run in `entrypoint.sh`; taxonomy seed and admin creation do not.

```bash
$COMPOSE exec app python -m app.seed

: "${MOMBOARD_ADMIN_EMAIL:?Set MOMBOARD_ADMIN_EMAIL}"
: "${MOMBOARD_ADMIN_PASSWORD:?Set MOMBOARD_ADMIN_PASSWORD}"
$COMPOSE exec -T app python -m app.users create \
  --email "$MOMBOARD_ADMIN_EMAIL" \
  --name "${MOMBOARD_ADMIN_NAME:-Admin}" \
  --role admin \
  --password "$MOMBOARD_ADMIN_PASSWORD"
unset MOMBOARD_ADMIN_PASSWORD
```

Prefer the interactive in-container prompt for a human operator. The automation form keeps the literal out of shell history but can expose it briefly to privileged process inspection. An existing email is reported and left unchanged.

## Verification gate

Run this gate for source or Compose deployments before declaring success:

```bash
base_url="${MOMBOARD_BASE_URL:-http://127.0.0.1:8000}"
for attempt in $(seq 1 30); do
  curl -fsS "$base_url/healthz" && break
  test "$attempt" -lt 30 || exit 1
  sleep 2
done

curl -fsS "$base_url/openapi.json" >/dev/null
curl -fsS "$base_url/" | grep -q '<div id="root"></div>'
test "$(curl -sS -o /dev/null -w '%{http_code}' "$base_url/api/me")" = 401
```

For Compose Ollama, also verify the model is installed:

```bash
curl -fsS http://127.0.0.1:11434/api/tags | grep -q 'qwen3:8b'
```

Run the repository quality gate after code or dependency changes:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests alembic scripts
.venv/bin/mypy app
npm run openapi:check --prefix web
npm test --prefix web -- --run
npm run typecheck --prefix web
npm run build --prefix web
```

Use a disposable database for migration verification:

```bash
validation_db="/tmp/momboard-validation-$$.db"
trap 'rm -f "$validation_db"' EXIT
DATABASE_URL="sqlite+aiosqlite:///$validation_db" .venv/bin/alembic upgrade head
DATABASE_URL="sqlite+aiosqlite:///$validation_db" .venv/bin/alembic check
```

Docker image tests skip automatically when no daemon is available. Report skips; do not report them as passes.

## Mode C: Fly.io production

Read `DEPLOY.md` before proceeding. A coding agent must obtain explicit approval before any command that creates or changes Fly applications, volumes, secrets, machines, scale, or production data.

Before requesting approval, run the local quality gate, a Docker build, and configuration validation:

```bash
docker build -t momboard:preflight .
fly config validate
```

Production invariants:

- Keep exactly one Fly machine while using SQLite.
- Mount the persistent volume at `/data`.
- Set a random `SESSION_SECRET` and an approved LLM backend/key through Fly secrets.
- Create the initial admin after the first successful deployment.
- Verify `/healthz`, `/openapi.json`, the SPA root, and unauthenticated `/api/me` behavior.
- Confirm a backup exists and download an off-site copy. `/data/backups` is useful for operational rollback but is not disaster recovery because it shares the application volume.
- The current Dockerfile installs SQLite runtime dependencies only. Before switching production to PostgreSQL, update the image install step to include `.[postgres]`, rebuild, and validate against PostgreSQL.

## Recovery and diagnosis

### Health check fails

Source mode:

```bash
tail -n 200 data/momboard.log
```

Compose mode:

```bash
$COMPOSE ps
$COMPOSE logs --tail=200 app
```

Check for migration errors, a mismatched `PORT`, an unwritable `data/` mount, or a missing `.env`.

### Database is locked

Stop duplicate source/Compose processes and ensure Uvicorn uses `--workers 1`. Never point multiple machines at the same SQLite file.

### Migration fails

Do not delete the database or stamp the revision. Preserve the database, capture `alembic current`, the failing revision, and sanitized logs. For production, take/download a backup before any corrective operation.

### SPA is missing or stale

```bash
npm ci --prefix web
npm run openapi:check --prefix web
npm run build --prefix web
test -f web/dist/index.html
```

Rebuild/restart the app or container after the frontend build.

### Local model is unavailable

```bash
curl -fsS http://127.0.0.1:11434/api/tags
$COMPOSE ps -a
$COMPOSE logs --tail=200 ollama ollama-bootstrap
```

Confirm that `LLM_BASE_URL` is `http://ollama:11434` inside Compose and `http://127.0.0.1:11434` for a source process. Ensure `LLM_LOCAL_MODEL` exactly matches a pulled model tag.

### Rollback or restore

Rollback and restore are destructive/high-risk operations. Follow `DEPLOY.md`, state exactly which release/database/backup will be affected, and wait for explicit approval. Never run `fly volumes destroy`, remove `data/`, or replace a live database as an automatic recovery step.

## Completion report

A coding agent should finish with a compact report containing:

- Mode deployed and URL
- LLM backend/model, without secrets
- Migration revision and seed/admin outcome
- Health/API/SPA/auth verification results
- Test/build results and skips
- Backup location and whether an off-site copy exists for production
- Files changed and any remaining warnings

Do not claim success if any required gate above failed.
