#!/usr/bin/env python3
"""Export FastAPI OpenAPI schema to JSON without requiring a running server.

Usage:
    python scripts/export_openapi.py [output_path]

Default output: web/src/generated/openapi-schema.json
"""

import json
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Set minimal env vars required by Settings to avoid validation errors
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///dummy.db")
os.environ.setdefault("SESSION_SECRET", "export-only-not-real")
os.environ.setdefault("ENV", "test")


def export_schema(output_path: Path | None = None) -> None:
    """Generate and write the OpenAPI JSON schema."""
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        database_url="sqlite+aiosqlite:///dummy.db",
        session_secret="export-only-not-real",  # noqa: S106
        env="test",
    )
    app = create_app(settings=settings)
    schema = app.openapi()

    if output_path is None:
        output_path = project_root / "web" / "src" / "generated" / "openapi-schema.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"OpenAPI schema exported to {output_path}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    export_schema(out)
