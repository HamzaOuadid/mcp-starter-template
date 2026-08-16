"""Real MCP stdio server built on the official MCP Python SDK.

This is what a client like Claude Desktop or the ``mcp`` CLI actually
talks to. Every tool takes an explicit ``token`` and ``session_id``
argument rather than relying on transport-level headers: stdio MCP
servers are typically one process per single local user, so there is no
per-request "Authorization" header to intercept the way an HTTP
transport has (see ``http_app.py`` for that variant, where the token
really does come from a header). Passing the token explicitly keeps the
auth-passthrough behaviour identical and testable across both
transports, and is a common, documented simplification for reference/dev
MCP servers -- production deployments fronting multiple real users
should prefer the HTTP transport with a real per-request credential.

Run with: ``mcp-starter serve-stdio`` (see ``cli.py``), or directly:
``python -m mcp_starter.mcp_app``.
"""

from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .config import ServerConfig
from .server import MCPStarterServer


def build_mcp_server(config: Optional[ServerConfig] = None, config_path: Optional[str] = None) -> FastMCP:
    if config is None:
        config = ServerConfig.from_yaml(config_path) if config_path else ServerConfig.default()

    starter = MCPStarterServer(config=config)
    mcp = FastMCP(
        name="mcp-starter-template",
        instructions=(
            "Security-first MCP starter server. Tools require an explicit "
            "`token` (try 'token-alice', 'token-bob', or 'token-admin' for "
            "the seeded dev users) and `session_id` for rate limiting."
        ),
    )

    @mcp.tool(description="Search internal docs visible to the calling user's team (read-only).")
    def search_docs(query: str, token: str, session_id: str) -> dict[str, Any]:
        result = starter.call_tool(session_id=session_id, token=token, tool_name="search_docs", arguments={"query": query})
        return result.to_dict()

    @mcp.tool(
        description=(
            "Create a ticket in the downstream ticket system. Write tool: "
            "gated behind the allowlist and, when dry-run mode is on, "
            "never calls the real downstream API."
        )
    )
    def create_ticket(title: str, body: str, token: str, session_id: str) -> dict[str, Any]:
        result = starter.call_tool(
            session_id=session_id,
            token=token,
            tool_name="create_ticket",
            arguments={"title": title, "body": body},
        )
        return result.to_dict()

    @mcp.tool(description="List every registered tool and its read/write classification (for security review).")
    def list_tools() -> list[dict[str, Any]]:
        return starter.list_tools()

    return mcp


def main() -> None:
    server = build_mcp_server()
    server.run()


if __name__ == "__main__":
    main()
