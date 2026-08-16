"""Loads and validates ``server.yaml``.

This is the "single config file [that] lists every tool's read/write
classification" from the security-reviewer acceptance criteria:
:class:`ToolConfig` entries are cross-checked against each tool's own
code-declared ``read_only`` flag at registration time (see
``registry.py``), so the config and the code can never silently drift
apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ToolConfig(BaseModel):
    read_only: bool
    # Not consumed yet (the rate/spend limiter lands in a later commit),
    # but every tool declares a cost from day one so the config schema
    # doesn't need to churn once the limiter starts reading it.
    cost_units: int = 1
    description: str = ""


class ServerConfig(BaseModel):
    allowed_write_tools: list[str] = Field(default_factory=list)
    tools: dict[str, ToolConfig] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ServerConfig":
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    @classmethod
    def default(cls) -> "ServerConfig":
        """A safe-by-default config for callers that don't load a YAML file.

        No write tools allowlisted -- matches the fail-safe posture the
        spec calls for even before any config file is read.
        """
        return cls(
            allowed_write_tools=[],
            tools={
                "search_docs": ToolConfig(read_only=True, cost_units=1, description="Search internal docs."),
                "create_ticket": ToolConfig(read_only=False, cost_units=5, description="Create a ticket."),
            },
        )

    def tool_config(self, tool_name: str) -> Optional[ToolConfig]:
        return self.tools.get(tool_name)
