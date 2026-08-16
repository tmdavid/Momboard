"""SQLite online backup with 14-day rotation.

Uses sqlite3's built-in `.backup()` method which performs an online backup
(safe even with WAL mode and concurrent readers/writers). Runs as an in-process
scheduled task to fit the one-process architecture on Fly.io.
"""

import asyncio
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = Path("/data/backups")
RETENTION_DAYS = 14


def perform_backup(
    db_path: str | Path,
    backup_dir: str | Path | None = None,
    *,
    retention_days: int = RETENTION_DAYS,
) -> Path:
    """Perform a SQLite online backup and rotate old backups.

    Args:
        db_path: Path to the source SQLite database file.
        backup_dir: Directory to store backups. Defaults to /data/backups.
        retention_days: Number of days to retain backups.

    Returns:
        Path to the new backup file.

    Raises:
        FileNotFoundError: If the source database doesn't exist.
        sqlite3.Error: If the backup fails.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Source database not found: {db_path}")

    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Generate timestamped filename
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"momboard_{timestamp}.db"

    # Perform online backup using sqlite3's backup API
    logger.info("Starting SQLite backup: %s -> %s", db_path, backup_file)
    start = time.monotonic()

    source = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(backup_file))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    elapsed = time.monotonic() - start
    size_mb = backup_file.stat().st_size / (1024 * 1024)
    logger.info("Backup complete: %.1f MB in %.2fs -> %s", size_mb, elapsed, backup_file)

    # Rotate old backups
    _rotate_backups(backup_dir, retention_days)

    return backup_file


def _rotate_backups(backup_dir: Path, retention_days: int) -> list[Path]:
    """Delete backup files older than retention_days.

    Returns:
        List of deleted files.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted: list[Path] = []

    for f in sorted(backup_dir.glob("momboard_*.db")):
        # Parse timestamp from filename: momboard_20260815_190000.db
        try:
            name_stem = f.stem  # momboard_20260815_190000
            ts_part = name_stem.replace("momboard_", "")
            file_dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S").replace(
                tzinfo=UTC
            )
        except ValueError:
            continue

        if file_dt < cutoff:
            f.unlink()
            deleted.append(f)
            logger.info("Rotated old backup: %s", f.name)

    return deleted


def verify_backup(backup_path: str | Path) -> dict[str, int]:
    """Verify a backup is a valid SQLite database by checking table row counts.

    Returns:
        Dict mapping table name to row count.

    Raises:
        sqlite3.DatabaseError: If the file is not a valid SQLite database.
    """
    backup_path = Path(backup_path)
    conn = sqlite3.connect(str(backup_path))
    try:
        # Integrity check
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            raise sqlite3.DatabaseError(f"Integrity check failed: {result[0]}")

        # Get all tables
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        counts: dict[str, int] = {}
        for (table_name,) in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
            counts[table_name] = count

        return counts
    finally:
        conn.close()


async def backup_scheduler(settings: Settings, *, interval_hours: float = 24.0) -> None:
    """Run periodic backups. Designed to be launched as an asyncio task.

    Runs the first backup shortly after startup (60s delay), then every interval_hours.
    """
    # Extract database file path from URL
    db_path = _db_path_from_url(settings.database_url)
    if db_path is None:
        logger.warning("Backup scheduler: not a file-based SQLite DB, skipping")
        return

    # Short delay on startup to let migrations finish
    await asyncio.sleep(60)

    while True:
        try:
            # Run backup in a thread to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, perform_backup, db_path)
        except Exception:
            logger.exception("Backup failed")

        await asyncio.sleep(interval_hours * 3600)


def _db_path_from_url(url: str) -> Path | None:
    """Extract the filesystem path from a sqlite URL.

    Examples:
        sqlite+aiosqlite:///data/momboard.db -> /data/momboard.db
        sqlite:///data/momboard.db -> /data/momboard.db
        sqlite+aiosqlite:///./data/local.db -> ./data/local.db
    """
    if "sqlite" not in url:
        return None

    # Strip driver prefix: sqlite+aiosqlite:///path or sqlite:///path
    parts = url.split("///", 1)
    if len(parts) != 2:
        return None

    path_str = parts[1]
    if not path_str:
        return None

    return Path(path_str)
