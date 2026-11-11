"""Tools declared the way real tool modules are: postponed annotations, unions and optionals."""

from __future__ import annotations

from typing import Any

from app.mcp.server import McpServer


def register(server: McpServer) -> None:
    @server.tool(name="annotated")
    async def annotated(needed: int, names: list[str] | None = None, maybe_text: str | None = None, flag: bool = False) -> dict[str, Any]:
        """Echo the arguments, to prove annotations are understood."""
        return {"needed": needed, "names": names, "maybe_text": maybe_text, "flag": flag}
