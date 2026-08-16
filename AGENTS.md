# AGENTS.md — Coding Agent Conventions

## Stack
- Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, pydantic v2
- pytest + pytest-asyncio + httpx AsyncClient + respx for mocked HTTP
- LLM calls: OpenAI Responses API with structured outputs (JSON Schema, strict: true)

## Architecture rules
- **Async everywhere.** Services thin, repos thinner.
- **One process.** Worker runs as asyncio background task within FastAPI lifespan.
- **Repository pattern-lite.** No raw SQL; everything through SQLAlchemy ORM/Core.
- **Portable types only:** `Integer` autoincrement PKs, `JSON().with_variant(JSONB, "postgresql")`, `DateTime(timezone=True)`. No dialect-specific DDL in models.
- **LLM calls isolated** in `app/llm/`. Agents never touch the DB directly; the pipeline glues them.
- **Every LLM schema** has a Pydantic twin in `app/llm/schemas.py` validated by tests.

## Testing
- LLM calls are **never real in tests**. Use `FakeLLMClient` with fixture JSON from `tests/fixtures/llm/`.
- DB tests run against SQLite in-memory (CI adds Postgres via testcontainers).
- No test may depend on autoincrement values across tables.
- Golden-file tests pin tagger prompt regressions.

## Migrations
- Alembic from the first migration. Never `create_all` outside tests.
- Never edit a merged migration. Add a new revision instead.
- `render_as_batch=True` for SQLite ALTER TABLE compatibility.

## Dependencies
- No new dependency without a one-line justification.
- Pin exact versions in pyproject.toml.
- `openapi-typescript` (7.4.4, devDependency): generates TypeScript types from FastAPI's OpenAPI schema for T14 type-safety contract.

## Code quality
- Ruff (select E, F, I, N, W, UP) + mypy (strict: false, warn_return_any: true, pydantic plugin).
- Every `/api/*` route is behind `require_user` by router-level dependency.
- Auth boundaries: admin-only routes use `require_admin`.

## LLM pipeline
- Normalizer → Tagger → Analyst (sequential, per conversation)
- Synthesizer (on-demand, cross-conversation)
- Tagger validates quotes verbatim (exact → fuzzy → drop); drops unknown tag keys.
- Analyst input excludes rejected highlights; evidence IDs validated post-hoc.
- Reprocess preserves `accepted`/`rejected` highlights; replaces only `suggested`.

## Deployment and operations
- [`docs/agent-deployment.md`](docs/agent-deployment.md) is the canonical coding-agent runbook. Do not improvise a second setup sequence in task output.
- Preserve an existing `.env`, `data/`, Docker volume, database, and backup. Copy `.env.example` only when `.env` is absent.
- Choose one runtime mode per database: source or Docker Compose. SQLite requires one Uvicorn worker and one application machine/process.
- The order is: install → configure → `alembic upgrade head` → `python -m app.seed` → OpenAPI check/frontend build → optional admin creation → start → verification gate.
- Migrations run automatically in the production container entrypoint; taxonomy seed and admin creation do not.
- Docker Compose requires `.env` and expects `PORT=8000`. The standalone Docker/Fly image defaults to port 8080.
- For local Ollama, use `LLM_BASE_URL=http://127.0.0.1:11434` from a host process and `http://ollama:11434` from Compose.
- Never print or commit session secrets, API keys, or admin passwords. Create an admin only when credentials are supplied out of band.
- Production deploys, secret changes, scaling, restores, rollbacks, and volume deletion require explicit approval before execution.
- A deployment is complete only after health, OpenAPI, SPA, unauthenticated-auth-boundary, migration, tests, and build checks pass. Report Docker-dependent skips and do not relabel them as passes.
- SQLite backups under `/data/backups` share the application volume; production recovery also requires a verified off-site copy.

## Generated API contract
- Any API schema or `response_model` change must be followed by `npm run openapi:check --prefix web`.
- Commit/update `web/src/generated/openapi.ts`; never hand-edit it.
- Run frontend tests, typecheck, and build after regeneration.
