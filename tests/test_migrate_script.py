"""scripts/migrate_db.py must track the real Alembic head and the real schema."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("migrate_db", ROOT / "scripts" / "migrate_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alembic(db: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}"}
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1500:]


def test_expected_head_is_the_real_alembic_head():
    real_head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    assert load_script().expected_head(ROOT) == real_head


def test_a_fully_migrated_database_verifies_clean(tmp_path, capsys):
    db = tmp_path / "m.db"
    alembic(db, "upgrade", "head")
    problems = load_script().verify_schema(db, 0, load_script().expected_head(ROOT))
    assert problems == [], capsys.readouterr().out


def test_a_database_one_revision_behind_is_flagged(tmp_path):
    db = tmp_path / "m.db"
    alembic(db, "upgrade", "head")
    alembic(db, "downgrade", "010_hypothesis_history_questions")     # two behind head: 011 and 012 are gone
    script = load_script()
    problems = script.verify_schema(db, 0, script.expected_head(ROOT))
    assert any("alembic revision" in p for p in problems)
    # the 011 columns and the 012 tables are gone too, and the checker says which
    assert any("min_confidence" in p or "taxonomy_version" in p or "app_settings" in p for p in problems)
    assert any("api_tokens" in p or "mcp_calls" in p for p in problems)


def test_a_database_one_revision_behind_names_the_new_tables(tmp_path):
    db = tmp_path / "m.db"
    alembic(db, "upgrade", "head")
    alembic(db, "downgrade", "-1")                                   # only 012 is gone
    script = load_script()
    problems = script.verify_schema(db, 0, script.expected_head(ROOT))
    assert any("alembic revision" in p for p in problems)
    assert any("api_tokens" in p for p in problems) and not any("min_confidence" in p for p in problems)


def test_the_script_is_self_contained_so_it_can_be_piped_into_a_container():
    """`docker exec -i app python - < scripts/migrate_db.py` has no package to import from."""
    source = (ROOT / "scripts" / "migrate_db.py").read_text()
    assert "from app" not in source and "import app" not in source


@pytest.mark.parametrize("flag", ["--verify-only"])
def test_verify_only_cli_exits_zero_on_a_healthy_db(tmp_path, flag):
    db = tmp_path / "m.db"
    alembic(db, "upgrade", "head")
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "migrate_db.py"), "--db", str(db), flag],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-1500:]
    assert "all checks passed" in done.stdout
