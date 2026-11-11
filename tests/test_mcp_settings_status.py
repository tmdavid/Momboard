"""The Connect-to-Claude card is driven by an `mcp` block on /api/settings/status."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import create_session_token
from app.config import Settings
from app.main import create_app


def settings(**over):
    base = dict(database_url="sqlite+aiosqlite://", session_secret="test-secret", openai_api_key="", env="test",
                worker_poll_interval=0.1)
    base.update(over)
    return Settings(**base)


async def status_for(engine, session_factory, user, **over):
    app = create_app(settings(**over))
    app.state.engine, app.state.session_factory = engine, session_factory
    cookie = create_session_token(user.id, app.state.settings.session_secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://momboard.internal:8080",
                           cookies={"session": cookie}, headers=over.pop("headers", {})) as c:
        return (await c.get("/api/settings/status")).json()


@pytest.mark.asyncio
async def test_off_by_default_and_says_so(engine, session_factory, user_david):
    mcp = (await status_for(engine, session_factory, user_david))["mcp"]
    assert mcp["enabled"] is False and mcp["url"] is None and mcp["allow_write"] is False


@pytest.mark.asyncio
async def test_when_on_it_gives_the_exact_url_and_limits(engine, session_factory, user_david):
    mcp = (await status_for(engine, session_factory, user_david, mcp_enabled=True, mcp_rate_limit_per_minute=30))["mcp"]
    assert mcp["enabled"] is True and mcp["url"] == "http://momboard.internal:8080/mcp"
    assert mcp["rate_limit_per_minute"] == 30 and mcp["public_url_configured"] is False


@pytest.mark.asyncio
async def test_a_configured_public_url_wins_and_is_flagged(engine, session_factory, user_david):
    mcp = (await status_for(engine, session_factory, user_david, mcp_enabled=True, public_base_url="https://mb.example.com/"))["mcp"]
    assert mcp["url"] == "https://mb.example.com/mcp" and mcp["public_url_configured"] is True


@pytest.mark.asyncio
async def test_nothing_secret_is_exposed(engine, session_factory, user_david):
    body = await status_for(engine, session_factory, user_david, mcp_enabled=True)
    assert set(body["mcp"]) == {"enabled", "url", "allow_write", "rate_limit_per_minute", "public_url_configured"}
