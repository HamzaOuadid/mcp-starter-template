"""User story: operator, dry-run mode.

  "As an operator, I can turn on dry-run mode and see what a write tool
  would have done."

Acceptance criteria: dry-run mode logs the would-be action (endpoint,
payload) with a `[DRY RUN]` marker and does not call the real downstream
API.

Edge case also covered here (spec section 9): dry-run + write tool
combination must never accidentally execute the real call, even when the
tool is allowlisted.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from mcp_starter.tools.tickets import TicketSystemClient


def test_dry_run_never_invokes_the_real_downstream_client(dry_run_writes_server):
    client = dry_run_writes_server.ticket_client
    client.create = MagicMock(wraps=client.create)  # spy

    result = dry_run_writes_server.call_tool(
        session_id="s1", token="token-alice", tool_name="create_ticket",
        arguments={"title": "Broken build", "body": "CI red on main"},
    )

    assert result.ok is True
    client.create.assert_not_called()
    assert result.result.dry_run is True
    assert result.result.ticket_id.startswith("DRYRUN-")
    assert client.created == []  # nothing landed in the "downstream system"


def test_dry_run_logs_the_would_be_action_with_marker(dry_run_writes_server, caplog):
    with caplog.at_level(logging.INFO, logger="mcp_starter.dryrun"):
        dry_run_writes_server.call_tool(
            session_id="s1", token="token-alice", tool_name="create_ticket",
            arguments={"title": "Broken build", "body": "CI red on main"},
        )

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "[DRY RUN]" in message
    assert "create_ticket" in message
    assert "Broken build" in message


def test_dry_run_off_with_allowlist_actually_calls_downstream(writes_enabled_server):
    client = writes_enabled_server.ticket_client
    client.create = MagicMock(wraps=client.create)

    result = writes_enabled_server.call_tool(
        session_id="s1", token="token-alice", tool_name="create_ticket",
        arguments={"title": "Broken build", "body": "CI red on main"},
    )

    assert result.ok is True
    client.create.assert_called_once_with(title="Broken build", body="CI red on main", requester="alice")
    assert result.result.dry_run is False
    assert not result.result.ticket_id.startswith("DRYRUN-")
    assert len(client.created) == 1


def test_dry_run_plus_write_tool_never_executes_even_when_allowlisted_repeatedly(dry_run_writes_server):
    """Edge case: dry-run + write tool combination must never accidentally
    execute the real call -- exercised repeatedly to guard against a
    regression that only shows up on a later call."""
    client = dry_run_writes_server.ticket_client
    client.create = MagicMock(wraps=client.create)

    for _ in range(3):
        result = dry_run_writes_server.call_tool(
            session_id="repeat-session", token="token-admin", tool_name="create_ticket",
            arguments={"title": "t", "body": "b"},
        )
        assert result.ok is True
        assert result.result.dry_run is True

    client.create.assert_not_called()


def test_read_only_tool_is_unaffected_by_dry_run_flag(dry_run_writes_server):
    """dry_run only changes write-tool behaviour; search_docs (read-only)
    doesn't take a dry_run argument at all and must work unchanged."""
    result = dry_run_writes_server.call_tool(
        session_id="s1", token="token-alice", tool_name="search_docs", arguments={"query": ""}
    )

    assert result.ok is True
