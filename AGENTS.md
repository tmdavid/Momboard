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
