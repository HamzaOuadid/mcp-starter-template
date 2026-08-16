"""HTTP transport variant, built on FastAPI.

Unlike the stdio adapter (``mcp_app.py``), this is a real multi-tenant
transport: the calling user's token comes from the ``Authorization:
Bearer <token>`` header on each request, and the session comes from an
``X-Session-Id`` header -- exactly the shape a production per-user
auth-passthrough deployment would use, since a shared service-account
credential is never in the request path at all.

Endpoints:
  GET  /tools                 -- registry listing (security review)
  POST /tools/{tool_name}/call -- invoke a tool
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .config import ServerConfig
from .server import MCPStarterServer


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


def create_app(server: Optional[MCPStarterServer] = None, config_path: Optional[str] = None) -> FastAPI:
    if server is None:
        config = ServerConfig.from_yaml(config_path) if config_path else ServerConfig.default()
        server = MCPStarterServer(config=config)

    app = FastAPI(title="mcp-starter-template", description="Security-first MCP server starter (HTTP transport)")
    app.state.server = server

    @app.get("/tools")
    def list_tools() -> list[dict[str, Any]]:
        return server.list_tools()

    @app.post("/tools/{tool_name}/call")
    def call_tool(
        tool_name: str,
        request: ToolCallRequest,
        authorization: Optional[str] = Header(default=None),
        x_session_id: Optional[str] = Header(default=None),
    ) -> dict[str, Any]:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[len("bearer "):].strip()

        session_id = x_session_id or "default-session"

        result = server.call_tool(
            session_id=session_id,
            token=token,
            tool_name=tool_name,
            arguments=request.arguments,
        )
        if result.ok:
            return result.to_dict()

        # Map structured MCPError -> HTTP status, but keep the same
        # {code, message, retry_after?} body so nothing is lost.
        status_map = {
            "UNAUTHENTICATED": 401,
            "WRITE_NOT_ALLOWED": 403,
            "RATE_LIMIT_EXCEEDED": 429,
            "TOOL_NOT_FOUND": 404,
            "INVALID_ARGUMENTS": 400,
        }
        code = result.error.code if result.error else "UNKNOWN"
        status_code = status_map.get(code, 400)
        raise HTTPException(status_code=status_code, detail=result.error.to_dict() if result.error else {})

    return app


# Module-level app for `uvicorn mcp_starter.http_app:app`
app = create_app()
