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
    r = await client.get("/healthz")
    assert r.json()["version"] == "0.1.0"
