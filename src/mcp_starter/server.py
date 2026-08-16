"""Orchestrates auth passthrough and the tool registry's allowlist gate.

``MCPStarterServer.call_tool`` is the single choke point every tool call
passes through, transport-agnostic on purpose. Its signature is stable
from the first commit; this one layers the write-tool allowlist on top of
auth passthrough. Dry-run, rate limiting, and audit logging are layered
in by subsequent commits.

Dispatch order so far:
  1. authenticate the caller (missing/invalid token -> ``UNAUTHENTICATED``)
  2. resolve the tool (unknown tool -> ``TOOL_NOT_FOUND``)
  3. write-allowlist check (disallowed write -> ``WRITE_NOT_ALLOWED``)
  4. execute, scoped to the resolved ``User``
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Optional

from .auth import AuthMiddleware
from .config import ServerConfig
from .errors import ErrorCode, MCPError
from .identity import MockIdentityProvider
from .registry import ToolRegistry, ToolSpec
from .tools import docs as docs_tool
from .tools import tickets as tickets_tool


@dataclass
class ToolCallResult:
    ok: bool
    result: Any = None
    error: Optional[MCPError] = None

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, "result": self.result}
        return {"ok": False, "error": self.error.to_dict() if self.error else None}


class MCPStarterServer:
    def __init__(
        self,
        config: Optional[ServerConfig] = None,
        identity_provider: Optional[MockIdentityProvider] = None,
        ticket_client: Optional[tickets_tool.TicketSystemClient] = None,
    ) -> None:
        self.config = config or ServerConfig.default()
        self.identity_provider = identity_provider or MockIdentityProvider()
        self.auth = AuthMiddleware(self.identity_provider)
        self.registry = ToolRegistry(self.config)
        self.ticket_client = ticket_client or tickets_tool.TicketSystemClient()

        self._register_default_tools()

    def _register_default_tools(self) -> None:
        search_cfg = self.config.tool_config("search_docs")
        self.registry.register(
            ToolSpec(
                name="search_docs",
                read_only=True,
                cost_units=search_cfg.cost_units if search_cfg else 1,
                description=search_cfg.description if search_cfg else "",
                handler=docs_tool.search_docs,
            )
        )

        ticket_cfg = self.config.tool_config("create_ticket")
        # Bind the downstream client at registration time so dispatch can
        # call every write tool with the same (user, **arguments) shape.
        bound_create_ticket = functools.partial(tickets_tool.create_ticket, client=self.ticket_client)
        self.registry.register(
            ToolSpec(
                name="create_ticket",
                read_only=False,
                cost_units=ticket_cfg.cost_units if ticket_cfg else 5,
                description=ticket_cfg.description if ticket_cfg else "",
                handler=bound_create_ticket,
            )
        )

    def list_tools(self) -> list[dict[str, Any]]:
        return self.registry.describe_all()

    def call_tool(
        self,
        session_id: str,
        token: Optional[str],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        try:
            user = self.auth.authenticate(token)
        except MCPError as exc:
            return ToolCallResult(ok=False, error=exc)

        spec = self.registry.get(tool_name)
        if spec is None:
            return ToolCallResult(
                ok=False,
                error=MCPError(code=ErrorCode.TOOL_NOT_FOUND, message=f"Unknown tool {tool_name!r}."),
            )

        if not spec.read_only and not self.registry.is_write_allowed(tool_name):
            return ToolCallResult(
                ok=False,
                error=MCPError(
                    code=ErrorCode.WRITE_NOT_ALLOWED,
                    message=(
                        f"Tool {tool_name!r} is a write tool and is not in "
                        "allowed_write_tools. Add it to server.yaml's "
                        "allowlist to enable it."
                    ),
                ),
            )

        result = spec.handler(user=user, **arguments)
        return ToolCallResult(ok=True, result=result)
