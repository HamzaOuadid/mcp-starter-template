"""User story: developer starting a new MCP server.

  "As a developer starting a new MCP server, I can fork this template and
  have auth passthrough working without re-deriving the pattern myself."

Acceptance criteria: cloning the repo and running the example server
enforces per-user scoping out of the box, demonstrated by a test with two
distinct mock users seeing different results from the same tool.

Edge case also covered here (spec section 9): a missing or invalid
identity token must reject the call outright, never fall back to a
default identity.
"""

from __future__ import annotations

from mcp_starter.errors import ErrorCode
from mcp_starter.server import MCPStarterServer


def test_two_users_see_different_results_from_same_tool():
    server = MCPStarterServer()

    alice_result = server.call_tool(session_id="s-alice", token="token-alice", tool_name="search_docs", arguments={"query": ""})
    bob_result = server.call_tool(session_id="s-bob", token="token-bob", tool_name="search_docs", arguments={"query": ""})

    assert alice_result.ok and bob_result.ok
    alice_ids = {doc.doc_id for doc in alice_result.result}
    bob_ids = {doc.doc_id for doc in bob_result.result}

    assert alice_ids != bob_ids
    # Alice (engineering) sees the eng runbook; Bob (sales) does not.
    assert "eng-001" in alice_ids
    assert "eng-001" not in bob_ids
    # Bob (sales) sees the pricing sheet; Alice does not.
    assert "sales-001" in bob_ids
    assert "sales-001" not in alice_ids
    # Both see the company-wide handbook -- passthrough scopes by team,
    # it doesn't hide company-wide docs from anyone.
    assert "all-001" in alice_ids
    assert "all-001" in bob_ids


def test_missing_token_is_rejected_not_defaulted():
    server = MCPStarterServer()

    result = server.call_tool(session_id="s1", token=None, tool_name="search_docs", arguments={"query": ""})

    assert result.ok is False
    assert result.error.code == ErrorCode.UNAUTHENTICATED


def test_invalid_token_is_rejected():
    server = MCPStarterServer()

    result = server.call_tool(session_id="s1", token="totally-made-up-token", tool_name="search_docs", arguments={"query": ""})

    assert result.ok is False
    assert result.error.code == ErrorCode.UNAUTHENTICATED


def test_empty_string_token_is_rejected():
    server = MCPStarterServer()

    result = server.call_tool(session_id="s1", token="", tool_name="search_docs", arguments={"query": ""})

    assert result.ok is False
    assert result.error.code == ErrorCode.UNAUTHENTICATED


def test_unknown_tool_name_does_not_crash():
    server = MCPStarterServer()

    result = server.call_tool(session_id="s1", token="token-alice", tool_name="nonexistent_tool", arguments={})

    assert result.ok is False
    assert result.error.code == ErrorCode.TOOL_NOT_FOUND
