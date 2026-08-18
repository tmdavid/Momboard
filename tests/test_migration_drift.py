"""T02 RED: Alembic fresh-upgrade and model/migration drift detection.

These tests verify:
- Alembic can upgrade from empty to head on a fresh database (SQLite & Postgres portable)
- The ORM model metadata matches the actual migration state (no drift)
- All expected tables exist after upgrade
"""

import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.models import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ALL_TABLES = {
    "companies",
    "contacts",
    "conversations",
    "conversation_contacts",
    "utterances",
    "tags",
    "highlights",
    "analyses",
    "notes",
    "users",
    "jobs",
}


def test_alembic_upgrade_head_on_empty_db(tmp_path):
    """Run 'alembic upgrade head' against a fresh SQLite file; assert exit 0 and tables created."""
    db_path = tmp_path / "test_alembic.db"
    db_url = f"sqlite:///{db_path}"

    env = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "SESSION_SECRET": "test",
        "OPENAI_API_KEY": "",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (
        result.returncode == 0
    ), f"Alembic upgrade failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    # Verify tables exist using synchronous engine
    engine = create_engine(db_url)
    with engine.connect() as conn:
        table_names = set(inspect(conn).get_table_names())

    assert ALL_TABLES <= table_names, f"Missing tables: {ALL_TABLES - table_names}"
    engine.dispose()


def test_metadata_matches_head_migration():
    """Alembic autogenerate against head produces NO diff — guards model/migration drift.

    This ensures that models.py and the migration files stay in sync.
    Any new model column or constraint that is missing from a migration will cause this to fail.
    """
    from sqlalchemy import create_engine

    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.runtime.environment import EnvironmentContext
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    # Run migrations against an in-memory DB
    engine = create_engine("sqlite://")
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", "sqlite://")

    script = ScriptDirectory.from_config(alembic_cfg)

    with engine.connect() as conn:
        # Apply all migrations
        _context = MigrationContext.configure(conn)

        # We need to run upgrade programmatically
        with EnvironmentContext(
            alembic_cfg,
            script,
            fn=lambda rev, ctx: script._upgrade_revs("head", rev),
            as_sql=False,
            destination_rev="head",
        ) as env_ctx:
            env_ctx.configure(
                connection=conn,
                target_metadata=Base.metadata,
                render_as_batch=True,
            )
            with env_ctx.begin_transaction():
                env_ctx.run_migrations()

        # Now compare metadata with migrated state
        mc = MigrationContext.configure(conn)
        diff = compare_metadata(mc, Base.metadata)

    engine.dispose()

    # Filter out irrelevant diffs (like index name differences on SQLite)
    meaningful_diffs = [d for d in diff if not (isinstance(d, tuple) and d[0] in ("remove_index",))]

    assert not meaningful_diffs, "Model/migration drift detected! Diffs:\n" + "\n".join(
        str(d) for d in meaningful_diffs
    )
