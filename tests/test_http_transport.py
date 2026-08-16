"""HTTP transport variant: token comes from the Authorization header,
session from X-Session-Id -- exercising the same guardrails through a
real (if local) HTTP request/response cycle instead of calling
MCPStarterServer directly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_starter.config import RateLimitConfig, ServerConfig, ToolConfig
from mcp_starter.http_app import create_app
from mcp_starter.server import MCPStarterServer


def _client(dry_run=True, allowed_write_tools=None, calls_per_min=10) -> TestClient:
    cfg = ServerConfig(
        dry_run=dry_run,
        allowed_write_tools=allowed_write_tools or [],
        rate_limit=RateLimitConfig(calls_per_min=calls_per_min, cost_per_session=50),
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description=""),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description=""),
        },
    )
    server = MCPStarterServer(config=cfg)
    return TestClient(create_app(server=server))


def test_list_tools_endpoint():
    client = _client()
    resp = client.get("/tools")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert names == {"search_docs", "create_ticket"}


def test_auth_header_passthrough_two_users_differ():
    client = _client()

    alice = client.post(
        "/tools/search_docs/call",
        json={"arguments": {"query": ""}},
        headers={"Authorization": "Bearer token-alice", "X-Session-Id": "s-alice"},
    )
    bob = client.post(
        "/tools/search_docs/call",
        json={"arguments": {"query": ""}},
        headers={"Authorization": "Bearer token-bob", "X-Session-Id": "s-bob"},
    )

    assert alice.status_code == 200 and bob.status_code == 200
    alice_ids = {d["doc_id"] for d in alice.json()["result"]}
    bob_ids = {d["doc_id"] for d in bob.json()["result"]}
    assert alice_ids != bob_ids


def test_missing_auth_header_returns_401():
    client = _client()
    resp = client.post("/tools/search_docs/call", json={"arguments": {"query": ""}})

    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "UNAUTHENTICATED"


def test_write_not_allowed_returns_403():
    client = _client()
    resp = client.post(
        "/tools/create_ticket/call",
        json={"arguments": {"title": "t", "body": "b"}},
        headers={"Authorization": "Bearer token-alice", "X-Session-Id": "s1"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "WRITE_NOT_ALLOWED"


def test_rate_limit_returns_429():
    client = _client(calls_per_min=1)
    headers = {"Authorization": "Bearer token-alice", "X-Session-Id": "s1"}

    first = client.post("/tools/search_docs/call", json={"arguments": {"query": ""}}, headers=headers)
    second = client.post("/tools/search_docs/call", json={"arguments": {"query": ""}}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_unknown_tool_returns_404():
    client = _client()
    resp = client.post(
        "/tools/delete_everything/call",
        json={"arguments": {}},
        headers={"Authorization": "Bearer token-alice", "X-Session-Id": "s1"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "TOOL_NOT_FOUND"
