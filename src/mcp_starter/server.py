"""``MCPStarterServer`` -- the transport-agnostic dispatch core.

This is the single choke point every tool call passes through, regardless
of which transport (stdio, HTTP, ...) eventually fronts it. Right now it
only knows how to do one thing -- authenticate the caller and route to a
tool by name -- but ``call_tool``'s signature (``session_id, token,
tool_name, arguments``) is the stable contract the write-tool allowlist,
dry-run, rate limiting, and audit logging guardrails all get layered onto
in subsequent commits, so it's fixed from the start rather than churned.

Dispatch order so far:
  1. authenticate the caller (missing/invalid token -> ``UNAUTHENTICATED``)
  2. look up the tool by name (unknown tool -> ``TOOL_NOT_FOUND``)
  3. execute, scoped to the resolved ``User`` -- never a shared credential
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .auth import AuthMiddleware
from .errors import ErrorCode, MCPError
from .identity import MockIdentityProvider
from .tools import docs as docs_tool


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
    def __init__(self, identity_provider: Optional[MockIdentityProvider] = None) -> None:
        self.identity_provider = identity_provider or MockIdentityProvider()
        self.auth = AuthMiddleware(self.identity_provider)
        # name -> handler. A real registry with read/write classification
        # and allowlist enforcement lands in the next commit; for now this
        # is just enough to route search_docs by name.
        self._tools: dict[str, Callable[..., Any]] = {
            "search_docs": docs_tool.search_docs,
        }

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

        handler = self._tools.get(tool_name)
        if handler is None:
            return ToolCallResult(
                ok=False,
                error=MCPError(code=ErrorCode.TOOL_NOT_FOUND, message=f"Unknown tool {tool_name!r}."),
            )

        result = handler(user=user, **arguments)
        return ToolCallResult(ok=True, result=result)
