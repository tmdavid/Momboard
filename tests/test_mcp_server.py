"""The /mcp gateway: auth, rate limit, audit, scopes, errors and per-request identity.

Runs against whichever `mcp` SDK is installed; CI also runs it against the pinned version.
"""

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.mcp import audit
from app.mcp.server import current_caller
from app.models import ApiToken, McpCall
from app.services import api_tokens as svc

ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def make_settings(**over) -> Settings:
    base = dict(database_url="sqlite+aiosqlite://", session_secret="test-secret", openai_api_key="", env="test",
                worker_poll_interval=0.1, mcp_enabled=True)
    base.update(over)
    return Settings(**base)


async def build_app(engine, session_factory, **over):
    app = create_app(make_settings(**over))
    app.state.engine = engine
    app.state.session_factory = session_factory

    @app.state.mcp.tool(name="whoami")
    async def whoami():
        """Who is calling."""
        c = current_caller()
        await asyncio.sleep(0.02)
        return {"email": c.user.email, "prefix": c.token.prefix, "base_url": c.base_url}

    @app.state.mcp.tool(name="echo")
    async def echo(query: str = "", limit: int = 20):
        """Echo the arguments back."""
        return {"items": [{"n": i} for i in range(3)], "query": query, "limit": limit}

    @app.state.mcp.tool(name="missing")
    async def missing():
        """Raises the same HTTP error a REST handler would."""
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    @app.state.mcp.tool(name="explode")
    async def explode():
        """Raises something unexpected."""
        raise RuntimeError("psycopg2.OperationalError: could not connect to /var/run/secret-db-host")

    @app.state.mcp.tool(name="slow")
    async def slow():
        """Takes too long."""
        await asyncio.sleep(5)
        return {"done": True}

    @app.state.mcp.tool(name="save_thing", scope="write", read_only=False)
    async def save_thing(title: str = "x"):
        """A write tool."""
        return {"saved": title}

    return app


@contextlib.asynccontextmanager
async def serve(app):
    """Run the app's MCP lifespan inside one dedicated task, as the real FastAPI lifespan does.

    The SDK's session manager uses an anyio task group, which must be entered and exited from the
    same asyncio task; pytest-asyncio would otherwise enter in setup and exit in teardown tasks.
    """
    started, stop = asyncio.Event(), asyncio.Event()

    async def run():
        async with app.state.mcp.lifespan():
            started.set()
            await stop.wait()

    task = asyncio.create_task(run())
    await asyncio.wait_for(started.wait(), 10)
    try:
        yield app
    finally:
        stop.set()
        await asyncio.wait_for(task, 10)


@pytest_asyncio.fixture
async def mcp_app(engine, session_factory):
    app = await build_app(engine, session_factory)
    async with serve(app):
        yield app


async def new_token(session_factory, user, scope="read", name="Claude"):
    async with session_factory() as db:
        row, plain = await svc.create_token(db, user, name=name, scope=scope, expires_in_days=90)
        await db.commit()
        return row.id, plain


def client(app, token=None, host="momboard.test") -> AsyncClient:
    headers = {**ACCEPT, **({"Authorization": f"Bearer {token}"} if token else {})}
    return AsyncClient(transport=ASGITransport(app=app), base_url=f"http://{host}", headers=headers)


def rpc(method, params=None, id=1):
    body = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def call(c, name, arguments=None, id=1):
    r = await c.post("/mcp", json=rpc("tools/call", {"name": name, "arguments": arguments or {}}, id))
    assert r.status_code == 200, r.text
    return r.json()["result"]


def text(result) -> str:
    return result["content"][0]["text"]


@pytest_asyncio.fixture
async def tok(session_factory, user_david):
    return await new_token(session_factory, user_david)


class TestMounting:
    @pytest.mark.asyncio
    async def test_off_by_default(self, engine, session_factory):
        app = create_app(make_settings(mcp_enabled=False))
        assert not hasattr(app.state, "mcp") or app.state.mcp is None
        assert "/mcp" not in {getattr(r, "path", "") for r in app.routes}

    @pytest.mark.asyncio
    async def test_exactly_one_mcp_route_and_it_sits_before_the_spa_catch_all(self, mcp_app):
        paths = [getattr(r, "path", "") for r in mcp_app.routes]
        assert paths.count("/mcp") == 1
        if "/{full_path:path}" in paths:
            assert paths.index("/mcp") < paths.index("/{full_path:path}")

    @pytest.mark.asyncio
    async def test_no_redirect_on_the_exact_path(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            r = await c.post("/mcp", json=rpc("tools/list"), follow_redirects=False)
            assert r.status_code == 200


class TestAuth:
    @pytest.mark.asyncio
    async def test_no_token_is_401_with_a_bearer_challenge(self, mcp_app):
        async with client(mcp_app) as c:
            r = await c.post("/mcp", json=rpc("tools/list"))
            assert r.status_code == 401 and r.headers["www-authenticate"].lower().startswith("bearer")

    @pytest.mark.asyncio
    async def test_every_kind_of_bad_token_gets_the_same_answer(self, mcp_app, tok, session_factory, user_david):
        tid, plain = tok
        rid, revoked = await new_token(session_factory, user_david, name="r")
        eid, expired = await new_token(session_factory, user_david, name="e")
        async with session_factory() as db:
            await svc.revoke_token(db, await db.get(ApiToken, rid))
            (await db.get(ApiToken, eid)).expires_at = datetime.now(UTC) - timedelta(days=1)
            await db.commit()
        bodies = set()
        for t in [None, "mb_" + "q" * 43, revoked, expired, "mb_x", "garbage"]:
            async with client(mcp_app, t) as c:
                r = await c.post("/mcp", json=rpc("tools/list"))
                assert r.status_code == 401
                bodies.add(r.text)
        assert len(bodies) == 1

    @pytest.mark.asyncio
    async def test_a_session_cookie_is_not_enough(self, mcp_app, user_david):
        from app.auth import create_session_token

        cookie = create_session_token(user_david.id, mcp_app.state.settings.session_secret)
        async with client(mcp_app) as c:
            r = await c.post("/mcp", json=rpc("tools/list"), cookies={"session": cookie})
            assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_revoking_applies_to_the_very_next_request(self, mcp_app, tok, session_factory):
        tid, plain = tok
        async with client(mcp_app, plain) as c:
            assert (await c.post("/mcp", json=rpc("tools/list"))).status_code == 200
            async with session_factory() as db:
                await svc.revoke_token(db, await db.get(ApiToken, tid))
                await db.commit()
            assert (await c.post("/mcp", json=rpc("tools/list"))).status_code == 401

    @pytest.mark.asyncio
    async def test_use_updates_last_used(self, mcp_app, tok, session_factory):
        tid, plain = tok
        async with client(mcp_app, plain) as c:
            await call(c, "echo")
        async with session_factory() as db:
            assert (await db.get(ApiToken, tid)).last_used_at is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "DELETE"])
    async def test_get_and_delete_are_refused_immediately_not_held_open(self, mcp_app, tok, method):
        async with client(mcp_app, tok[1]) as c:
            r = await asyncio.wait_for(c.request(method, "/mcp"), 5)
            assert r.status_code == 405 and "POST" in r.headers.get("allow", "")


class TestProtocol:
    @pytest.mark.asyncio
    async def test_lists_tools_with_read_only_annotations(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            tools = {t["name"]: t for t in (await c.post("/mcp", json=rpc("tools/list"))).json()["result"]["tools"]}
        assert {"whoami", "echo", "save_thing"} <= set(tools)
        assert tools["echo"]["annotations"]["readOnlyHint"] is True
        assert tools["save_thing"]["annotations"]["readOnlyHint"] is False
        assert tools["save_thing"]["annotations"]["destructiveHint"] is False

    @pytest.mark.asyncio
    async def test_initialize_carries_the_server_instructions(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            r = await c.post("/mcp", json=rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                                             "clientInfo": {"name": "t", "version": "1"}}))
        result = r.json()["result"]
        assert result["serverInfo"]["name"] == "MomBoard"
        ins = result["instructions"].lower()
        assert "mom test" in ins and "url" in ins and "compliment" in ins and "quoted" in ins

    @pytest.mark.asyncio
    async def test_a_tool_result_is_compact_json(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            out = text(await call(c, "echo", {"query": "pricing", "limit": 5}))
        assert "\n" not in out and ": " not in out and json.loads(out)["query"] == "pricing"

    @pytest.mark.asyncio
    async def test_unknown_tool_is_a_clear_error_not_a_stack_trace(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            r = await c.post("/mcp", json=rpc("tools/call", {"name": "nope", "arguments": {}}))
        body = r.text
        assert "Traceback" not in body and "nope" in body

    @pytest.mark.asyncio
    async def test_oversized_bodies_are_refused(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            r = await c.post("/mcp", content=b"x" * (1024 * 1024 + 10))
        assert r.status_code == 413


class TestIdentity:
    @pytest.mark.asyncio
    async def test_the_tool_sees_the_token_owner_and_prefix(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            out = json.loads(text(await call(c, "whoami")))
        assert out["email"] == "d@rp.com" and out["prefix"] == tok[1][:8]

    @pytest.mark.asyncio
    async def test_concurrent_callers_never_see_each_others_identity(self, mcp_app, session_factory, user_david, user_member):
        _, a = await new_token(session_factory, user_david)
        _, b = await new_token(session_factory, user_member)

        async def who(token):
            async with client(mcp_app, token) as c:
                return json.loads(text(await call(c, "whoami")))["email"]

        results = await asyncio.gather(*[who(a if i % 2 == 0 else b) for i in range(20)])
        assert results == ["d@rp.com" if i % 2 == 0 else "member@rp.com" for i in range(20)]

    @pytest.mark.asyncio
    async def test_links_use_the_public_base_url_when_set(self, engine, session_factory, user_david):
        app = await build_app(engine, session_factory, public_base_url="https://momboard.example.com/")
        _, plain = await new_token(session_factory, user_david)
        async with serve(app):
            async with client(app, plain, host="10.0.0.5:8080") as c:
                assert json.loads(text(await call(c, "whoami")))["base_url"] == "https://momboard.example.com"

    @pytest.mark.asyncio
    async def test_links_fall_back_to_the_request_host(self, mcp_app, tok):
        async with client(mcp_app, tok[1], host="momboard.internal") as c:
            assert json.loads(text(await call(c, "whoami")))["base_url"] == "http://momboard.internal"


class TestScopes:
    @pytest.mark.asyncio
    async def test_a_read_token_cannot_call_a_write_tool(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            r = await call(c, "save_thing")
        assert r["isError"] is True and "This token is read-only" in text(r)

    @pytest.mark.asyncio
    async def test_a_write_token_is_still_blocked_while_writes_are_switched_off(self, mcp_app, session_factory, user_david):
        _, plain = await new_token(session_factory, user_david, scope="write")
        async with client(mcp_app, plain) as c:
            r = await call(c, "save_thing")
        assert r["isError"] is True and "turned off" in text(r) and "MCP_ALLOW_WRITE" in text(r)

    @pytest.mark.asyncio
    async def test_a_write_token_works_once_writes_are_on(self, engine, session_factory, user_david):
        app = await build_app(engine, session_factory, mcp_allow_write=True)
        _, plain = await new_token(session_factory, user_david, scope="write")
        async with serve(app):
            async with client(app, plain) as c:
                r = await call(c, "save_thing", {"title": "hello"})
        assert not r.get("isError") and json.loads(text(r)) == {"saved": "hello"}

    @pytest.mark.asyncio
    async def test_read_tools_work_with_either_scope(self, mcp_app, session_factory, user_david):
        _, plain = await new_token(session_factory, user_david, scope="write")
        async with client(mcp_app, plain) as c:
            assert not (await call(c, "echo")).get("isError")


class TestErrors:
    @pytest.mark.asyncio
    async def test_a_rest_error_becomes_an_actionable_tool_error(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            r = await call(c, "missing")
        assert r["isError"] is True and "Hypothesis not found" in text(r)

    @pytest.mark.asyncio
    async def test_unexpected_errors_never_leak_internals(self, mcp_app, tok, caplog):
        caplog.set_level("ERROR")
        async with client(mcp_app, tok[1]) as c:
            r = await call(c, "explode")
        assert r["isError"] is True
        assert "psycopg2" not in text(r) and "secret-db-host" not in text(r) and "Traceback" not in text(r)
        assert "went wrong" in text(r)
        assert "secret-db-host" in caplog.text            # the detail is logged server-side

    @pytest.mark.asyncio
    async def test_a_slow_tool_times_out_with_a_clear_message(self, engine, session_factory, user_david):
        app = await build_app(engine, session_factory, mcp_tool_timeout_seconds=0.2)
        _, plain = await new_token(session_factory, user_david)
        async with serve(app):
            async with client(app, plain) as c:
                r = await asyncio.wait_for(call(c, "slow"), 5)
        assert r["isError"] is True and "took longer" in text(r)


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_sixty_calls_a_minute_then_429_with_retry_after(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            for i in range(60):
                r = await c.post("/mcp", json=rpc("tools/call", {"name": "echo", "arguments": {}}, i))
                assert r.status_code == 200, i
            r = await c.post("/mcp", json=rpc("tools/call", {"name": "echo", "arguments": {}}, 99))
            assert r.status_code == 429 and 1 <= int(r.headers["retry-after"]) <= 60

    @pytest.mark.asyncio
    async def test_listing_tools_does_not_use_up_the_budget(self, mcp_app, tok):
        async with client(mcp_app, tok[1]) as c:
            for i in range(80):
                assert (await c.post("/mcp", json=rpc("tools/list", id=i))).status_code == 200
            assert (await c.post("/mcp", json=rpc("tools/call", {"name": "echo", "arguments": {}}))).status_code == 200

    @pytest.mark.asyncio
    async def test_the_budget_is_per_token(self, engine, session_factory, user_david, user_member):
        app = await build_app(engine, session_factory, mcp_rate_limit_per_minute=3)
        _, a = await new_token(session_factory, user_david)
        _, b = await new_token(session_factory, user_member)
        async with serve(app):
            async with client(app, a) as ca, client(app, b) as cb:
                for _ in range(3):
                    await call(ca, "echo")
                r = await ca.post("/mcp", json=rpc("tools/call", {"name": "echo", "arguments": {}}))
                assert r.status_code == 429
                assert (await cb.post("/mcp", json=rpc("tools/call", {"name": "echo", "arguments": {}}))).status_code == 200

    @pytest.mark.asyncio
    async def test_a_batch_of_calls_counts_each_call(self, engine, session_factory, user_david):
        app = await build_app(engine, session_factory, mcp_rate_limit_per_minute=3)
        _, plain = await new_token(session_factory, user_david)
        batch = [rpc("tools/call", {"name": "echo", "arguments": {}}, i) for i in range(4)]
        async with serve(app):
            async with client(app, plain) as c:
                assert (await c.post("/mcp", json=batch)).status_code == 429

    @pytest.mark.asyncio
    async def test_unauthenticated_requests_do_not_consume_anyones_budget(self, engine, session_factory, user_david):
        app = await build_app(engine, session_factory, mcp_rate_limit_per_minute=2)
        _, plain = await new_token(session_factory, user_david)
        async with serve(app):
            async with client(app) as anon:
                for _ in range(10):
                    await anon.post("/mcp", json=rpc("tools/call", {"name": "echo", "arguments": {}}))
            async with client(app, plain) as c:
                assert (await c.post("/mcp", json=rpc("tools/call", {"name": "echo", "arguments": {}}))).status_code == 200


class TestAudit:
    @pytest.mark.asyncio
    async def test_every_call_is_recorded_with_the_token_prefix_and_no_text(self, mcp_app, tok, session_factory):
        tid, plain = tok
        long_text = "We spent three hours every Monday reconciling the export by hand and nobody trusts it. " * 5
        async with client(mcp_app, plain) as c:
            await call(c, "echo", {"query": long_text, "limit": 7})
            await call(c, "missing")
            await call(c, "explode")
            await call(c, "save_thing")
        async with session_factory() as db:
            rows = {r.tool: r for r in (await db.execute(select(McpCall))).scalars().all()}
        assert rows["echo"].status == "ok" and rows["echo"].result_count == 3
        assert rows["missing"].status == "error" and rows["explode"].status == "error"
        assert rows["save_thing"].status == "denied"
        for r in rows.values():
            assert r.token_id == tid and r.token_prefix == plain[:8] and r.duration_ms >= 0
            assert plain not in (r.args_summary or "") and long_text[:80] not in (r.args_summary or "")
        assert "limit=7" in rows["echo"].args_summary and len(rows["echo"].args_summary) <= 120

    @pytest.mark.asyncio
    async def test_listing_tools_is_not_a_tool_call(self, mcp_app, tok, session_factory):
        async with client(mcp_app, tok[1]) as c:
            await c.post("/mcp", json=rpc("tools/list"))
        async with session_factory() as db:
            assert (await db.execute(select(McpCall))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_prune_keeps_ninety_days(self, session_factory, tok):
        tid, plain = tok
        async with session_factory() as db:
            for days in (1, 89, 91, 200):
                await audit.record(db, token_id=tid, token_prefix=plain[:8], tool=f"t{days}", arguments={}, status="ok", duration_ms=1)
            rows = (await db.execute(select(McpCall))).scalars().all()
            for r in rows:
                r.created_at = datetime.now(UTC) - timedelta(days=int(r.tool[1:]))
            await db.commit()
        async with session_factory() as db:
            assert await audit.prune(db) == 2
            await db.commit()
            left = {r.tool for r in (await db.execute(select(McpCall))).scalars().all()}
        assert left == {"t1", "t89"}
