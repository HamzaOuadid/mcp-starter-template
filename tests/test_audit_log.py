"""Definition of done: "a reviewer unfamiliar with the code can read the
audit log and reconstruct what happened in a test session."

These tests drive a small session through the server and then verify the
JSONL file and SQLite table both contain enough structure to answer:
who called what, was it a write, was it allowed, was it a dry-run, how
long did it take. Bundled with the rate-limiter commit (spec milestone
M3 groups "rate limiter" and "structured audit logging" together, and
the limiter's session_id is what audit records are keyed by).
"""

from __future__ import annotations

import json

from mcp_starter.audit import AuditLogger
from mcp_starter.config import RateLimitConfig, ServerConfig, ToolConfig
from mcp_starter.server import MCPStarterServer


def _config() -> ServerConfig:
    return ServerConfig(
        dry_run=True,
        allowed_write_tools=["create_ticket"],
        rate_limit=RateLimitConfig(calls_per_min=10, cost_per_session=50),
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description=""),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description=""),
        },
    )


def test_audit_jsonl_reconstructs_a_session(tmp_path):
    jsonl_path = tmp_path / "audit.jsonl"
    audit_logger = AuditLogger(jsonl_path=jsonl_path)
    server = MCPStarterServer(config=_config(), audit_logger=audit_logger)

    server.call_tool(session_id="review-session", token="token-alice", tool_name="search_docs", arguments={"query": ""})
    server.call_tool(session_id="review-session", token="token-alice", tool_name="create_ticket", arguments={"title": "t", "body": "b"})
    server.call_tool(session_id="review-session", token=None, tool_name="search_docs", arguments={"query": ""})

    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    records = [json.loads(line) for line in lines]

    read_record = records[0]
    assert read_record["tool_name"] == "search_docs"
    assert read_record["read_or_write"] == "read"
    assert read_record["allowed"] is True
    assert read_record["user_id"] == "alice"

    write_record = records[1]
    assert write_record["tool_name"] == "create_ticket"
    assert write_record["read_or_write"] == "write"
    assert write_record["dry_run"] is True
    assert write_record["allowed"] is True
    assert "[DRY RUN]" in write_record["detail"]

    denied_record = records[2]
    assert denied_record["allowed"] is False
    assert denied_record["error_code"] == "UNAUTHENTICATED"

    # Every record has a latency measurement -- part of reconstructing
    # "what happened", not just "what was allowed".
    assert all(r["latency_ms"] >= 0 for r in records)


def test_audit_sqlite_table_matches_data_model(tmp_path):
    sqlite_path = tmp_path / "audit.db"
    audit_logger = AuditLogger(sqlite_path=sqlite_path)
    server = MCPStarterServer(config=_config(), audit_logger=audit_logger)

    server.call_tool(session_id="s1", token="token-bob", tool_name="search_docs", arguments={"query": ""})

    rows = audit_logger.query(session_id="s1")
    assert len(rows) == 1
    row = rows[0]
    # Data model: (timestamp, session_id, user_id, tool_name, read_or_write, dry_run, allowed, latency_ms)
    assert row["session_id"] == "s1"
    assert row["user_id"] == "bob"
    assert row["tool_name"] == "search_docs"
    assert row["read_or_write"] == "read"
    assert row["dry_run"] == 0
    assert row["allowed"] == 1
    assert row["latency_ms"] >= 0


def test_query_filters_by_session(tmp_path):
    audit_logger = AuditLogger(sqlite_path=tmp_path / "audit.db")
    server = MCPStarterServer(config=_config(), audit_logger=audit_logger)

    server.call_tool(session_id="sess-1", token="token-alice", tool_name="search_docs", arguments={"query": ""})
    server.call_tool(session_id="sess-2", token="token-bob", tool_name="search_docs", arguments={"query": ""})

    assert len(audit_logger.query(session_id="sess-1")) == 1
    assert len(audit_logger.query(session_id="sess-2")) == 1
    assert len(audit_logger.query()) == 2


def test_rate_limit_denial_is_also_audited(tmp_path):
    """The audit trail must capture denials too, not just successes --
    otherwise a reviewer can't reconstruct why a session's calls stopped
    succeeding partway through."""
    cfg = ServerConfig(
        dry_run=True,
        allowed_write_tools=[],
        rate_limit=RateLimitConfig(calls_per_min=1, cost_per_session=50),
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description=""),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description=""),
        },
    )
    audit_logger = AuditLogger(sqlite_path=tmp_path / "audit.db")
    server = MCPStarterServer(config=cfg, audit_logger=audit_logger)

    server.call_tool(session_id="s1", token="token-alice", tool_name="search_docs", arguments={"query": ""})
    server.call_tool(session_id="s1", token="token-alice", tool_name="search_docs", arguments={"query": ""})

    rows = audit_logger.query(session_id="s1")
    assert len(rows) == 2
    assert rows[0]["allowed"] == 1
    assert rows[1]["allowed"] == 0
    assert rows[1]["error_code"] == "RATE_LIMIT_EXCEEDED"
