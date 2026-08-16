"""Command-line entry point: ``mcp-starter``.

Commands:
  tools         -- print the tool registry (name, read/write, allowlisted?)
  demo          -- run the worked "what this prevents" scenario end-to-end
  serve-http    -- run the FastAPI HTTP transport
  serve-stdio   -- run the real MCP stdio server (for MCP clients)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .audit import AuditLogger
from .config import ServerConfig
from .server import MCPStarterServer

app = typer.Typer(add_completion=False, help="Security-first MCP server starter template.")

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent.parent / "server.yaml"


def _load_config(config_path: Optional[Path]) -> ServerConfig:
    path = config_path or DEFAULT_CONFIG
    if path.exists():
        return ServerConfig.from_yaml(path)
    return ServerConfig.default()


@app.command()
def tools(config: Optional[Path] = typer.Option(None, help="Path to server.yaml")) -> None:
    """List every registered tool and its read/write classification."""
    server = MCPStarterServer(config=_load_config(config))
    for entry in server.list_tools():
        classification = "read-only" if entry["read_only"] else "WRITE"
        enabled = "enabled" if entry["write_enabled"] else "DISABLED (not allowlisted)"
        marker = classification if entry["read_only"] else f"{classification} [{enabled}]"
        typer.echo(f"  {entry['name']:<16} {marker:<32} cost={entry['cost_units']:<3} {entry['description']}")


@app.command()
def demo(
    config: Optional[Path] = typer.Option(None, help="Path to server.yaml"),
    allow_writes: bool = typer.Option(False, "--allow-writes", help="Allowlist create_ticket for this demo run"),
) -> None:
    """Run the worked two-user permission-boundary scenario end to end.

    Demonstrates, in order: (1) two mock users seeing different
    search_docs results, (2) a write tool denied by default, (3) dry-run
    mode logging without executing, (4) rate limiting a burst of calls,
    all backed by the real audit log.
    """
    cfg = _load_config(config)
    if allow_writes:
        cfg = cfg.model_copy(update={"allowed_write_tools": ["create_ticket"]})

    audit_path = Path("demo_audit.jsonl")
    if audit_path.exists():
        audit_path.unlink()
    audit_logger = AuditLogger(jsonl_path=audit_path)
    server = MCPStarterServer(config=cfg, audit_logger=audit_logger)

    typer.echo("=== 1. Per-user auth passthrough: same tool, same query, different results ===")
    for token, label in [("token-alice", "alice (engineering)"), ("token-bob", "bob (sales)")]:
        result = server.call_tool(session_id="demo-session", token=token, tool_name="search_docs", arguments={"query": ""})
        doc_ids = [d.doc_id for d in result.result] if result.ok else None
        typer.echo(f"  {label}: sees docs {doc_ids}")

    typer.echo("\n=== 2. Missing/invalid identity is rejected, not defaulted ===")
    result = server.call_tool(session_id="demo-session", token=None, tool_name="search_docs", arguments={"query": ""})
    typer.echo(f"  token=None -> ok={result.ok} error={result.error.to_dict() if result.error else None}")

    typer.echo("\n=== 3. Write tool default posture ===")
    result = server.call_tool(
        session_id="demo-session-2", token="token-alice", tool_name="create_ticket",
        arguments={"title": "Broken build", "body": "CI red on main"},
    )
    if result.ok:
        typer.echo(f"  create_ticket allowed (allowlisted): {result.result}")
    else:
        typer.echo(f"  create_ticket denied: {result.error.to_dict()}")

    typer.echo("\n=== 4. Rate limit: burst of calls past the cap ===")
    limit = cfg.rate_limit.calls_per_min
    burst_session = "demo-burst-session"
    for i in range(limit + 1):
        result = server.call_tool(session_id=burst_session, token="token-alice", tool_name="search_docs", arguments={"query": ""})
        status = "allowed" if result.ok else f"DENIED ({result.error.code})"
        typer.echo(f"  call {i + 1}/{limit + 1}: {status}")

    typer.echo(f"\n=== Audit log written to {audit_path.resolve()} ===")
    for record in audit_logger.records[-3:]:
        typer.echo(f"  {record.to_json()}")


@app.command("serve-http")
def serve_http(
    config: Optional[Path] = typer.Option(None, help="Path to server.yaml"),
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the HTTP transport variant (FastAPI + uvicorn)."""
    import uvicorn

    from .http_app import create_app

    fastapi_app = create_app(config_path=str(config) if config else None)
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command("serve-stdio")
def serve_stdio(config: Optional[Path] = typer.Option(None, help="Path to server.yaml")) -> None:
    """Run the real MCP stdio server (for MCP-compatible clients)."""
    from .mcp_app import build_mcp_server

    mcp_server = build_mcp_server(config_path=str(config) if config else None)
    mcp_server.run()


if __name__ == "__main__":
    app()
