"""User story: operator, rate/spend cap.

  "As an operator, I can cap spend/rate per session and get a clear error
  when a client exceeds it."

Acceptance criteria: exceeding the configured cap returns a structured
MCP error, not a silent failure or crash.

Edge case also covered here (spec section 9): once the limit is hit
mid-session, subsequent calls in that session must keep being rejected
until the window resets -- not just the one call that tripped it.
"""

from __future__ import annotations

import pytest

from mcp_starter.config import RateLimitConfig, ServerConfig, ToolConfig
from mcp_starter.errors import ErrorCode, MCPError
from mcp_starter.limiter import SessionLimiter
from mcp_starter.server import MCPStarterServer


def make_config(calls_per_min: int = 5, cost_per_session: int = 10) -> ServerConfig:
    return ServerConfig(
        dry_run=True,
        allowed_write_tools=[],
        rate_limit=RateLimitConfig(calls_per_min=calls_per_min, cost_per_session=cost_per_session),
        tools={
            "search_docs": ToolConfig(read_only=True, cost_units=1, description="Search internal docs."),
            "create_ticket": ToolConfig(read_only=False, cost_units=5, description="Create a ticket."),
        },
    )


def test_burst_of_n_plus_one_rejects_the_last_call():
    limiter = SessionLimiter(RateLimitConfig(calls_per_min=3, cost_per_session=100, window_seconds=60))

    for _ in range(3):
        limiter.check_and_consume("session-a", cost_units=1)  # should not raise

    with pytest.raises(MCPError) as excinfo:
        limiter.check_and_consume("session-a", cost_units=1)

    assert excinfo.value.code == ErrorCode.RATE_LIMIT_EXCEEDED
    assert excinfo.value.retry_after is not None


def test_calls_keep_being_rejected_until_window_resets():
    """Not just the call that tripped it -- every call after, within the
    same window, must also be rejected."""
    fake_time = [0.0]
    limiter = SessionLimiter(
        RateLimitConfig(calls_per_min=2, cost_per_session=100, window_seconds=60),
        clock=lambda: fake_time[0],
    )

    limiter.check_and_consume("s", cost_units=1)
    limiter.check_and_consume("s", cost_units=1)

    for _ in range(5):
        fake_time[0] += 1  # time passes, but well within the 60s window
        with pytest.raises(MCPError) as excinfo:
            limiter.check_and_consume("s", cost_units=1)
        assert excinfo.value.code == ErrorCode.RATE_LIMIT_EXCEEDED

    # Once the window fully elapses, the session gets a fresh budget.
    fake_time[0] += 60
    limiter.check_and_consume("s", cost_units=1)  # should not raise


def test_cost_cap_is_enforced_independent_of_call_count():
    limiter = SessionLimiter(RateLimitConfig(calls_per_min=100, cost_per_session=10, window_seconds=60))

    limiter.check_and_consume("s", cost_units=6)
    with pytest.raises(MCPError) as excinfo:
        limiter.check_and_consume("s", cost_units=6)  # 6+6=12 > 10

    assert excinfo.value.code == ErrorCode.RATE_LIMIT_EXCEEDED


def test_sessions_are_isolated_from_each_other():
    limiter = SessionLimiter(RateLimitConfig(calls_per_min=1, cost_per_session=100, window_seconds=60))

    limiter.check_and_consume("session-a", cost_units=1)
    limiter.check_and_consume("session-b", cost_units=1)  # own independent budget, should not raise


def test_rate_limit_via_server_returns_structured_error():
    """Integration: the server-level dispatch surfaces RATE_LIMIT_EXCEEDED,
    not a crash, once a session's cap is exceeded, and keeps rejecting."""
    server_config = make_config(calls_per_min=5, cost_per_session=50)
    server = MCPStarterServer(config=server_config)
    limit = server.config.rate_limit.calls_per_min
    session_id = "burst-session"

    results = [
        server.call_tool(session_id=session_id, token="token-alice", tool_name="search_docs", arguments={"query": ""})
        for _ in range(limit + 1)
    ]

    assert all(r.ok for r in results[:limit])
    assert results[limit].ok is False
    assert results[limit].error.code == ErrorCode.RATE_LIMIT_EXCEEDED

    # And the call right after that is *also* still rejected, not just
    # the one that tripped it.
    follow_up = server.call_tool(session_id=session_id, token="token-alice", tool_name="search_docs", arguments={"query": ""})
    assert follow_up.ok is False
    assert follow_up.error.code == ErrorCode.RATE_LIMIT_EXCEEDED


def test_denied_write_does_not_consume_rate_budget():
    """A write tool denied by the allowlist shouldn't itself burn the
    session's rate budget -- only checks that actually proceed to
    execution should count."""
    server_config = make_config(calls_per_min=2, cost_per_session=50)  # create_ticket not allowlisted
    server = MCPStarterServer(config=server_config)

    for _ in range(5):
        result = server.call_tool(
            session_id="s1", token="token-alice", tool_name="create_ticket", arguments={"title": "t", "body": "b"}
        )
        assert result.ok is False
        assert result.error.code == ErrorCode.WRITE_NOT_ALLOWED

    # Rate budget is untouched -- a read call still succeeds.
    result = server.call_tool(session_id="s1", token="token-alice", tool_name="search_docs", arguments={"query": ""})
    assert result.ok is True
