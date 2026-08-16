from __future__ import annotations

import pytest

from mcp_starter.config import ServerConfig, ToolConfig
from mcp_starter.server import MCPStarterServer


def make_config(allowed_write_tools: list[str] | None = None) -> ServerConfig:
    return ServerConfig(
        allowed_write_tools=allowed_write_tools or [],
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description="Search internal docs."),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description="Create a ticket."),
        },
    )


@pytest.fixture
def default_server() -> MCPStarterServer:
    """Safe-by-default server: no write tools allowlisted."""
    return MCPStarterServer(config=make_config())


@pytest.fixture
def writes_enabled_server() -> MCPStarterServer:
    """Server with create_ticket allowlisted."""
    return MCPStarterServer(config=make_config(allowed_write_tools=["create_ticket"]))
