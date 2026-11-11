#!/usr/bin/env python3
"""Apply and verify the database migrations on a SQLite MomBoard DB (any version up to head).

What it does, in order:
  1. Pre-flight: resolves the DB, checks it is SQLite, refuses if the app looks
     like it is still running, checks the DB's integrity and free disk space.
  2. Backup: online-backs-up the DB (sqlite3 .backup, safe with WAL) and verifies
     the backup opens and passes integrity_check. Aborts if the backup fails.
  3. Migrate: `alembic upgrade head`, then `alembic check`.
  4. Verify: schema asserts for the v0.4 and v0.5 changes, `PRAGMA integrity_check`,
     `PRAGMA foreign_key_check`, and that no rows were lost.

Safe to re-run (Alembic skips applied revisions). Nothing here deletes data; the
migrations are additive (008 backfills snapshots by reading, then UPDATE-ing).

The revision it expects is read from the alembic/versions files, so it keeps working
as new migrations are added; the schema checks below list what each release needs.

Usage (from the repo root, on the box that runs MomBoard from source):

    python scripts/migrate_db.py --dry-run     # pre-flight + show pending only
    python scripts/migrate_db.py               # backup, migrate, verify (asks first)
    python scripts/migrate_db.py --yes         # same, no prompt
    python scripts/migrate_db.py --verify-only # just check the schema (no changes)

Container deploys apply migrations automatically on start (entrypoint.sh). To only
VERIFY a container's DB without copying files into it:

    docker exec -i <container> python - --verify-only < scripts/migrate_db.py

Never prints secrets: only the resolved database *path* is shown.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Used only if the alembic/versions files cannot be found (for example when this file is piped into a
# container whose working directory is not the repo). Normally the head is read from those files.
FALLBACK_HEAD_REVISION = "011_v05_tagging"

# table -> columns that must exist after the v0.4 migrations
REQUIRED_COLUMNS: dict[str, set[str]] = {
    # 007 taxonomy
    "tags": {"origin", "category"},
    # 008 decision snapshots
    "decision_evidence": {
        "quote_snapshot", "company_name", "conversation_id",
        "conversation_date", "cited_at", "invalid_reason",
    },
    # 008 + 009 decisions
    "decisions": {"integrity_checked_at", "owner_id", "area"},
    # 010 hypotheses
    "hypothesis_links": {"reviewed_by", "reviewed_at"},
    "hypothesis_band_events": {
        "id", "hypothesis_id", "from_band", "to_band", "cause_link_id", "created_at",
    },
    "hypothesis_questions": {"id", "hypothesis_id", "text", "asked_at", "created_at"},
    # 011 tagging quality + settings (v0.5)
    "app_settings": {"id", "key", "value"},
    "conversations": {"taxonomy_version", "tagged_at"},
}

# columns that 011 adds to a table which an earlier entry above already lists
EXTRA_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "tags": {"min_confidence", "negative_hint", "example", "added_in_version"},
}

# tables whose row counts must not shrink across the migration
COUNTED_TABLES = (
    "tags", "conversations", "highlights", "decisions", "decision_evidence",
    "hypotheses", "hypothesis_links",
)

OK, FAIL, WARN = "  [ ok ]", "  [FAIL]", "  [warn]"


# --------------------------------------------------------------------------- helpers


def repo_root() -> Path:
    try:
        return Path(__file__).resolve().parent.parent
    except NameError:  # piped via `python -` into a container
        return Path.cwd()


def read_env_value(root: Path, key: str) -> str | None:
    """DATABASE_URL from the environment, else from .env (never echoed)."""
    if os.environ.get(key):
        return os.environ[key]
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def sqlite_path_from_url(url: str) -> Path:
    """sqlite+aiosqlite:///rel.db -> rel.db ; sqlite+aiosqlite:////abs.db -> /abs.db."""
    if not url.startswith("sqlite"):
        raise SystemExit(
            "DATABASE_URL is not SQLite. This script only supports the SQLite deployment "
            "(see documentation/deployment/deploy.md for PostgreSQL)."
        )
    marker = ":///"
    return Path(url.split(marker, 1)[1])


def connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(path))


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def count_rows(conn: sqlite3.Connection) -> dict[str, int | None]:
    return {
        t: (conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if table_exists(conn, t) else None)
        for t in COUNTED_TABLES
    }


def expected_head(root: Path) -> str:
    """The newest revision, read from alembic/versions (the one no other revision descends from)."""
    import re

    versions = root / "alembic" / "versions"
    revisions: set[str] = set()
    parents: set[str] = set()
    if versions.is_dir():
        for path in versions.glob("*.py"):
            text = path.read_text()
            rev = re.search(r'^revision(?:: str)?\s*=\s*"([^"]+)"', text, re.M)
            down = re.search(r'^down_revision(?:: [^=]+)?\s*=\s*"([^"]+)"', text, re.M)
            if rev:
                revisions.add(rev.group(1))
            if down:
                parents.add(down.group(1))
    heads = revisions - parents
    if len(heads) == 1:
        return heads.pop()
    print(f"{WARN} could not determine the alembic head from {versions}; using {FALLBACK_HEAD_REVISION}")
    return FALLBACK_HEAD_REVISION


def current_revision(conn: sqlite3.Connection) -> str | None:
    if not table_exists(conn, "alembic_version"):
        return None
    row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def app_looks_running() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-fa", "uvicorn.*app.main"], capture_output=True, text=True, check=False
        ).stdout
    except FileNotFoundError:
        return False
    return bool(out.strip())


# --------------------------------------------------------------------------- verification


def fk_violation_count(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        return len(conn.execute("PRAGMA foreign_key_check").fetchall())
    finally:
        conn.close()


def verify_schema(db_path: Path, fk_baseline: int = 0, head: str = FALLBACK_HEAD_REVISION) -> list[str]:
    """Return a list of problems (empty = healthy). Prints a line per check.

    ``fk_baseline`` is the number of foreign-key violations that already existed before
    migrating; only violations beyond that count as a problem.
    """
    problems: list[str] = []
    conn = connect(db_path)
    try:
        rev = current_revision(conn)
        if rev == head:
            print(f"{OK} alembic revision is {rev}")
        else:
            problems.append(f"alembic revision is {rev!r}, expected {head!r}")
            print(f"{FAIL} alembic revision is {rev!r}, expected {head!r}")

        required = {t: set(cols) for t, cols in REQUIRED_COLUMNS.items()}
        for table, cols in EXTRA_REQUIRED_COLUMNS.items():
            required.setdefault(table, set()).update(cols)
        for table, needed in required.items():
            if not table_exists(conn, table):
                problems.append(f"table {table} is missing")
                print(f"{FAIL} table {table} is missing")
                continue
            missing = needed - columns(conn, table)
            if missing:
                problems.append(f"{table} is missing columns {sorted(missing)}")
                print(f"{FAIL} {table} is missing columns {sorted(missing)}")
            else:
                print(f"{OK} {table} has {len(needed)} required column(s)")

        # 009: decisions.status CHECK allows 'draft'
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='decisions'"
        ).fetchone()
        if row and "'draft'" in row[0]:
            print(f"{OK} decisions.status allows 'draft'")
        else:
            problems.append("decisions.status CHECK does not allow 'draft'")
            print(f"{FAIL} decisions.status CHECK does not allow 'draft'")

        # 008 backfill: every receipt that still points at a highlight has a snapshot
        if "quote_snapshot" in columns(conn, "decision_evidence"):
            unsnapped = conn.execute(
                "SELECT COUNT(*) FROM decision_evidence "
                "WHERE highlight_id IS NOT NULL AND quote_snapshot IS NULL"
            ).fetchone()[0]
            if unsnapped:
                problems.append(f"{unsnapped} decision_evidence row(s) have no snapshot")
                print(f"{FAIL} {unsnapped} decision_evidence row(s) have no quote snapshot")
            else:
                print(f"{OK} every cited receipt has a quote snapshot")

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity == "ok":
            print(f"{OK} PRAGMA integrity_check: ok")
        else:
            problems.append(f"integrity_check: {integrity}")
            print(f"{FAIL} PRAGMA integrity_check: {integrity}")

        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if len(fk) > fk_baseline:
            problems.append(f"{len(fk) - fk_baseline} NEW foreign key violation(s)")
            print(f"{FAIL} {len(fk)} foreign key violation(s) vs {fk_baseline} before migrating, e.g. {fk[:3]}")
        elif fk:
            print(f"{WARN} {len(fk)} foreign key violation(s), all pre-existing (same as before migrating) — not caused by this migration")
        else:
            print(f"{OK} PRAGMA foreign_key_check: clean")
    finally:
        conn.close()
    return problems


# --------------------------------------------------------------------------- steps


def preflight(db_path: Path, force: bool) -> None:
    print("\n== 1. Pre-flight ==")
    if not db_path.exists():
        raise SystemExit(f"{FAIL} database file not found: {db_path}")
    print(f"{OK} database: {db_path} ({db_path.stat().st_size / 1_048_576:.1f} MiB)")

    if app_looks_running():
        msg = "MomBoard (uvicorn) appears to be running. Stop it before migrating a SQLite DB."
        if not force:
            raise SystemExit(f"{FAIL} {msg}  (override with --force)")
        print(f"{WARN} {msg} Continuing because of --force.")
    else:
        print(f"{OK} no running uvicorn process detected")

    conn = connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SystemExit(f"{FAIL} database fails integrity_check before migrating: {integrity}")
        print(f"{OK} integrity_check on the existing database: ok")
        fk_existing = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        if fk_existing:
            print(f"{WARN} {fk_existing} pre-existing foreign key violation(s) (will not be blamed on the migration)")
        print(f"     current revision: {current_revision(conn)}")
    finally:
        conn.close()

    free = shutil.disk_usage(db_path.parent).free
    need = db_path.stat().st_size * 3
    if free < need:
        raise SystemExit(
            f"{FAIL} not enough free disk ({free / 1_048_576:.0f} MiB free, "
            f"need ~{need / 1_048_576:.0f} MiB for backup + migration)"
        )
    print(f"{OK} free disk: {free / 1_048_576:.0f} MiB")


def backup(db_path: Path, backup_dir: Path) -> Path:
    print("\n== 2. Backup ==")
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"pre-migrate-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    src = connect(db_path)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = connect(dest)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        raise SystemExit(f"{FAIL} backup failed verification ({result}); nothing was migrated")
    print(f"{OK} backup written and verified: {dest}")
    print("     (this file shares the volume with the DB — copy it off-box too)")
    return dest


def run_alembic(root: Path, python: str, db_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run(
        [python, "-m", "alembic", *args], cwd=root, env=env, capture_output=True, text=True
    )


def migrate(root: Path, python: str, db_url: str) -> None:
    print("\n== 3. Migrate ==")
    up = run_alembic(root, python, db_url, "upgrade", "head")
    for line in (up.stdout + up.stderr).splitlines():
        if "Running upgrade" in line or "Error" in line or "error" in line:
            print(f"     {line.strip()}")
    if up.returncode != 0:
        print(up.stderr[-2000:])
        raise SystemExit(
            f"{FAIL} alembic upgrade failed. The database may be partly migrated — "
            "restore from the backup above (see MIGRATIONS-RUNBOOK.local.md)."
        )
    print(f"{OK} alembic upgrade head completed")

    chk = run_alembic(root, python, db_url, "check")
    if chk.returncode == 0:
        print(f"{OK} alembic check: models and database agree")
    else:
        print(f"{WARN} alembic check reported differences:\n{(chk.stdout + chk.stderr)[-800:]}")


# --------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="SQLite file (default: from DATABASE_URL / .env)")
    parser.add_argument("--backup-dir", help="Where to write the backup (default: <db dir>/backups)")
    parser.add_argument("--python", default=sys.executable, help="Python used to run alembic")
    parser.add_argument("--dry-run", action="store_true", help="Pre-flight and show pending only")
    parser.add_argument("--verify-only", action="store_true", help="Check the schema; change nothing")
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    parser.add_argument("--force", action="store_true", help="Continue even if uvicorn seems to be running")
    args = parser.parse_args()

    root = repo_root()
    if args.db:
        db_path = Path(args.db)
        db_url = f"sqlite+aiosqlite:///{db_path.resolve()}"
    else:
        url = read_env_value(root, "DATABASE_URL")
        if not url:
            raise SystemExit("DATABASE_URL not set (environment or .env). Pass --db PATH.")
        db_path = sqlite_path_from_url(url)
        if not db_path.is_absolute():
            db_path = (root / db_path).resolve()
        db_url = f"sqlite+aiosqlite:///{db_path}"

    if args.verify_only:
        print("== Verify (read-only) ==")
        # No pre-migration baseline in read-only mode: report FK issues as warnings.
        problems = verify_schema(db_path, fk_violation_count(db_path), expected_head(root))
        print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    preflight(db_path, args.force)

    if args.dry_run:
        conn = connect(db_path)
        cur = current_revision(conn)
        conn.close()
        pending = run_alembic(root, args.python, db_url, "history", "-r", "current:head")
        # `current:head` is inclusive of the current revision: drop the already-applied step.
        lines = [
            ln for ln in pending.stdout.splitlines()
            if ln.strip() and not (cur and f"-> {cur}" in ln)
        ]
        print("\n== Pending revisions, newest first (dry run — nothing changed) ==")
        print("\n".join(lines) if lines else "(none — already at head)")
        return 0

    if not args.yes:
        answer = input("\nBack up and migrate this database now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted. Nothing changed.")
            return 1

    before_conn = connect(db_path)
    rows_before = count_rows(before_conn)
    before_conn.close()
    fk_baseline = fk_violation_count(db_path)

    backup_dir = Path(args.backup_dir) if args.backup_dir else db_path.parent / "backups"
    backup_file = backup(db_path, backup_dir)
    migrate(root, args.python, db_url)

    print("\n== 4. Verify ==")
    problems = verify_schema(db_path, fk_baseline, expected_head(root))

    after_conn = connect(db_path)
    rows_after = count_rows(after_conn)
    after_conn.close()
    for table, before in rows_before.items():
        after = rows_after[table]
        if before is None:
            print(f"     {table}: (new) {after}")
        elif after is not None and after < before:
            problems.append(f"{table} lost rows ({before} -> {after})")
            print(f"{FAIL} {table}: {before} -> {after} rows (LOST ROWS)")
        else:
            print(f"{OK} {table}: {before} -> {after} rows")

    print("\n== Result ==")
    if problems:
        print(f"{FAIL} {len(problems)} problem(s):")
        for p in problems:
            print(f"       - {p}")
        print(f"\nRestore with the backup: {backup_file}")
        print("(stop the app, copy it over the DB file, restart — see the runbook)")
        return 1
    print(f"{OK} migrations applied and verified. Backup kept at: {backup_file}")
    print("Next: start the app, then run the smoke checks from the runbook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
