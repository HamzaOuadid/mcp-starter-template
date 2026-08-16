from __future__ import annotations

import pytest

from mcp_starter.config import RateLimitConfig, ServerConfig, ToolConfig
from mcp_starter.server import MCPStarterServer


def make_config(
    dry_run: bool = True,
    allowed_write_tools: list[str] | None = None,
    calls_per_min: int = 5,
    cost_per_session: int = 10,
    window_seconds: int = 60,
) -> ServerConfig:
    return ServerConfig(
        dry_run=dry_run,
        allowed_write_tools=allowed_write_tools or [],
        rate_limit=RateLimitConfig(
            calls_per_min=calls_per_min,
            cost_per_session=cost_per_session,
            window_seconds=window_seconds,
        ),
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
    """Server with create_ticket allowlisted, dry_run on, and a generous
    rate budget -- some dry-run tests make several calls in one session
    purely to re-verify the dry-run guarantee, not to exercise limits."""
    return MCPStarterServer(
        config=make_config(
            allowed_write_tools=["create_ticket"], dry_run=True, calls_per_min=100, cost_per_session=100
        )
    )
