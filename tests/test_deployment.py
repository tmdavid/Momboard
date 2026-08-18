"""T23: Deployment, backup, and SPA fallback tests."""

import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.backup import (
    _db_path_from_url,
    _rotate_backups,
    perform_backup,
    verify_backup,
)
from app.config import Settings
from app.models import Base

# ─── Backup Tests ────────────────────────────────────────────────────────────


class TestBackupPerform:
    """Test SQLite online backup produces a restorable copy."""

    def test_backup_produces_valid_sqlite_file(self, tmp_path: Path):
        """Backup creates a valid, restorable SQLite copy."""
        # Create a source database with some data
        src_db = tmp_path / "source.db"
        conn = sqlite3.connect(str(src_db))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob')")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        result = perform_backup(src_db, backup_dir)

        # Backup file exists
        assert result.exists()
        assert result.stat().st_size > 0
        assert result.name.startswith("momboard_")
        assert result.suffix == ".db"

        # Backup is a valid SQLite database with correct data
        backup_conn = sqlite3.connect(str(result))
        rows = backup_conn.execute("SELECT name FROM users ORDER BY id").fetchall()
        assert rows == [("Alice",), ("Bob",)]
        backup_conn.close()

    def test_backup_integrity_check_passes(self, tmp_path: Path):
        """Backup passes SQLite integrity check."""
        src_db = tmp_path / "source.db"
        conn = sqlite3.connect(str(src_db))
        conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO conversations VALUES (1, 'Test call')")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        result = perform_backup(src_db, backup_dir)

        counts = verify_backup(result)
        assert "conversations" in counts
        assert counts["conversations"] == 1

    def test_backup_nonexistent_source_raises(self, tmp_path: Path):
        """Backup of non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            perform_backup(tmp_path / "nonexistent.db", tmp_path / "backups")

    def test_backup_creates_directory_if_missing(self, tmp_path: Path):
        """Backup creates the backup directory if it doesn't exist."""
        src_db = tmp_path / "source.db"
        sqlite3.connect(str(src_db)).close()

        backup_dir = tmp_path / "deep" / "nested" / "backups"
        assert not backup_dir.exists()

        perform_backup(src_db, backup_dir)
        assert backup_dir.exists()


class TestBackupRotation:
    """Test 14-day rotation of backup files."""

    def test_rotates_old_backups(self, tmp_path: Path):
        """Files older than retention_days are deleted."""
        # Create files with timestamps spanning 20 days
        now = datetime.now(UTC)
        for days_ago in range(20):
            dt = now - timedelta(days=days_ago)
            filename = f"momboard_{dt.strftime('%Y%m%d_%H%M%S')}.db"
            (tmp_path / filename).write_text("fake")

        deleted = _rotate_backups(tmp_path, retention_days=14)
        # Should delete files older than 14 days (days 15-19 = 5 files)
        assert len(deleted) >= 5

        # Recent files should remain
        remaining = list(tmp_path.glob("momboard_*.db"))
        assert len(remaining) <= 15

    def test_keeps_recent_backups(self, tmp_path: Path):
        """Recent files within retention window are kept."""
        now = datetime.now(UTC)
        for days_ago in range(5):
            dt = now - timedelta(days=days_ago)
            filename = f"momboard_{dt.strftime('%Y%m%d_%H%M%S')}.db"
            (tmp_path / filename).write_text("fake")

        deleted = _rotate_backups(tmp_path, retention_days=14)
        assert len(deleted) == 0

    def test_ignores_non_matching_files(self, tmp_path: Path):
        """Non-momboard files are not touched."""
        (tmp_path / "other_file.db").write_text("keep")
        (tmp_path / "random.txt").write_text("keep")

        deleted = _rotate_backups(tmp_path, retention_days=0)
        assert len(deleted) == 0
        assert (tmp_path / "other_file.db").exists()


class TestVerifyBackup:
    """Test backup verification utility."""

    def test_verify_valid_backup(self, tmp_path: Path):
        """Valid SQLite database passes verification."""
        db_file = tmp_path / "valid.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO tags VALUES (1, 'pain')")
        conn.execute("INSERT INTO tags VALUES (2, 'workaround')")
        conn.commit()
        conn.close()

        counts = verify_backup(db_file)
        assert counts == {"tags": 2}

    def test_verify_corrupt_file_raises(self, tmp_path: Path):
        """Corrupt file raises DatabaseError."""
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_bytes(b"not a sqlite file at all")

        with pytest.raises(sqlite3.DatabaseError):
            verify_backup(corrupt)


class TestDbPathFromUrl:
    """Test URL parsing for database path extraction."""

    def test_aiosqlite_absolute(self):
        assert _db_path_from_url("sqlite+aiosqlite:////data/momboard.db") == Path(
            "/data/momboard.db"
        )

    def test_aiosqlite_relative(self):
        assert _db_path_from_url("sqlite+aiosqlite:///data/momboard.db") == Path(
            "data/momboard.db"
        )

    def test_plain_sqlite(self):
        assert _db_path_from_url("sqlite:///data/app.db") == Path("data/app.db")

    def test_postgres_returns_none(self):
        assert _db_path_from_url("postgresql+asyncpg://user:pass@host/db") is None

    def test_memory_returns_none(self):
        # In-memory has empty path after ///
        result = _db_path_from_url("sqlite+aiosqlite://")
        assert result is None


# ─── SPA Fallback Tests ──────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def spa_app(tmp_path: Path):
    """Create app with a fake web/dist directory to test SPA routing."""
    # Create a temporary web/dist with index.html and assets
    dist_dir = tmp_path / "web" / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)

    (dist_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body><div id='root'></div></body></html>"
    )
    (assets_dir / "app.js").write_text("console.log('app');")
    (assets_dir / "style.css").write_text("body { margin: 0; }")
    (dist_dir / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")

    settings = Settings(
        database_url="sqlite+aiosqlite://",
        session_secret="test-secret",
        openai_api_key="",
        env="test",
    )

    from contextlib import asynccontextmanager
    from typing import Any

    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, Response
    from fastapi.staticfiles import StaticFiles
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def on_connect(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    application = FastAPI(title="MomBoard", version="0.1.0", lifespan=noop_lifespan)
    application.state.settings = settings
    application.state.engine = engine
    application.state.session_factory = session_factory

    @application.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "version": "0.1.0"}

    from app.api.router import api_router

    application.include_router(api_router, prefix="/api")

    from app.api.auth import auth_router

    application.include_router(auth_router)

    # Mount SPA exactly as production main.py does
    spa_path = dist_dir
    assets_path = spa_path / "assets"
    application.mount("/assets", StaticFiles(directory=str(assets_path)), name="spa-assets")

    @application.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str) -> Response:
        file_path = spa_path / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(spa_path / "index.html"))

    # Seed user for auth tests
    from app.auth import hash_password
    from app.models import User
    from app.seed import seed_tags

    async with session_factory() as session:
        await seed_tags(session)
        user = User(
            email="d@rp.com", name="David",
            password_hash=hash_password("pw"), role="admin",
        )
        session.add(user)
        await session.commit()

    yield application
    await engine.dispose()


@pytest_asyncio.fixture
async def spa_client(spa_app) -> AsyncClient:
    """Client against the SPA-enabled app."""
    async with AsyncClient(
        transport=ASGITransport(app=spa_app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
class TestSPAFallback:
    """Test that SPA client routes serve index.html without shadowing API."""

    async def test_root_returns_index_html(self, spa_client: AsyncClient):
        """GET / returns the SPA shell."""
        r = await spa_client.get("/")
        assert r.status_code == 200
        assert "<div id='root'></div>" in r.text

    async def test_conversations_deep_route_returns_index(self, spa_client: AsyncClient):
        """GET /conversations/1 returns SPA shell (client-side route)."""
        r = await spa_client.get("/conversations/1")
        assert r.status_code == 200
        assert "<div id='root'></div>" in r.text

    async def test_explore_returns_index(self, spa_client: AsyncClient):
        """GET /explore returns SPA shell."""
        r = await spa_client.get("/explore")
        assert r.status_code == 200
        assert "<div id='root'></div>" in r.text

    async def test_insights_returns_index(self, spa_client: AsyncClient):
        """GET /insights returns SPA shell."""
        r = await spa_client.get("/insights")
        assert r.status_code == 200
        assert "<div id='root'></div>" in r.text

    async def test_assets_served_directly(self, spa_client: AsyncClient):
        """GET /assets/app.js serves the actual JS file."""
        r = await spa_client.get("/assets/app.js")
        assert r.status_code == 200
        assert "console.log" in r.text

    async def test_favicon_served_directly(self, spa_client: AsyncClient):
        """GET /favicon.ico serves the actual file."""
        r = await spa_client.get("/favicon.ico")
        assert r.status_code == 200

    async def test_api_not_shadowed(self, spa_client: AsyncClient):
        """GET /api/me should return 401 (not index.html)."""
        r = await spa_client.get("/api/me")
        assert r.status_code == 401
        body = r.json()
        assert "detail" in body

    async def test_auth_not_shadowed(self, spa_client: AsyncClient):
        """POST /auth/login is handled by auth router, not SPA."""
        r = await spa_client.post(
            "/auth/login",
            json={"email": "wrong@test.com", "password": "wrong"},
        )
        # Should get 401 from auth handler, not 200 index.html
        assert r.status_code == 401

    async def test_healthz_not_shadowed(self, spa_client: AsyncClient):
        """GET /healthz returns JSON health check, not index.html."""
        r = await spa_client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"

    async def test_docs_not_shadowed(self, spa_client: AsyncClient):
        """GET /docs returns Swagger UI, not index.html."""
        r = await spa_client.get("/docs")
        assert r.status_code == 200
        assert "swagger" in r.text.lower() or "openapi" in r.text.lower()

    async def test_openapi_json_not_shadowed(self, spa_client: AsyncClient):
        """GET /openapi.json returns OpenAPI schema."""
        r = await spa_client.get("/openapi.json")
        assert r.status_code == 200
        body = r.json()
        assert "openapi" in body


# ─── Container Contract Tests ────────────────────────────────────────────────


class TestContainerContract:
    """Static checks for persistent storage and Docker command overrides."""

    project_root = Path(__file__).parent.parent

    def test_dockerfile_uses_absolute_data_volume_database(self):
        dockerfile = (self.project_root / "Dockerfile").read_text()
        assert 'DATABASE_URL="sqlite+aiosqlite:////data/momboard.db"' in dockerfile

    def test_entrypoint_execs_supplied_command_before_migrations(self):
        entrypoint = (self.project_root / "entrypoint.sh").read_text()
        passthrough = 'exec "$@"'
        migration = "python -m alembic upgrade head"
        assert passthrough in entrypoint
        assert entrypoint.index(passthrough) < entrypoint.index(migration)


# ─── Docker Build Tests ──────────────────────────────────────────────────────


def _docker_available() -> bool:
    """Check if Docker is available in the environment."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=10
        )
        # docker info may return 0 even when the builder driver is broken
        if result.returncode != 0:
            return False
        if "error" in (result.stderr or "").lower():
            return False
        # Extra check: try a minimal build to verify the builder is functional
        check = subprocess.run(
            ["docker", "build", "--help"],
            capture_output=True, text=True, timeout=5
        )
        if check.returncode != 0:
            return False
        # Try to verify daemon connectivity with a simple pull check
        ping = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=10
        )
        if ping.returncode != 0 or "error" in (ping.stderr or "").lower():
            return False
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available — required for container build/smoke tests",
)
class TestDockerBuild:
    """Test Docker image builds and runs correctly.

    Skipped when Docker is not available (CI without Docker, dev without daemon).
    """

    def test_docker_build_succeeds(self):
        """Multi-stage Dockerfile builds without errors."""
        project_root = Path(__file__).parent.parent
        result = subprocess.run(
            ["docker", "build", "-t", "momboard-test:latest", "."],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=300,
        )
        # Skip (don't fail) if the Docker builder driver is broken
        if result.returncode != 0 and "driver not connecting" in result.stderr:
            pytest.skip("Docker builder driver not connecting — cannot run build tests")
        assert result.returncode == 0, f"Docker build failed:\n{result.stderr}"

    def test_docker_image_has_correct_user(self):
        """Image runs as non-root user."""
        result = subprocess.run(
            ["docker", "run", "--rm", "momboard-test:latest", "whoami"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "momboard" in result.stdout.strip()

    def test_docker_image_has_web_dist(self):
        """Image contains built frontend files."""
        result = subprocess.run(
            ["docker", "run", "--rm", "momboard-test:latest", "ls", "/app/web/dist/index.html"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_docker_image_has_alembic(self):
        """Image contains Alembic migrations."""
        result = subprocess.run(
            ["docker", "run", "--rm", "momboard-test:latest", "ls", "/app/alembic/versions/"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "001_initial.py" in result.stdout
