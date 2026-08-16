"""Smoke tests for the real MCP stdio server built on the official SDK
(mcp_app.py). These exercise the FastMCP tool registration and in-process
call path (not a full stdio subprocess round-trip) to confirm the server
that a real MCP client would talk to actually wires the same guardrails
as the transport-agnostic core.
"""

from __future__ import annotations

import pytest

from mcp_starter.config import RateLimitConfig, ServerConfig, ToolConfig
from mcp_starter.mcp_app import build_mcp_server


def _structured(raw):
    """FastMCP's call_tool returns (content_blocks, structured_dict) when
    the tool's return type is annotated as a dict; unwrap to the dict."""
    return raw[1] if isinstance(raw, tuple) else raw


def _config() -> ServerConfig:
    return ServerConfig(
        dry_run=True,
        allowed_write_tools=[],
        rate_limit=RateLimitConfig(calls_per_min=10, cost_per_session=50),
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description=""),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description=""),
        },
    )


@pytest.mark.asyncio
async def test_stdio_server_lists_all_three_tools():
    server = build_mcp_server(config=_config())
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == {"search_docs", "create_ticket", "list_tools"}


@pytest.mark.asyncio
async def test_stdio_server_two_users_differ():
    server = build_mcp_server(config=_config())

    alice = _structured(await server.call_tool("search_docs", {"query": "", "token": "token-alice", "session_id": "s-alice"}))
    bob = _structured(await server.call_tool("search_docs", {"query": "", "token": "token-bob", "session_id": "s-bob"}))

    assert alice["ok"] is True and bob["ok"] is True
    alice_ids = {d["doc_id"] for d in alice["result"]}
    bob_ids = {d["doc_id"] for d in bob["result"]}
    assert alice_ids != bob_ids


@pytest.mark.asyncio
async def test_stdio_server_write_tool_denied_by_default():
    server = build_mcp_server(config=_config())

    result = _structured(await server.call_tool(
        "create_ticket", {"title": "t", "body": "b", "token": "token-alice", "session_id": "s1"}
    ))

    assert result["ok"] is False
    assert result["error"]["code"] == "WRITE_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_stdio_server_missing_token_rejected():
    server = build_mcp_server(config=_config())

    result = _structured(await server.call_tool("search_docs", {"query": "", "token": "", "session_id": "s1"}))

    assert result["ok"] is False
    assert result["error"]["code"] == "UNAUTHENTICATED"
