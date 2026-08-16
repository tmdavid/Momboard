"""T04: Authentication tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_wrong_password_401(client: AsyncClient, user_david):
    r = await client.post("/auth/login", json={"email": "d@rp.com", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user_401(client: AsyncClient):
    r = await client.post("/auth/login", json={"email": "nobody@rp.com", "password": "pw"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_sets_httponly_session_cookie_and_me_works(client: AsyncClient, user_david):
    r = await client.post("/auth/login", json={"email": "d@rp.com", "password": "pw"})
    assert r.status_code == 200
    assert "session" in r.cookies

    # Use cookie to call /api/me
    me_r = await client.get("/api/me")
    assert me_r.status_code == 200
    assert me_r.json()["email"] == "d@rp.com"


@pytest.mark.asyncio
async def test_protected_route_401_without_cookie(client: AsyncClient):
    r = await client.get("/api/conversations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_only_route_403_for_member(member_client: AsyncClient):
    r = await member_client.post(
        "/api/tags",
        json={
            "key": "test",
            "emoji": "🧪",
            "name": "Test",
            "sort_order": 99,
            "is_active": True,
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_access_admin_routes(auth_client: AsyncClient):
    r = await auth_client.get("/api/tags")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
