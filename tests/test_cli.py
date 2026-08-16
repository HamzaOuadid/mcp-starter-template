"""Smoke tests for the CLI: `mcp-starter tools` and `mcp-starter demo`
must run end-to-end without error and produce the artifacts they claim
to (an audit log file, non-crashing output covering all four guardrails).
"""

from __future__ import annotations

from typer.testing import CliRunner

from mcp_starter.cli import app

runner = CliRunner()


def test_tools_command_lists_both_example_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["tools"])

    assert result.exit_code == 0
    assert "search_docs" in result.stdout
    assert "create_ticket" in result.stdout
    assert "DISABLED" in result.stdout  # write tool not allowlisted by default


def test_demo_command_runs_full_scenario(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["demo"])

    assert result.exit_code == 0, result.stdout
    assert "auth passthrough" in result.stdout.lower()
    assert "rejected" in result.stdout.lower() or "reject" in result.stdout.lower()
    assert (tmp_path / "demo_audit.jsonl").exists()


def test_demo_command_with_allow_writes_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["demo", "--allow-writes"])

    assert result.exit_code == 0, result.stdout
    assert "create_ticket allowed" in result.stdout
