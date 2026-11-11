"""T01: Health check endpoint tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz_returns_200_and_version(client: AsyncClient):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "version" in r.json()


@pytest.mark.asyncio
async def test_healthz_version_matches_settings(client: AsyncClient):
    from app.config import get_settings

    r = await client.get("/healthz")
    assert r.json()["version"] == get_settings().version


def test_every_declared_version_agrees():
    """One release number: the app setting, pyproject, and the web package must not drift
    (they sat at 0.2.0 through v0.3 and v0.4 before this test existed)."""
    import json
    import tomllib
    from pathlib import Path

    from app.config import get_settings

    root = Path(__file__).resolve().parent.parent
    app_version = get_settings().version
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    web = json.loads((root / "web" / "package.json").read_text())["version"]
    lock = json.loads((root / "web" / "package-lock.json").read_text())
    assert pyproject == app_version == web == lock["version"] == lock["packages"][""]["version"]

