"""Tests for T24 Google Meet/Drive parsing and T25 MCP server tools."""

from pathlib import Path

import pytest

from app.mcp_server import TOOLS, handle_tool_call
from app.services.gmeet import parse_meet_doc

# --- T24 Google Meet Doc Parsing ---


def test_parse_meet_doc_standard_format():
    """Standard Meet transcript format: Speaker\\nTimestamp\\nText."""
    content = (
        "David Torres\n10:30 AM\nHey, thanks for joining today.\n\n"
        "Maria Lopez\n10:31 AM\nSure, happy to chat about our process.\n\n"
        "David Torres\n10:32 AM\nSo what does your current workflow look like?\n\n"
    )
    parsed, error = parse_meet_doc(content)
    assert error is None
    assert "David Torres: Hey, thanks for joining today." in parsed
    assert "Maria Lopez: Sure, happy to chat about our process." in parsed


def test_parse_meet_doc_fixture():
    """Parse the recorded Drive fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "drive" / "doc_export_002.txt"
    if fixture_path.exists():
        content = fixture_path.read_text()
        parsed, error = parse_meet_doc(content)
        # Should either parse successfully or return a specific error
        assert parsed or error


def test_parse_meet_doc_unparseable_returns_error():
    """Completely unparseable content returns error, not crash."""
    parsed, error = parse_meet_doc("x")
    assert parsed == ""
    assert error is not None
    assert "Could not parse" in error


def test_parse_meet_doc_simple_name_text():
    """Simple name-based alternating format."""
    content = "Speaker A\nHello there\nSpeaker B\nHi, how are you?"
    parsed, error = parse_meet_doc(content)
    # Should attempt to parse even without timestamps
    assert parsed or error  # One or the other, no crash


# --- T25 MCP Server ---


def test_mcp_tools_defined():
    """MCP server defines the required 7 tools."""
    tools = TOOLS
    names = {t.name for t in tools}
    expected = {
        "search_conversations",
        "get_conversation",
        "get_highlights",
        "get_commitments",
        "run_synthesis",
        "create_conversation",
        "ask_corpus",
    }
    assert expected == names


def test_mcp_tools_have_schemas():
    """Every tool has an inputSchema."""
    tools = TOOLS
    for tool in tools:
        assert tool.inputSchema is not None
        assert tool.inputSchema["type"] == "object"


@pytest.mark.asyncio
async def test_mcp_search_conversations(seeded_db, sample_conversation):
    """MCP search_conversations returns matching results."""
    result = await handle_tool_call(
        "search_conversations",
        {"q": "Acme"},
        db_session=seeded_db,
    )
    assert "conversations" in result
    assert len(result["conversations"]) >= 1


@pytest.mark.asyncio
async def test_mcp_get_conversation(seeded_db, sample_conversation):
    """MCP get_conversation returns full detail."""
    result = await handle_tool_call(
        "get_conversation",
        {"id": sample_conversation.id},
        db_session=seeded_db,
    )
    assert result["id"] == sample_conversation.id
    assert "utterances" in result
    assert len(result["utterances"]) >= 1


@pytest.mark.asyncio
async def test_mcp_get_conversation_not_found(seeded_db):
    """MCP get_conversation with invalid ID returns error."""
    result = await handle_tool_call(
        "get_conversation",
        {"id": 99999},
        db_session=seeded_db,
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_mcp_get_highlights(seeded_db, sample_conversation):
    """MCP get_highlights returns highlights list."""
    from app.models import Highlight
    seeded_db.add(Highlight(
        conversation_id=sample_conversation.id,
        tag_key="pain",
        quote="Test pain",
        status="accepted",
        origin="ai",
    ))
    await seeded_db.commit()

    result = await handle_tool_call(
        "get_highlights",
        {"tag": "pain", "status": "accepted"},
        db_session=seeded_db,
    )
    assert "highlights" in result
    assert len(result["highlights"]) >= 1


@pytest.mark.asyncio
async def test_mcp_get_commitments(seeded_db, sample_conversation):
    """MCP get_commitments returns commitment/followup highlights."""
    from app.models import Highlight
    seeded_db.add(Highlight(
        conversation_id=sample_conversation.id,
        tag_key="commitment",
        quote="Will send intro",
        status="accepted",
        origin="ai",
    ))
    await seeded_db.commit()

    result = await handle_tool_call(
        "get_commitments",
        {"open_only": True},
        db_session=seeded_db,
    )
    assert "commitments" in result
    assert len(result["commitments"]) >= 1


@pytest.mark.asyncio
async def test_mcp_create_conversation_via_inbox(seeded_db):
    """MCP create_conversation submits to staging inbox."""
    result = await handle_tool_call(
        "create_conversation",
        {
            "title": "MCP Test Call",
            "transcript": "Speaker: Hello\nOther: Hi there",
        },
        db_session=seeded_db,
    )
    await seeded_db.commit()
    assert "inbox_item_id" in result
    assert result["status"] == "pending_import"


@pytest.mark.asyncio
async def test_mcp_ask_corpus(seeded_db):
    """MCP ask_corpus returns gap answer when empty."""
    result = await handle_tool_call(
        "ask_corpus",
        {"question": "what about pricing?"},
        db_session=seeded_db,
    )
    assert result["gap"] is True


@pytest.mark.asyncio
async def test_mcp_unknown_tool(seeded_db):
    """Unknown tool name returns error."""
    result = await handle_tool_call(
        "nonexistent_tool",
        {},
        db_session=seeded_db,
    )
    assert "error" in result
