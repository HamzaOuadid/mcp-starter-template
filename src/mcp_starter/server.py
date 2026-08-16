"""Orchestrates auth, the allowlist gate, dry-run, rate limiting, and audit.

``MCPStarterServer.call_tool`` is the single choke point every tool call
passes through, transport-agnostic on purpose: the stdio MCP adapter and
the HTTP/FastAPI adapter (added in a later commit) are both thin wrappers
around this class, so the guardrail logic is implemented and tested
exactly once.

Dispatch order for every call:
  1. resolve the tool (unknown tool -> ``TOOL_NOT_FOUND``)
  2. authenticate the caller (missing/invalid token -> ``UNAUTHENTICATED``)
  3. write-allowlist check (disallowed write -> ``WRITE_NOT_ALLOWED``)
  4. rate/spend check (over budget -> ``RATE_LIMIT_EXCEEDED``)
  5. execute (dry-run substituted in for write tools when configured)
  6. audit log, always -- allowed or denied, real or dry-run
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Any, Optional

from . import audit as audit_module
from .audit import AuditLogger, AuditRecord
from .auth import AuthMiddleware
from .config import ServerConfig
from .dryrun import format_dry_run_detail
from .errors import ErrorCode, MCPError
from .identity import MockIdentityProvider
from .limiter import SessionLimiter
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
        audit_logger: Optional[AuditLogger] = None,
        ticket_client: Optional[tickets_tool.TicketSystemClient] = None,
    ) -> None:
        self.config = config or ServerConfig.default()
        self.identity_provider = identity_provider or MockIdentityProvider()
        self.auth = AuthMiddleware(self.identity_provider)
        self.registry = ToolRegistry(self.config)
        self.audit = audit_logger or AuditLogger()
        self.ticket_client = ticket_client or tickets_tool.TicketSystemClient()
        self.limiter = SessionLimiter(self.config.rate_limit)

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

    def session_usage(self, session_id: str) -> dict[str, int]:
        return self.limiter.usage(session_id)

    def call_tool(
        self,
        session_id: str,
        token: Optional[str],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        start = time.monotonic()
        spec = self.registry.get(tool_name)
        read_or_write = "unknown"
        if spec is not None:
            read_or_write = "read" if spec.read_only else "write"

        def deny(user_id: str, error: MCPError, dry_run: bool = False) -> ToolCallResult:
            latency_ms = (time.monotonic() - start) * 1000
            self.audit.log(
                AuditRecord(
                    timestamp=audit_module.now(),
                    session_id=session_id,
                    user_id=user_id,
                    tool_name=tool_name,
                    read_or_write=read_or_write,
                    dry_run=dry_run,
                    allowed=False,
                    latency_ms=latency_ms,
                    error_code=error.code,
                    detail=error.message,
                )
            )
            return ToolCallResult(ok=False, error=error)

        try:
            user = self.auth.authenticate(token)
        except MCPError as exc:
            return deny("unknown", exc)

        if spec is None:
            return deny(
                user.user_id,
                MCPError(code=ErrorCode.TOOL_NOT_FOUND, message=f"Unknown tool {tool_name!r}."),
            )

        if not spec.read_only and not self.registry.is_write_allowed(tool_name):
            return deny(
                user.user_id,
                MCPError(
                    code=ErrorCode.WRITE_NOT_ALLOWED,
                    message=(
                        f"Tool {tool_name!r} is a write tool and is not in "
                        "allowed_write_tools. Add it to server.yaml's "
                        "allowlist to enable it."
                    ),
                ),
            )

        try:
            self.limiter.check_and_consume(session_id, spec.cost_units)
        except MCPError as exc:
            return deny(user.user_id, exc)

        dry_run_active = bool(self.config.dry_run) and not spec.read_only

        if spec.read_only:
            result = spec.handler(user=user, **arguments)
        else:
            result = spec.handler(user=user, dry_run=dry_run_active, **arguments)

        detail = format_dry_run_detail(tool_name, arguments) if dry_run_active else ""
        latency_ms = (time.monotonic() - start) * 1000
        self.audit.log(
            AuditRecord(
                timestamp=audit_module.now(),
                session_id=session_id,
                user_id=user.user_id,
                tool_name=tool_name,
                read_or_write=read_or_write,
                dry_run=dry_run_active,
                allowed=True,
                latency_ms=latency_ms,
                error_code=None,
                detail=detail,
            )
        )
        return ToolCallResult(ok=True, result=result)
