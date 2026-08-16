from __future__ import annotations

import pytest

from mcp_starter.config import ServerConfig, ToolConfig
from mcp_starter.server import MCPStarterServer


def make_config(dry_run: bool = True, allowed_write_tools: list[str] | None = None) -> ServerConfig:
    return ServerConfig(
        dry_run=dry_run,
        allowed_write_tools=allowed_write_tools or [],
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description="Search internal docs."),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description="Create a ticket."),
        },
    )


@pytest.fixture
def default_server() -> MCPStarterServer:
    """Safe-by-default server: dry_run on, no write tools allowlisted."""
    return MCPStarterServer(config=make_config())


@pytest.fixture
def writes_enabled_server() -> MCPStarterServer:
    """Server with create_ticket allowlisted AND dry_run off: writes really land.

    (dry_run=False here so the pre-existing allowlist test, written before
    dry-run mode existed, still exercises a real downstream write.)
    """
    return MCPStarterServer(config=make_config(allowed_write_tools=["create_ticket"], dry_run=False))


@pytest.fixture
def dry_run_writes_server() -> MCPStarterServer:
    """Server with create_ticket allowlisted but dry_run on (the shipped default posture)."""
    return MCPStarterServer(config=make_config(allowed_write_tools=["create_ticket"], dry_run=True))
