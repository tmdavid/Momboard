"""T25: MCP server — real MCP SDK with stdio + streamable HTTP transports.

7 tools: search_conversations, get_conversation, get_highlights, get_commitments,
         run_synthesis, create_conversation, ask_corpus.

Uses mcp (Python MCP SDK) for protocol compliance.
Auth: PAT header for HTTP transport, implicit trust for stdio.
Shared service layer (same functions as REST API).
"""

import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ─── Tool definitions ───

TOOLS = [
    Tool(
        name="search_conversations",
        description="Search conversations by title, company, contact, date range, or tags.",
        inputSchema={
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query text"},
                "company": {"type": "string", "description": "Company name filter"},
                "tag": {"type": "string", "description": "Tag key filter"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="get_conversation",
        description="Get full conversation detail including utterances, highlights, and analysis.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Conversation ID"},
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="get_highlights",
        description="Get highlights (tagged evidence) filtered by tag, company, date, status.",
        inputSchema={
            "type": "object",
            "properties": {
                "tag": {"type": "string"},
                "company": {"type": "string"},
                "status": {"type": "string", "default": "accepted"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="get_commitments",
        description="Get commitment and follow-up highlights, optionally filtered to open only.",
        inputSchema={
            "type": "object",
            "properties": {
                "open_only": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="run_synthesis",
        description="Run cross-conversation synthesis on filtered highlights.",
        inputSchema={
            "type": "object",
            "properties": {
                "filters": {"type": "object", "description": "Highlight filters"},
            },
            "required": ["filters"],
        },
    ),
    Tool(
        name="create_conversation",
        description="Create a new conversation from a transcript via staging inbox.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "transcript": {"type": "string"},
                "interviewer": {"type": "string"},
                "company": {"type": "string"},
                "contacts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "transcript"],
        },
    ),
    Tool(
        name="ask_corpus",
        description=(
            "Ask a question over the evidence corpus. Returns claims with highlight "
            "citations or indicates an evidence gap."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"},
                "filters": {"type": "object", "description": "Optional highlight filters"},
            },
            "required": ["question"],
        },
    ),
    Tool(
        name="list_hypotheses",
        description=(
            "List hypotheses (beliefs) with their grounding band and evidence strength "
            "counts. Read-only. grounding is one of grounded|contested|refuted|candidate|"
            "hunch — treat 'hunch'/'candidate' as unproven, 'contested' as customers "
            "disagreeing. Optionally filter by grounding."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "grounding": {
                    "type": "string",
                    "description": "Optional filter: grounded|contested|refuted|candidate|hunch",
                },
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="get_hypothesis",
        description=(
            "Get one hypothesis with its grounding band, strength counts, and the "
            "confirmed evidence links (both supporting and contradicting), each with "
            "quote and conversation id. Read-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Hypothesis ID"}},
            "required": ["id"],
        },
    ),
    Tool(
        name="list_decisions",
        description=(
            "List decisions with status (proposed|decided|superseded) and integrity "
            "(ok|undermined). Read-only. Do not build on an 'undermined' decision without "
            "checking why."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional status filter"},
                "integrity": {"type": "string", "description": "Optional integrity filter"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="get_decision",
        description=(
            "Get one decision with its rationale, status, integrity (+ reasons), the "
            "hypothesis it rests on, and the cited evidence quotes. Read-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Decision ID"}},
            "required": ["id"],
        },
    ),
]


# ─── Tool handler dispatch (shared with HTTP transport) ───


async def handle_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    db_session: Any,
    settings: Any = None,
) -> dict[str, Any]:
    """Handle an MCP tool call — delegates to the shared service layer.

    This is the canonical entry point used by both stdio and HTTP transports.
    """

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import (
        Analysis,
        Company,
        Conversation,
        Highlight,
        Job,
        Utterance,
    )

    db: AsyncSession = db_session

    if tool_name == "search_conversations":
        query = select(Conversation).order_by(Conversation.created_at.desc())
        q = arguments.get("q")
        company = arguments.get("company")
        limit = arguments.get("limit", 20)

        if q:
            query = query.where(Conversation.title.ilike(f"%{q}%"))
        if company:
            query = query.join(Company).where(Company.name.ilike(f"%{company}%"))
        query = query.limit(limit)
        result = await db.execute(query)
        convos = result.scalars().all()
        return {
            "conversations": [
                {
                    "id": c.id,
                    "title": c.title,
                    "status": c.status,
                    "happened_at": c.happened_at.isoformat() if c.happened_at else None,
                }
                for c in convos
            ]
        }

    elif tool_name == "get_conversation":
        convo_id = arguments["id"]
        convo = await db.get(Conversation, convo_id)
        if convo is None:
            return {"error": "Conversation not found"}
        utts_result = await db.execute(
            select(Utterance)
            .where(Utterance.conversation_id == convo_id)
            .order_by(Utterance.idx)
        )
        hl_result = await db.execute(
            select(Highlight).where(Highlight.conversation_id == convo_id)
        )
        return {
            "id": convo.id,
            "title": convo.title,
            "status": convo.status,
            "utterances": [
                {"idx": u.idx, "speaker": u.speaker_label, "text": u.text}
                for u in utts_result.scalars().all()
            ],
            "highlights": [
                {"id": h.id, "tag": h.tag_key, "quote": h.quote, "status": h.status}
                for h in hl_result.scalars().all()
            ],
        }

    elif tool_name == "get_highlights":
        hl_query = select(Highlight)
        tag = arguments.get("tag")
        status = arguments.get("status", "accepted")
        limit = arguments.get("limit", 50)
        if tag:
            hl_query = hl_query.where(Highlight.tag_key == tag)
        if status:
            hl_query = hl_query.where(Highlight.status == status)
        hl_query = hl_query.order_by(Highlight.created_at.desc()).limit(limit)
        hl_result = await db.execute(hl_query)
        return {
            "highlights": [
                {
                    "id": h.id,
                    "tag": h.tag_key,
                    "quote": h.quote,
                    "conversation_id": h.conversation_id,
                }
                for h in hl_result.scalars().all()
            ]
        }

    elif tool_name == "get_commitments":
        open_only = arguments.get("open_only", True)
        limit = arguments.get("limit", 50)
        commit_query = select(Highlight).where(
            Highlight.tag_key.in_(["commitment", "followup"])
        )
        if open_only:
            commit_query = commit_query.where(Highlight.status.in_(["accepted", "suggested"]))
        commit_query = commit_query.order_by(Highlight.created_at.desc()).limit(limit)
        commits_result = await db.execute(commit_query)
        return {
            "commitments": [
                {
                    "id": h.id,
                    "tag": h.tag_key,
                    "quote": h.quote,
                    "conversation_id": h.conversation_id,
                }
                for h in commits_result.scalars().all()
            ]
        }

    elif tool_name == "run_synthesis":
        filters = arguments.get("filters", {})
        analysis = Analysis(kind="synthesis", input_scope=filters)
        db.add(analysis)
        await db.flush()
        job = Job(
            kind="synthesize",
            payload={"analysis_id": analysis.id, "filters": filters},
            status="queued",
        )
        db.add(job)
        await db.flush()
        return {"analysis_id": analysis.id, "status": "queued"}

    elif tool_name == "create_conversation":
        from app.services import DuplicateSourceRefError, submit_to_inbox

        title = arguments["title"]
        transcript = arguments["transcript"]
        source_ref = f"mcp:{hash(transcript)}"
        try:
            item = await submit_to_inbox(
                db,
                source="mcp",
                source_ref=source_ref,
                title=title,
                raw_content=transcript,
                content_format="auto",
                meta={
                    "interviewer": arguments.get("interviewer"),
                    "company": arguments.get("company"),
                    "contacts": arguments.get("contacts"),
                },
            )
            await db.flush()
            return {"inbox_item_id": item.id, "status": "pending_import"}
        except DuplicateSourceRefError as e:
            return {"error": str(e), "existing_id": e.existing_id}

    elif tool_name == "ask_corpus":
        from app.config import get_settings
        from app.llm.factory import create_llm_client
        from app.services.corpus_chat import ask_corpus

        question = arguments["question"]
        filters = arguments.get("filters")
        s = settings or get_settings()
        llm = create_llm_client(s, agent="chat")
        try:
            result_data: dict[str, Any] = await ask_corpus(db, question, llm=llm, filters=filters)
        finally:
            await llm.close()
        return result_data

    elif tool_name == "list_hypotheses":
        from app.api.hypotheses import _build_rollup, _compute_grounding
        from app.models import Hypothesis

        grounding_filter = arguments.get("grounding")
        limit = arguments.get("limit", 50)
        hyps_result = await db.execute(
            select(Hypothesis)
            .where(Hypothesis.status != "archived")
            .order_by(Hypothesis.created_at.desc())
        )
        items = []
        for hyp in hyps_result.scalars().all():
            supports, contradicts, _co_sup, _co_con, _last = await _build_rollup(db, hyp.id)
            grounding = _compute_grounding(supports, contradicts)
            if grounding_filter and grounding != grounding_filter:
                continue
            items.append({
                "id": hyp.id,
                "statement": hyp.statement,
                "segment": hyp.segment,
                "status": hyp.status,
                "origin": hyp.origin,
                "grounding": grounding,
                "supporting": supports.get("confirmed", 0),
                "contradicting": contradicts.get("confirmed", 0),
                "suggested": supports.get("suggested", 0) + contradicts.get("suggested", 0),
            })
            if len(items) >= limit:
                break
        return {"hypotheses": items}

    elif tool_name == "get_hypothesis":
        from app.api.hypotheses import _build_rollup, _compute_grounding
        from app.models import Hypothesis, HypothesisLink

        hyp_row = await db.get(Hypothesis, arguments["id"])
        if hyp_row is None:
            return {"error": "Hypothesis not found"}
        supports, contradicts, _co_sup, _co_con, _last = await _build_rollup(db, hyp_row.id)
        # Confirmed evidence links with quote + conversation ref (citations).
        links_result = await db.execute(
            select(HypothesisLink, Highlight)
            .join(Highlight, HypothesisLink.highlight_id == Highlight.id)
            .where(
                HypothesisLink.hypothesis_id == hyp_row.id,
                HypothesisLink.status == "confirmed",
            )
        )
        evidence = [
            {
                "stance": link.stance,
                "quote": hl.quote,
                "highlight_id": hl.id,
                "conversation_id": hl.conversation_id,
            }
            for link, hl in links_result.all()
        ]
        return {
            "id": hyp_row.id,
            "statement": hyp_row.statement,
            "segment": hyp_row.segment,
            "status": hyp_row.status,
            "origin": hyp_row.origin,
            "grounding": _compute_grounding(supports, contradicts),
            "supporting": supports.get("confirmed", 0),
            "contradicting": contradicts.get("confirmed", 0),
            "evidence": evidence,
        }

    elif tool_name == "list_decisions":
        from app.models import Decision

        d_query = select(Decision).order_by(Decision.created_at.desc())
        if arguments.get("status"):
            d_query = d_query.where(Decision.status == arguments["status"])
        if arguments.get("integrity"):
            d_query = d_query.where(Decision.integrity == arguments["integrity"])
        d_query = d_query.limit(arguments.get("limit", 50))
        d_result = await db.execute(d_query)
        return {
            "decisions": [
                {
                    "id": d.id,
                    "title": d.title,
                    "status": d.status,
                    "integrity": d.integrity,
                    "hypothesis_id": d.hypothesis_id,
                }
                for d in d_result.scalars().all()
            ]
        }

    elif tool_name == "get_decision":
        from app.models import Decision, DecisionEvidence

        decision = await db.get(Decision, arguments["id"])
        if decision is None:
            return {"error": "Decision not found"}
        ev_result = await db.execute(
            select(DecisionEvidence, Highlight)
            .join(Highlight, DecisionEvidence.highlight_id == Highlight.id)
            .where(DecisionEvidence.decision_id == decision.id)
        )
        evidence = [
            {"highlight_id": hl.id, "quote": hl.quote, "conversation_id": hl.conversation_id}
            for _de, hl in ev_result.all()
        ]
        return {
            "id": decision.id,
            "title": decision.title,
            "rationale_md": decision.rationale_md,
            "status": decision.status,
            "integrity": decision.integrity,
            "integrity_reasons": decision.integrity_reasons,
            "hypothesis_id": decision.hypothesis_id,
            "evidence": evidence,
        }

    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ─── MCP Server instance ───


def create_mcp_server() -> Server:
    """Create and configure the MCP Server instance with all tools registered."""
    server: Server = Server("momboard")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        """Dispatch tool call to handler, using a fresh DB session."""
        import json as json_mod

        from app.config import get_settings
        from app.db import create_engine, create_session_factory

        settings = get_settings()
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        async with session_factory() as db:
            result = await handle_tool_call(
                name,
                arguments or {},
                db_session=db,
                settings=settings,
            )
            await db.commit()
        await engine.dispose()

        return [TextContent(type="text", text=json_mod.dumps(result, default=str))]

    return server


# ─── Entry points for transports ───


async def run_stdio() -> None:
    """Run MCP server over stdio transport (for Claude Desktop / CLI)."""
    server = create_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def mount_streamable_http(app: Any) -> None:
    """Mount the MCP server as a streamable HTTP endpoint on a FastAPI/Starlette app.

    Accessible at POST /mcp — uses signed session tokens for auth (same as REST API).
    The Bearer token or session cookie must be a valid signed session token issued by
    the app's session_secret. Presence-only credentials are rejected.
    """
    import json as json_mod

    from app.auth import decode_session_token
    from app.models import User

    async def _authenticate_mcp_request(request: Request) -> int | None:
        """Validate MCP request credentials and return user_id or None.

        Accepts either:
        - Authorization: Bearer <signed-session-token>
        - session cookie containing a signed session token

        Returns user_id if valid, None otherwise.
        """
        settings = request.app.state.settings
        secret = settings.session_secret

        # Try Bearer token first
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_id = decode_session_token(token, secret)
            if user_id is not None:
                return user_id
            return None

        # Try session cookie
        session_cookie = request.cookies.get("session")
        if session_cookie:
            user_id = decode_session_token(session_cookie, secret)
            return user_id

        return None

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
    async def mcp_endpoint(request: Request) -> Response:
        """Handle MCP JSON-RPC over HTTP with cryptographic auth.

        Credentials must be a valid signed session token (bearer or cookie).
        Invalid/expired/malformed tokens or tokens referencing nonexistent users → 401.
        Valid JSON-RPC → dispatched through handle_tool_call.
        """
        # Cryptographic auth: decode and verify the signed session token
        user_id = await _authenticate_mcp_request(request)
        if user_id is None:
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Unauthorized"}, "id": None},
                status_code=401,
            )

        # Verify user exists and is valid
        session_factory = request.app.state.session_factory
        async with session_factory() as db:
            user: User | None = await db.get(User, user_id)
            if user is None:
                return JSONResponse(
                    {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Unauthorized"}, "id": None},
                    status_code=401,
                )

        # Only POST carries JSON-RPC requests
        if request.method != "POST":
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Only POST supported"}, "id": None},
                status_code=405,
            )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
                status_code=400,
            )

        method = body.get("method", "")
        req_id = body.get("id")
        params = body.get("params", {})

        # Handle MCP protocol methods
        if method == "initialize":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "momboard", "version": "0.2.0"},
                },
            })

        elif method == "tools/list":
            tools_list = [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.inputSchema,
                }
                for t in TOOLS
            ]
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools_list},
            })

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            app_settings = request.app.state.settings
            app_session_factory = request.app.state.session_factory
            try:
                async with app_session_factory() as db:
                    result = await handle_tool_call(
                        tool_name,
                        arguments,
                        db_session=db,
                        settings=app_settings,
                    )
                    await db.commit()
            except Exception as exc:
                logger.exception("MCP tools/call error: %s", exc)
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Internal error: {exc}"},
                })

            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json_mod.dumps(result, default=str)}],
                },
            })

        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


# ─── CLI entry point ───

if __name__ == "__main__":
    import asyncio

    asyncio.run(run_stdio())
