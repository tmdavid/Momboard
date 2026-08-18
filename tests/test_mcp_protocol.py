"""T25: MCP protocol tests — tool registration, schema validation, transport wiring.

Tests the actual MCP SDK Server, tool schemas, unknown tool errors, and
transport boundary (stdio + streamable HTTP). Tests:
1. Server instance creation and tool listing
2. Tool call dispatch via the server's internal handler
3. StreamableHTTP is mounted on the FastAPI app
4. Auth: unauthenticated JSON-RPC → 401, authenticated → 200 with valid response
5. 7 tool schema contracts
6. Unknown tool error handling
7. Parity with shared REST service layer
8. Valid initialize/list-tools/call-tool JSON-RPC exchange through HTTP ASGI boundary
9. Stdio transport is executable
10. Auth hardening: garbage bearer 401, malformed cookie 401, signed token for
    nonexistent user 401, valid signed bearer succeeds, valid signed session cookie succeeds
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import create_session_token
from app.mcp_server import TOOLS, create_mcp_server, handle_tool_call, mount_streamable_http


class TestMCPToolSchemas:
    """Verify all 7 tools are registered with correct schemas."""

    def test_seven_tools_registered(self):
        assert len(TOOLS) == 7

    def test_tool_names(self):
        names = {t.name for t in TOOLS}
        expected = {
            "search_conversations",
            "get_conversation",
            "get_highlights",
            "get_commitments",
            "run_synthesis",
            "create_conversation",
            "ask_corpus",
        }
        assert names == expected

    def test_each_tool_has_input_schema(self):
        for tool in TOOLS:
            assert tool.inputSchema is not None
            assert tool.inputSchema.get("type") == "object"
            assert "properties" in tool.inputSchema

    def test_required_fields_on_get_conversation(self):
        tool = next(t for t in TOOLS if t.name == "get_conversation")
        assert "required" in tool.inputSchema
        assert "id" in tool.inputSchema["required"]

    def test_required_fields_on_create_conversation(self):
        tool = next(t for t in TOOLS if t.name == "create_conversation")
        assert "required" in tool.inputSchema
        assert "title" in tool.inputSchema["required"]
        assert "transcript" in tool.inputSchema["required"]

    def test_required_fields_on_ask_corpus(self):
        tool = next(t for t in TOOLS if t.name == "ask_corpus")
        assert "required" in tool.inputSchema
        assert "question" in tool.inputSchema["required"]

    def test_required_fields_on_run_synthesis(self):
        tool = next(t for t in TOOLS if t.name == "run_synthesis")
        assert "required" in tool.inputSchema
        assert "filters" in tool.inputSchema["required"]


class TestMCPServerCreation:
    """Test MCP Server instance creation and tool listing."""

    def test_create_server_returns_server_instance(self):
        from mcp.server import Server
        server = create_mcp_server()
        assert isinstance(server, Server)
        assert server.name == "momboard"


class TestMCPToolDispatch:
    """Test tool call dispatch through handle_tool_call."""

    @pytest.mark.asyncio
    async def test_search_conversations_returns_list(self, seeded_db):
        result = await handle_tool_call(
            "search_conversations",
            {"q": "test", "limit": 5},
            db_session=seeded_db,
        )
        assert "conversations" in result
        assert isinstance(result["conversations"], list)

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, seeded_db):
        result = await handle_tool_call(
            "get_conversation",
            {"id": 99999},
            db_session=seeded_db,
        )
        assert result.get("error") == "Conversation not found"

    @pytest.mark.asyncio
    async def test_get_highlights_empty(self, seeded_db):
        result = await handle_tool_call(
            "get_highlights",
            {"status": "accepted"},
            db_session=seeded_db,
        )
        assert "highlights" in result

    @pytest.mark.asyncio
    async def test_get_commitments_empty(self, seeded_db):
        result = await handle_tool_call(
            "get_commitments",
            {"open_only": True},
            db_session=seeded_db,
        )
        assert "commitments" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, seeded_db):
        result = await handle_tool_call(
            "nonexistent_tool",
            {},
            db_session=seeded_db,
        )
        assert "error" in result
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_create_conversation_dedupes(self, seeded_db):
        """Create the same conversation twice → dedupe error."""
        args = {"title": "Test Convo", "transcript": "Hello world"}
        result1 = await handle_tool_call("create_conversation", args, db_session=seeded_db)
        assert "inbox_item_id" in result1

        # Same content → dedupe
        result2 = await handle_tool_call("create_conversation", args, db_session=seeded_db)
        assert "error" in result2 or "existing_id" in result2


class TestMCPToolParityWithREST:
    """Verify MCP tool outputs match REST service layer semantics."""

    @pytest.mark.asyncio
    async def test_search_parity(self, seeded_db, sample_conversation):
        """MCP search returns same shape as REST /api/conversations."""
        result = await handle_tool_call(
            "search_conversations",
            {"limit": 10},
            db_session=seeded_db,
        )
        convos = result["conversations"]
        assert len(convos) >= 1
        c = convos[0]
        # Same fields as REST API list endpoint
        assert "id" in c
        assert "title" in c
        assert "status" in c

    @pytest.mark.asyncio
    async def test_get_conversation_parity(self, seeded_db, sample_conversation):
        """MCP get_conversation returns utterances + highlights like REST."""
        result = await handle_tool_call(
            "get_conversation",
            {"id": sample_conversation.id},
            db_session=seeded_db,
        )
        assert result["id"] == sample_conversation.id
        assert "utterances" in result
        assert "highlights" in result
        assert isinstance(result["utterances"], list)


class TestStreamableHTTPMount:
    """Verify streamable HTTP transport is actually mounted on the app."""

    @pytest.mark.asyncio
    async def test_mcp_endpoint_exists(self, app):
        """The /mcp endpoint is registered on the FastAPI app."""
        mount_streamable_http(app)
        route_paths = [r.path for r in app.routes]
        assert "/mcp" in route_paths

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(self, app):
        """POST /mcp without auth returns 401 (not 404 or 500)."""
        mount_streamable_http(app)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            )
            assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_initialize_returns_result(self, app, user_david):
        """POST /mcp with valid signed Bearer token → valid initialize response."""
        mount_streamable_http(app)
        token = create_session_token(user_david.id, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["jsonrpc"] == "2.0"
            assert body["id"] == 1
            assert "result" in body
            assert body["result"]["serverInfo"]["name"] == "momboard"
            assert "capabilities" in body["result"]

    @pytest.mark.asyncio
    async def test_authenticated_list_tools_returns_7(self, app, user_david):
        """POST /mcp tools/list with valid auth returns all 7 tools."""
        mount_streamable_http(app)
        token = create_session_token(user_david.id, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["id"] == 2
            tools = body["result"]["tools"]
            assert len(tools) == 7
            names = {t["name"] for t in tools}
            assert "search_conversations" in names
            assert "ask_corpus" in names

    @pytest.mark.asyncio
    async def test_authenticated_call_tool_returns_content(self, app, user_david):
        """POST /mcp tools/call with valid auth returns tool result."""
        mount_streamable_http(app)
        token = create_session_token(user_david.id, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 3,
                    "params": {
                        "name": "search_conversations",
                        "arguments": {"q": "test", "limit": 5},
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["id"] == 3
            content = body["result"]["content"]
            assert len(content) == 1
            assert content[0]["type"] == "text"
            # Parse the JSON text
            result_data = json.loads(content[0]["text"])
            assert "conversations" in result_data

    @pytest.mark.asyncio
    async def test_http_tool_call_sees_fixture_conversation(
        self, app, user_david, sample_conversation
    ):
        """Regression: MCP HTTP tools/call shares the app DB — fixture data is visible.

        A conversation created in the shared test fixture DB must be retrievable
        through an authenticated HTTP MCP get_conversation tool call, proving
        the HTTP handler uses app.state.session_factory (same engine/DB) and not
        a separate in-memory database.
        """
        mount_streamable_http(app)
        token = create_session_token(user_david.id, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 10,
                    "params": {
                        "name": "get_conversation",
                        "arguments": {"id": sample_conversation.id},
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["id"] == 10
            assert "error" not in body
            content = body["result"]["content"]
            assert content[0]["type"] == "text"
            result_data = json.loads(content[0]["text"])
            # Proves the MCP HTTP path reads from the same DB as the fixtures
            assert result_data["id"] == sample_conversation.id
            assert result_data["title"] == "Acme discovery call"
            assert len(result_data["utterances"]) == 4
            assert result_data["utterances"][0]["speaker"] == "David"


class TestMCPAuthHardening:
    """Auth hardening: cryptographic validation of credentials.

    Ensures that presence-only credentials are rejected; only properly signed
    session tokens referencing existing users are accepted.
    """

    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, app):
        """MCP HTTP without any auth (no cookie, no bearer) returns 401."""
        mount_streamable_http(app)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
            )
            assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_garbage_bearer_returns_401(self, app):
        """Bearer with arbitrary garbage string is rejected."""
        mount_streamable_http(app)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={"Authorization": "Bearer garbage-token-xyz"},
            )
            assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_cookie_returns_401(self, app):
        """Session cookie with invalid/malformed value is rejected."""
        mount_streamable_http(app)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            cookies={"session": "not-a-valid-signed-token"},
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            )
            assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_signed_bearer_succeeds(self, app, user_david):
        """A properly signed Bearer token for an existing user succeeds."""
        mount_streamable_http(app)
        token = create_session_token(user_david.id, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["result"]["serverInfo"]["name"] == "momboard"

    @pytest.mark.asyncio
    async def test_valid_signed_session_cookie_succeeds(self, app, user_david):
        """A properly signed session cookie for an existing user succeeds."""
        mount_streamable_http(app)
        token = create_session_token(user_david.id, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            cookies={"session": token},
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["result"]["serverInfo"]["name"] == "momboard"

    @pytest.mark.asyncio
    async def test_signed_token_for_nonexistent_user_returns_401(self, app):
        """A signed token referencing a user_id that doesn't exist returns 401."""
        mount_streamable_http(app)
        # Create a token for user_id=99999 which doesn't exist in the DB
        token = create_session_token(99999, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_tool_calls_work_with_valid_auth(self, app, user_david):
        """Tool calls (tools/call) work correctly with valid auth — end-to-end."""
        mount_streamable_http(app)
        token = create_session_token(user_david.id, app.state.settings.session_secret)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 5,
                    "params": {
                        "name": "get_highlights",
                        "arguments": {"status": "accepted", "limit": 10},
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["id"] == 5
            content = body["result"]["content"]
            assert content[0]["type"] == "text"
            result_data = json.loads(content[0]["text"])
            assert "highlights" in result_data

    @pytest.mark.asyncio
    async def test_wrong_secret_bearer_returns_401(self, app, user_david):
        """A token signed with a different secret is rejected."""
        mount_streamable_http(app)
        # Sign with a different secret
        token = create_session_token(user_david.id, "wrong-secret-entirely")

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            r = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 401


class TestMCPAuthBehavior:
    """Auth requirements for HTTP transport (legacy tests)."""

    @pytest.mark.asyncio
    async def test_api_routes_require_auth(self, client):
        """API routes (REST) require authentication."""
        r = await client.get("/api/conversations")
        assert r.status_code == 401 or r.status_code == 403


class TestMCPStdioTransport:
    """Verify stdio transport is executable as a subprocess."""

    def test_stdio_module_is_importable(self):
        """The mcp_server module can be imported for stdio use."""
        from app.mcp_server import run_stdio
        assert callable(run_stdio)

    def test_stdio_entry_point_syntax_valid(self):
        """The __main__ guard makes the module executable without error on import."""
        # Verify the script is syntactically valid and importable
        result = subprocess.run(
            [sys.executable, "-c", "import app.mcp_server"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            timeout=5,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
