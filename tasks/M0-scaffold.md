# M0 — Repo scaffold

## T01 — App factory + healthz + tooling

**Depends on:** nothing

**RED** — `tests/test_healthz.py`

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app

@pytest.mark.asyncio
async def test_healthz_returns_200_and_version():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "version" in r.json()
```

**GREEN**

- `app/main.py` with `create_app()` (app factory pattern — required later for test isolation).
- `app/config.py` using pydantic-settings (`Settings` with `database_url`, `openai_api_key`, `session_secret`, `env`), loaded from `.env`.
- `pyproject.toml` (uv or poetry), ruff + mypy config, `pytest.ini`/`pyproject` pytest config with `asyncio_mode = auto`.
- `Dockerfile` (python-slim, non-root user) + `docker-compose.yml` (app only for now).
- CI (GitHub Actions): lint → typecheck → test.

**Done when:** suite green, `docker compose up` serves `/healthz`, CI passes.

---

## T02 — Async DB wiring + Alembic + test fixtures

**Depends on:** T01

**RED** — `tests/test_db.py`

```python
@pytest.mark.asyncio
async def test_session_fixture_roundtrip(db_session):
    from sqlalchemy import text
    assert (await db_session.execute(text("select 1"))).scalar_one() == 1

def test_alembic_upgrade_head_on_empty_db(tmp_path):
    # runs `alembic upgrade head` against a fresh sqlite file; asserts exit ok
    ...

def test_metadata_matches_head_migration():
    # alembic-autogenerate against head produces NO diff (guards model/migration drift)
    ...
```

**GREEN**

- `app/db.py`: async engine from `settings.database_url` (`sqlite+aiosqlite` default), `async_sessionmaker`, SQLite pragmas (WAL, busy_timeout, foreign_keys=ON) via connection event hook that no-ops on other dialects.
- Alembic initialized (async template), `env.py` reading URL from settings; empty initial revision.
- `tests/conftest.py`: per-test SQLite file (or in-memory + StaticPool), `db_session` fixture with rollback isolation, `client` fixture (app + dependency-overridden session).
- CI matrix: add a Postgres job via testcontainers running the same suite (`DATABASE_URL` env switch).

**Done when:** suite green on SQLite and Postgres in CI; drift-guard test in place.
