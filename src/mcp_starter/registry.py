"""Tool registry: read/write classification + allowlist enforcement.

Every tool the server knows about -- read-only or write -- is registered
here so a security reviewer has one place to see the full tool surface
and its classification (:meth:`ToolRegistry.describe_all`). Write tools
are always visible in that listing, but a write tool only becomes
*callable* once its name is present in the ``allowed_write_tools``
allowlist supplied at startup. That split is deliberate: hiding a write
tool entirely would mean a caller who requests it gets a generic "unknown
tool" error indistinguishable from a typo, whereas the spec's edge case
requires "a clear denial, not silently no-op" -- which needs the registry
to recognize the tool by name and then explicitly refuse it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .config import ServerConfig


@dataclass(frozen=True)
class ToolSpec:
    """A tool's identity, classification, and handler.

    ``read_only`` here is the code's own declaration -- ``ToolRegistry``
    cross-checks it against ``server.yaml`` at registration time and
    refuses to start up on a mismatch, so config and code can't quietly
    disagree about what a tool is allowed to do.
    """

    name: str
    read_only: bool
    cost_units: int
    description: str
    handler: Callable[..., Any]


class ToolRegistrationError(ValueError):
    """Raised when a tool's declared classification disagrees with config."""


class ToolRegistry:
    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        tool_cfg = self._config.tool_config(spec.name)
        if tool_cfg is None:
            # Fail safe: an undeclared tool is treated as if config said
            # read_only=True was NOT confirmed, so we refuse to register
            # it at all rather than guessing its classification.
            raise ToolRegistrationError(
                f"Tool {spec.name!r} is not declared in server.yaml's `tools:` "
                "section. Every tool must have an explicit read/write "
                "classification in config before it can be registered."
            )
        if tool_cfg.read_only != spec.read_only:
            raise ToolRegistrationError(
                f"Tool {spec.name!r} declares read_only={spec.read_only} in code "
                f"but server.yaml says read_only={tool_cfg.read_only}. Refusing "
                "to register: config and code must agree on classification."
            )
        self._tools[spec.name] = spec

    def get(self, tool_name: str) -> Optional[ToolSpec]:
        return self._tools.get(tool_name)

    def cost_of(self, tool_name: str) -> int:
        spec = self._tools.get(tool_name)
        return spec.cost_units if spec else 0

    def is_write_allowed(self, tool_name: str) -> bool:
        """True if a write tool is both registered and allowlisted.

        Read-only tools are always considered "allowed" here -- this
        check only gates the write path. Defaults to closed: an unknown
        tool name is never allowed.
        """
        spec = self._tools.get(tool_name)
        if spec is None:
            return False
        if spec.read_only:
            return True
        return tool_name in self._config.allowed_write_tools

    def describe_all(self) -> list[dict[str, Any]]:
        """A reviewer-facing listing: every registered tool and its classification.

        This is what backs the "security reviewer can see exactly which
        tools can write" acceptance criteria -- no need to read handler
        source, the registry itself is the source of truth.
        """
        return [
            {
                "name": spec.name,
                "read_only": spec.read_only,
                "cost_units": spec.cost_units,
                "description": spec.description,
                "write_enabled": self.is_write_allowed(spec.name),
            }
            for spec in sorted(self._tools.values(), key=lambda s: s.name)
        ]

    def default_read_only_check(self) -> bool:
        """True iff every currently-registered write tool is NOT allowlisted.

        Convenience used by the "tools default to read-only unless
        explicitly enabled" test: asserts the *default* config (empty
        allowlist) leaves no write tool callable.
        """
        return all(
            self.is_write_allowed(spec.name) is False
            for spec in self._tools.values()
            if not spec.read_only
        )
