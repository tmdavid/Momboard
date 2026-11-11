"""API tokens over HTTP: management endpoints, and bearer auth on the REST API."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models import ApiToken


def bearer(app, token: str) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": f"Bearer {token}"})


async def create(client, **body):
    body.setdefault("name", "Claude")
    r = await client.post("/api/tokens", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def read_token(auth_client):
    return (await create(auth_client, scope="read"))["token"]


@pytest_asyncio.fixture
async def write_token(auth_client):
    return (await create(auth_client, scope="write", name="writer"))["token"]


class TestManagement:
    @pytest.mark.asyncio
    async def test_create_returns_the_secret_once_and_never_again(self, auth_client):
        r = await auth_client.post("/api/tokens", json={"name": "Claude Team connector", "scope": "read", "expires_in_days": 90})
        assert r.status_code == 201
        body = r.json()
        assert body["token"].startswith("mb_") and len(body["token"]) == 46
        assert body["prefix"] == body["token"][:8] and body["scope"] == "read" and body["status"] == "active"
        assert r.headers["cache-control"] == "no-store"
        listed = (await auth_client.get("/api/tokens")).json()
        assert listed["items"][0]["prefix"] == body["prefix"]
        text = (await auth_client.get("/api/tokens")).text
        assert body["token"] not in text and "token_hash" not in text and '"token"' not in text

    @pytest.mark.asyncio
    async def test_defaults_are_read_only_and_ninety_days(self, auth_client):
        body = await create(auth_client)
        assert body["scope"] == "read"
        days = (datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00")) - datetime.now(UTC)).days
        assert 88 <= days <= 90

    @pytest.mark.asyncio
    async def test_never_expires(self, auth_client):
        assert (await create(auth_client, expires_in_days=None))["expires_at"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [{"name": ""}, {"name": "x" * 101}, {"scope": "admin"}, {"expires_in_days": 7}, {}])
    async def test_invalid_requests_are_422(self, auth_client, body):
        r = await auth_client.post("/api/tokens", json=body)
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_the_eleventh_active_token_is_refused_with_a_useful_message(self, auth_client):
        for i in range(10):
            await create(auth_client, name=f"t{i}")
        r = await auth_client.post("/api/tokens", json={"name": "one too many"})
        assert r.status_code == 409 and "Revoke" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_revoke_keeps_the_row_and_marks_it(self, auth_client, session_factory):
        t = await create(auth_client)
        r = await auth_client.post(f"/api/tokens/{t['id']}/revoke")
        assert r.status_code == 200 and r.json()["status"] == "revoked" and r.json()["revoked_at"]
        async with session_factory() as db:
            assert len((await db.execute(select(ApiToken))).scalars().all()) == 1
        # idempotent
        assert (await auth_client.post(f"/api/tokens/{t['id']}/revoke")).status_code == 200

    @pytest.mark.asyncio
    async def test_a_revoked_token_frees_a_slot(self, auth_client):
        made = [await create(auth_client, name=f"t{i}") for i in range(10)]
        await auth_client.post(f"/api/tokens/{made[0]['id']}/revoke")
        assert (await auth_client.post("/api/tokens", json={"name": "again"})).status_code == 201

    @pytest.mark.asyncio
    async def test_members_manage_only_their_own_admins_see_and_revoke_all(self, auth_client, member_client):
        mine = await create(member_client, name="members")
        admins = await create(auth_client, name="admins")
        assert [t["name"] for t in (await member_client.get("/api/tokens")).json()["items"]] == ["members"]
        listed = (await auth_client.get("/api/tokens")).json()["items"]
        assert sorted(t["name"] for t in listed) == ["admins", "members"]
        assert {t["owner_name"] for t in listed} == {"David", "Member"}
        # a member cannot even tell that someone else's token exists
        assert (await member_client.post(f"/api/tokens/{admins['id']}/revoke")).status_code == 404
        assert (await member_client.post("/api/tokens/99999/revoke")).status_code == 404
        # an admin can revoke anyone's
        assert (await auth_client.post(f"/api/tokens/{mine['id']}/revoke")).json()["status"] == "revoked"

    @pytest.mark.asyncio
    async def test_requires_a_signed_in_user(self, client):
        assert (await client.get("/api/tokens")).status_code == 401
        assert (await client.post("/api/tokens", json={"name": "x"})).status_code == 401
        assert (await client.post("/api/tokens/1/revoke")).status_code == 401


class TestBearerOnRest:
    @pytest.mark.asyncio
    async def test_a_token_authenticates_as_its_owner(self, app, read_token):
        async with bearer(app, read_token) as c:
            r = await c.get("/api/me")
            assert r.status_code == 200 and r.json()["email"] == "d@rp.com"
            assert (await c.get("/api/tags")).status_code == 200

    @pytest.mark.asyncio
    async def test_a_read_token_cannot_change_anything(self, app, read_token):
        async with bearer(app, read_token) as c:
            r = await c.put("/api/settings/company", json={"name": "X", "aliases": [], "email_domains": []})
            assert r.status_code == 403 and "read-only" in r.json()["detail"].lower()
            assert (await c.post("/api/tags", json={"key": "k", "name": "K", "emoji": "x", "description": "d"})).status_code == 403
            assert (await c.delete("/api/conversations/1")).status_code == 403

    @pytest.mark.asyncio
    async def test_a_write_token_can_write_with_its_owners_permissions(self, app, write_token):
        async with bearer(app, write_token) as c:
            r = await c.put("/api/settings/company", json={"name": "Acme", "aliases": [], "email_domains": []})
            assert r.status_code == 200, r.text            # the owner is an admin

    @pytest.mark.asyncio
    async def test_a_token_never_exceeds_its_owners_role(self, app, member_client):
        tok = (await create(member_client, scope="write"))["token"]
        async with bearer(app, tok) as c:
            r = await c.put("/api/settings/company", json={"name": "Acme", "aliases": [], "email_domains": []})
            assert r.status_code == 403 and "admin" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_tokens_cannot_manage_tokens(self, app, write_token):
        async with bearer(app, write_token) as c:
            assert (await c.get("/api/tokens")).status_code == 403
            assert (await c.post("/api/tokens", json={"name": "minted by a token"})).status_code == 403
            assert (await c.post("/api/tokens/1/revoke")).status_code == 403

    @pytest.mark.asyncio
    async def test_every_failure_looks_the_same(self, app, auth_client, session_factory):
        good = await create(auth_client)
        revoked = await create(auth_client, name="r")
        await auth_client.post(f"/api/tokens/{revoked['id']}/revoke")
        expired = await create(auth_client, name="e")
        async with session_factory() as db:
            row = await db.get(ApiToken, expired["id"])
            row.expires_at = datetime.now(UTC) - timedelta(days=1)
            await db.commit()
        seen = set()
        for tok in ["mb_" + "x" * 43, revoked["token"], expired["token"], "mb_short", "mb_"]:
            async with bearer(app, tok) as c:
                r = await c.get("/api/tags")
                assert r.status_code == 401
                seen.add(r.text)
        assert len(seen) == 1, f"responses differ: {seen}"          # nothing reveals why
        assert good["token"] not in next(iter(seen))

    @pytest.mark.asyncio
    async def test_a_revoked_token_stops_working_on_the_next_request(self, app, auth_client):
        t = await create(auth_client)
        async with bearer(app, t["token"]) as c:
            assert (await c.get("/api/tags")).status_code == 200
            await auth_client.post(f"/api/tokens/{t['id']}/revoke")
            assert (await c.get("/api/tags")).status_code == 401

    @pytest.mark.asyncio
    async def test_a_bad_bearer_does_not_fall_back_to_a_cookie(self, app, user_david):
        from app.auth import create_session_token

        cookie = create_session_token(user_david.id, app.state.settings.session_secret)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies={"session": cookie},
                               headers={"Authorization": "Bearer mb_" + "y" * 43}) as c:
            assert (await c.get("/api/tags")).status_code == 401

    @pytest.mark.asyncio
    async def test_other_authorization_schemes_are_ignored(self, app, auth_client):
        r = await auth_client.get("/api/tags", headers={"Authorization": "Basic dXNlcjpwdw=="})
        assert r.status_code == 200                                  # the cookie still works

    @pytest.mark.asyncio
    async def test_use_is_recorded_as_last_used(self, app, auth_client, read_token):
        before = (await auth_client.get("/api/tokens")).json()["items"][0]["last_used_at"]
        assert before is None
        async with bearer(app, read_token) as c:
            await c.get("/api/tags")
        assert (await auth_client.get("/api/tokens")).json()["items"][0]["last_used_at"] is not None

    @pytest.mark.asyncio
    async def test_the_secret_never_reaches_the_logs(self, app, auth_client, caplog):
        caplog.set_level(logging.DEBUG)
        t = await create(auth_client)
        async with bearer(app, t["token"]) as c:
            await c.get("/api/tags")
            await c.get("/api/tags", headers={"Authorization": "Bearer mb_" + "z" * 43})
        assert t["token"] not in caplog.text and ("z" * 43) not in caplog.text


class TestTokenManagementCannotBeReachedByATokenInDisguise:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/tokens/"), ("POST", "/api/tokens/"), ("GET", "/api/%74okens"), ("GET", "/api//tokens"),
        ("GET", "/api/tokens/../tokens"), ("GET", "/api/./tokens"), ("POST", "/api/tokens/1/revoke/"),
        ("GET", "/API/tokens"), ("GET", "/api/Tokens"),
    ])
    async def test_variants_never_succeed(self, app, write_token, session_factory, method, path):
        async with bearer(app, write_token) as c:
            r = await c.request(method, path, json={"name": "x"} if method == "POST" else None)
            # Unknown paths may fall through to the single-page app (HTML). What must never happen is
            # the token API answering a token: no JSON success, and no token minted or revoked.
            is_api_success = r.status_code < 300 and "json" in r.headers.get("content-type", "")
            assert not is_api_success, f"{method} {path} -> {r.status_code} {r.text[:100]}"
        async with session_factory() as db:
            rows = (await db.execute(select(ApiToken))).scalars().all()
        assert len(rows) == 1 and rows[0].revoked_at is None     # only the fixture token; nothing minted or revoked
