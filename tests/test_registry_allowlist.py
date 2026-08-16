"""User story: security reviewer.

  "As a security reviewer, I can see exactly which tools can write and
  confirm nothing writes by default."

Acceptance criteria: a single config file lists every tool's read/write
classification; a test asserts all tools default to read-only unless
explicitly enabled.

Edge case also covered here (spec section 9): a write tool requested but
not in the allowlist must return a clear denial, not silently no-op.
"""

from __future__ import annotations

import pytest

from mcp_starter.config import ServerConfig, ToolConfig
from mcp_starter.errors import ErrorCode
from mcp_starter.registry import ToolRegistrationError, ToolRegistry, ToolSpec


def make_config() -> ServerConfig:
    return ServerConfig(
        allowed_write_tools=[],
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description="Search internal docs."),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description="Create a ticket."),
        },
    )


def test_registry_describes_every_tool_classification(default_server):
    described = {entry["name"]: entry for entry in default_server.list_tools()}

    assert described["search_docs"]["read_only"] is True
    assert described["create_ticket"]["read_only"] is False


def test_all_write_tools_default_to_disabled(default_server):
    """With an empty allowlist, no write tool should be callable."""
    assert default_server.registry.default_read_only_check() is True

    described = {entry["name"]: entry for entry in default_server.list_tools()}
    assert described["create_ticket"]["write_enabled"] is False
    assert described["search_docs"]["write_enabled"] is True  # read-only tools are always "allowed"


def test_write_tool_not_in_allowlist_is_denied(default_server):
    result = default_server.call_tool(
        session_id="s1", token="token-alice", tool_name="create_ticket",
        arguments={"title": "x", "body": "y"},
    )

    assert result.ok is False
    assert result.error.code == ErrorCode.WRITE_NOT_ALLOWED


def test_write_tool_in_allowlist_becomes_enabled(writes_enabled_server):
    described = {entry["name"]: entry for entry in writes_enabled_server.list_tools()}
    assert described["create_ticket"]["write_enabled"] is True

    result = writes_enabled_server.call_tool(
        session_id="s1", token="token-alice", tool_name="create_ticket",
        arguments={"title": "Broken build", "body": "CI red on main"},
    )
    assert result.ok is True
    assert result.result.ticket_id.startswith("TKT-")


def test_registration_refuses_undeclared_tool():
    config = make_config()
    registry = ToolRegistry(config)

    with pytest.raises(ToolRegistrationError):
        registry.register(
            ToolSpec(name="delete_everything", read_only=False, cost_units=1, description="", handler=lambda: None)
        )


def test_registration_refuses_classification_mismatch():
    """Code says read_only=False but config says read_only=True: refuse."""
    config = make_config()
    registry = ToolRegistry(config)

    with pytest.raises(ToolRegistrationError):
        registry.register(
            ToolSpec(name="search_docs", read_only=False, cost_units=1, description="", handler=lambda: None)
        )


def test_unknown_tool_call_is_tool_not_found(default_server):
    result = default_server.call_tool(session_id="s1", token="token-alice", tool_name="nonexistent_tool", arguments={})

    assert result.ok is False
    assert result.error.code == ErrorCode.TOOL_NOT_FOUND
