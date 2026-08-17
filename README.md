# mcp-starter-template

A reference MCP server scaffold encoding security patterns most public MCP
examples skip: **per-user auth passthrough** (never a shared service
account), **read-only tools by default** with explicit write opt-in, a
**dry-run mode** for write tools, and a **per-session spend/rate cap** with
structured denials instead of silent no-ops or crashes. Every guardrail is
backed by an automated test, not just a docstring.

Built as a portfolio piece after auditing and stripping dead tool handlers
out of a production MCP fork that had none of these guardrails.

A sibling project, **[`mcp-issue-tracker`](https://github.com/HamzaOuadid/mcp-issue-tracker)**,
reuses this exact security architecture (auth passthrough, allowlist-gated
writes, dry-run, rate limiting, audit trail) applied to a real, local
issue-tracker domain — same pattern, proven twice rather than once.

## Why this exists

Most public MCP server examples wire an assistant straight to a service
account with full permissions and no guardrails. That's how an assistant
answering a reasonable question ends up leaking data the asker shouldn't
see, or silently executing a write nobody approved. This repo is what the
safer default looks like, small enough to read end to end in one sitting.

## Guardrails, and what each one prevents

| Guardrail | Where | What it prevents |
|---|---|---|
| **Auth passthrough** | `auth.py`, `identity.py` | A tool call ever running under a shared/blanket credential. Every call resolves *this specific caller's* identity and every downstream check uses that identity, not an admin/service account. Prevents "assistant sees everything the service account can see, regardless of who asked." |
| **Read-only by default + explicit write allowlist** | `registry.py`, `server.yaml` | A newly-added or mis-configured write tool executing before anyone has explicitly reviewed and enabled it. A tool is only ever callable as a write if its name is in `allowed_write_tools`; everything else is inert. Prevents "we added a tool and forgot it could delete things." |
| **Dry-run mode** | `tools/tickets.py`, `dryrun.py`, `server.py` | A write tool's *real* downstream side effect firing while an operator is still validating behaviour. In dry-run, the real API client is never called at all — verified in tests by spying on the client method itself, not just by inspecting the response. Prevents "we tested in prod because dry-run secretly still wrote." |
| **Per-session rate/spend cap** | `limiter.py` | An unbounded or runaway client burning spend or hammering a downstream API. Once a session's window budget (calls or cost units) is exhausted, every subsequent call in that window is rejected with a structured error and a `retry_after`, not just the one call that tripped it. Prevents "a bug in the client turned into an unbounded API bill." |
| **Structured audit log** | `audit.py` | A security incident being unreconstructable after the fact. Every call — allowed or denied, read or write, dry-run or real — is written as one JSON-lines record and one SQLite row: timestamp, session, user, tool, read/write, dry-run flag, allowed flag, latency. Prevents "we don't actually know what happened." |

## Architecture

```
                         ┌─────────────────────────────┐
   MCP client  ───────▶  │      transport adapter      │
 (stdio / HTTP)          │  mcp_app.py  /  http_app.py  │
                         └──────────────┬───────────────┘
                                        │ token, session_id, tool_name, args
                                        ▼
                         ┌─────────────────────────────┐
                         │      MCPStarterServer        │   server.py — single
                         │        .call_tool()          │   choke point every
                         └──────────────┬───────────────┘   call passes through
                    1) resolve tool ────┤
                    2) authenticate ────┤──▶ AuthMiddleware ──▶ MockIdentityProvider
                    3) allowlist check ─┤──▶ ToolRegistry
                    4) rate/spend check ┤──▶ SessionLimiter
                    5) execute ─────────┤──▶ tool handler (search_docs / create_ticket)
                    6) audit log ───────┴──▶ AuditLogger ──▶ audit.jsonl + SQLite
```

- **Auth middleware** (`auth.py`) resolves a bearer token to a `User` via
  `MockIdentityProvider` (`identity.py`) — clearly labeled dev-only, seeded
  with two distinct test users (`alice`/engineering, `bob`/sales) plus an
  admin. Missing or unrecognized tokens are rejected; there is no fallback
  identity.
- **Tool registry** (`registry.py`) is the single place every tool's
  read/write classification lives, cross-checked at registration time
  against `server.yaml`'s `tools:` section — a mismatch between what the
  code declares and what the config says refuses to start up. A write tool
  is only *callable* once its name is in `allowed_write_tools`; it's still
  *visible* in `list_tools()` either way, so a reviewer can see the full
  surface area, not just what's currently enabled.
- **Dry-run wrapper**: each write tool's handler takes a `dry_run: bool`
  and, for `create_ticket`, never touches `TicketSystemClient.create` (the
  stand-in downstream API) when it's true — it returns a synthetic
  `DRYRUN-...` id instead. `dryrun.py` formats the `[DRY RUN]` audit line.
- **Rate/spend limiter** (`limiter.py`) is a fixed-window counter per
  `session_id`: `calls_per_min` and `cost_per_session` (tool cost comes
  from the registry) reset together every `window_seconds`. Denied calls
  don't themselves consume budget.
- **Audit log** (`audit.py`) writes JSON-lines to a file and mirrors every
  record into a SQLite `audit_log` table matching the spec's data model,
  so it can be tailed as text or queried with SQL.

Two transports wrap the same `MCPStarterServer` core:

- **`mcp_app.py`** — a real MCP stdio server built on the official
  [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
  (`FastMCP`). Since stdio is a single local process with no per-request
  headers, `token` and `session_id` are explicit tool arguments — a common,
  documented simplification for local/dev MCP servers. This is what an
  actual MCP client (Claude Desktop, the `mcp` CLI, etc.) would talk to.
- **`http_app.py`** — a FastAPI HTTP transport where the token comes from
  a real `Authorization: Bearer <token>` header and the session from
  `X-Session-Id`, the shape a genuine multi-tenant deployment would use.

### Example tools

- `search_docs(query) -> list[DocResult]` — **read-only**. Searches a small
  static in-memory corpus, filtered to docs visible to the *calling user's*
  team (or company-wide docs). This is what makes auth passthrough provable:
  the same query from `alice` (engineering) and `bob` (sales) returns
  different results.
- `create_ticket(title, body) -> TicketId` — **write**, allowlist-gated.
  Stands in for a real ticketing API (`TicketSystemClient`); dry-run
  intercepts before that client is ever touched.

### Data model

- `audit_log`: `timestamp, session_id, user_id, tool_name, read_or_write,
  dry_run, allowed, latency_ms, error_code, detail` — SQLite table +
  JSON-lines file, written on every call.
- `tool_registry` config (`server.yaml` `tools:` section): `read_only,
  cost_units, description` per tool name.
- `session_limits`: in-memory per-session window (`call_count, cost_used`,
  reset at `window_seconds`), driven by `rate_limit:` in `server.yaml`.

### Error contract

Every rejection is a structured `MCPError` — `{code, message, retry_after?,
details?}` — never a bare exception or a silent no-op:

| code | when |
|---|---|
| `UNAUTHENTICATED` | token missing or not recognized |
| `WRITE_NOT_ALLOWED` | write tool called but not in `allowed_write_tools` |
| `RATE_LIMIT_EXCEEDED` | session exceeded `calls_per_min` or `cost_per_session` |
| `TOOL_NOT_FOUND` | unknown tool name |
| `INVALID_ARGUMENTS` | handler raised `TypeError` on the given arguments |

Over HTTP these map to `401 / 403 / 429 / 404 / 400` respectively, with the
same `{code, message, ...}` body in the response's `detail`.

## Install

Requires Python 3.10+ (developed and tested on 3.10; the spec called for
3.11+ — see *Deviations* below for why 3.10 was used instead).

```bash
git clone https://github.com/HamzaOuadid/mcp-starter-template.git
cd mcp-starter-template
pip install -e ".[dev]"
```

## Usage

### List the tool registry (security review)

```bash
mcp-starter tools
```

Real output from this repo:

```
  create_ticket    WRITE [DISABLED (not allowlisted)] cost=5   Create a ticket in the downstream ticket system (write, allowlist-gated).
  search_docs      read-only                        cost=1   Search internal docs visible to the calling user's team (read-only).
```

### Run the worked "what this prevents" demo

This is the milestone 4 deliverable: simulate the two-test-user scenario
end to end and show the permission boundary holding, using the real
`server.yaml` shipped in this repo (`dry_run: true`, empty
`allowed_write_tools`).

```bash
mcp-starter demo
```

Actual output from a real run against this repo's `server.yaml`
(`rate_limit.calls_per_min: 5`):

```
=== 1. Per-user auth passthrough: same tool, same query, different results ===
  alice (engineering): sees docs ['eng-001', 'eng-002', 'all-001']
  bob (sales): sees docs ['sales-001', 'sales-002', 'all-001']

=== 2. Missing/invalid identity is rejected, not defaulted ===
  token=None -> ok=False error={'code': 'UNAUTHENTICATED', 'message': 'Missing or invalid identity token; call rejected.'}

=== 3. Write tool default posture ===
  create_ticket denied: {'code': 'WRITE_NOT_ALLOWED', 'message': "Tool 'create_ticket' is a write tool and is not in allowed_write_tools. Add it to server.yaml's allowlist to enable it."}

=== 4. Rate limit: burst of calls past the cap ===
  call 1/6: allowed
  call 2/6: allowed
  call 3/6: allowed
  call 4/6: allowed
  call 5/6: allowed
  call 6/6: DENIED (RATE_LIMIT_EXCEEDED)

=== Audit log written to <repo>\demo_audit.jsonl ===
  {"allowed": true, "detail": "", "dry_run": false, "error_code": null, "latency_ms": 0.0, "read_or_write": "read", "session_id": "demo-burst-session", ...}
  {"allowed": true, ...}
  {"allowed": false, "error_code": "RATE_LIMIT_EXCEEDED", "detail": "Session 'demo-burst-session' exceeded its rate/spend cap (5 calls or 10 cost units per 60s window).", ...}
```

`alice` (engineering) and `bob` (sales) see disjoint doc sets plus the
shared company-wide handbook (`all-001`) — the permission boundary holds
from the exact same tool and query. A `None` token is rejected outright.
`create_ticket` is refused because the allowlist is empty by default. The
6th call in a 5-call-per-minute session is denied with a structured error.

Run it with the write tool allowlisted (still dry-run, since that's the
config default) to see the dry-run response shape:

```bash
mcp-starter demo --allow-writes
```

```
=== 3. Write tool default posture ===
  create_ticket allowed (allowlisted): TicketId(ticket_id='DRYRUN-8ffc09d5', dry_run=True)
```

No real ticket was created — `TicketSystemClient.created` stays empty in
dry-run mode; this is asserted directly in `tests/test_dry_run.py` by
spying on the client method itself.

### Run the HTTP transport

```bash
mcp-starter serve-http --port 8000
```

```bash
curl http://127.0.0.1:8000/tools

curl -X POST http://127.0.0.1:8000/tools/search_docs/call \
  -H "Authorization: Bearer token-alice" \
  -H "X-Session-Id: demo-1" \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"query": ""}}'

# Write tool, denied by default (empty allowlist):
curl -i -X POST http://127.0.0.1:8000/tools/create_ticket/call \
  -H "Authorization: Bearer token-alice" \
  -H "X-Session-Id: demo-1" \
  -H "Content-Type: application/json" \
  -d '{"arguments": {"title": "Broken build", "body": "CI red on main"}}'
# -> HTTP 403, {"detail":{"code":"WRITE_NOT_ALLOWED", ...}}
```

Dev tokens: `token-alice` (engineering), `token-bob` (sales), `token-admin`
(engineering, admin flag set).

### Run the real MCP stdio server

```bash
mcp-starter serve-stdio
```

This starts a real `FastMCP` stdio server — point an MCP client (e.g. the
`mcp` CLI's `mcp dev`, or Claude Desktop's config) at
`python -m mcp_starter.mcp_app`. Tools: `search_docs(query, token,
session_id)`, `create_ticket(title, body, token, session_id)`,
`list_tools()`.

### Configuration

Edit `server.yaml`:

```yaml
dry_run: true                 # write tools log-and-simulate instead of executing
allowed_write_tools: []       # empty = no write tool is callable, by design
rate_limit:
  calls_per_min: 5
  cost_per_session: 10
  window_seconds: 60
tools:
  search_docs:
    read_only: true
    cost_units: 1
  create_ticket:
    read_only: false
    cost_units: 5
```

To actually enable ticket creation: add `create_ticket` to
`allowed_write_tools` **and** set `dry_run: false`. Either one alone keeps
it either invisible-to-writes or simulated.

## Testing

```bash
pytest tests/ -v
```

Real output from this repo (40 tests, all passing):

```
tests/test_audit_log.py::test_audit_jsonl_reconstructs_a_session PASSED
tests/test_audit_log.py::test_audit_sqlite_table_matches_data_model PASSED
tests/test_audit_log.py::test_query_filters_by_session PASSED
tests/test_audit_log.py::test_rate_limit_denial_is_also_audited PASSED
tests/test_auth_passthrough.py::test_two_users_see_different_results_from_same_tool PASSED
tests/test_auth_passthrough.py::test_missing_token_is_rejected_not_defaulted PASSED
tests/test_auth_passthrough.py::test_invalid_token_is_rejected PASSED
tests/test_auth_passthrough.py::test_empty_string_token_is_rejected PASSED
tests/test_auth_passthrough.py::test_unknown_tool_name_does_not_crash PASSED
tests/test_cli.py::test_tools_command_lists_both_example_tools PASSED
tests/test_cli.py::test_demo_command_runs_full_scenario PASSED
tests/test_cli.py::test_demo_command_with_allow_writes_flag PASSED
tests/test_dry_run.py::test_dry_run_never_invokes_the_real_downstream_client PASSED
tests/test_dry_run.py::test_dry_run_logs_the_would_be_action_with_marker PASSED
tests/test_dry_run.py::test_dry_run_off_with_allowlist_actually_calls_downstream PASSED
tests/test_dry_run.py::test_dry_run_plus_write_tool_never_executes_even_when_allowlisted_repeatedly PASSED
tests/test_dry_run.py::test_read_only_tool_is_unaffected_by_dry_run_flag PASSED
tests/test_http_transport.py::test_list_tools_endpoint PASSED
tests/test_http_transport.py::test_auth_header_passthrough_two_users_differ PASSED
tests/test_http_transport.py::test_missing_auth_header_returns_401 PASSED
tests/test_http_transport.py::test_write_not_allowed_returns_403 PASSED
tests/test_http_transport.py::test_rate_limit_returns_429 PASSED
tests/test_http_transport.py::test_unknown_tool_returns_404 PASSED
tests/test_mcp_stdio.py::test_stdio_server_lists_all_three_tools PASSED
tests/test_mcp_stdio.py::test_stdio_server_two_users_differ PASSED
tests/test_mcp_stdio.py::test_stdio_server_write_tool_denied_by_default PASSED
tests/test_mcp_stdio.py::test_stdio_server_missing_token_rejected PASSED
tests/test_rate_limit.py::test_burst_of_n_plus_one_rejects_the_last_call PASSED
tests/test_rate_limit.py::test_calls_keep_being_rejected_until_window_resets PASSED
tests/test_rate_limit.py::test_cost_cap_is_enforced_independent_of_call_count PASSED
tests/test_rate_limit.py::test_sessions_are_isolated_from_each_other PASSED
tests/test_rate_limit.py::test_rate_limit_via_server_returns_structured_error PASSED
tests/test_rate_limit.py::test_denied_write_does_not_consume_rate_budget PASSED
tests/test_registry_allowlist.py::test_registry_describes_every_tool_classification PASSED
tests/test_registry_allowlist.py::test_all_write_tools_default_to_disabled PASSED
tests/test_registry_allowlist.py::test_write_tool_not_in_allowlist_is_denied PASSED
tests/test_registry_allowlist.py::test_write_tool_in_allowlist_becomes_enabled PASSED
tests/test_registry_allowlist.py::test_registration_refuses_undeclared_tool PASSED
tests/test_registry_allowlist.py::test_registration_refuses_classification_mismatch PASSED
tests/test_registry_allowlist.py::test_unknown_tool_call_is_tool_not_found PASSED

======================== 40 passed, 1 warning in 6.91s ========================
```

Coverage by concern:

- **Auth passthrough** (`test_auth_passthrough.py`) — two mock users, same
  tool, different results; missing/invalid/empty token rejected, never
  defaulted; unknown tool name fails cleanly instead of crashing.
- **Registry / allowlist** (`test_registry_allowlist.py`) — every tool's
  classification is inspectable; all write tools default to disabled;
  registration refuses tools missing from config or whose code/config
  classification disagree; unknown tool name is a clean `TOOL_NOT_FOUND`.
- **Dry-run** (`test_dry_run.py`) — spies on `TicketSystemClient.create`
  directly to assert it's genuinely never invoked in dry-run, not just
  that the response looks synthetic; uses `caplog` to confirm the
  `[DRY RUN]` marker is actually logged; confirms the real client *is*
  called once dry-run is off and the tool is allowlisted; repeats the
  dry-run + allowlisted-write combination multiple times to guard against
  regression; confirms read-only tools are unaffected by the flag.
- **Rate limiting** (`test_rate_limit.py`) — burst of N+1 rejects exactly
  the (N+1)th; calls keep being rejected for the rest of the window (not
  just the one that tripped it) via a fake clock; cost cap enforced
  independent of call count; sessions are isolated from each other; a
  denied write doesn't itself consume rate budget.
- **Audit log** (`test_audit_log.py`) — JSONL and SQLite both capture a
  full session in enough detail to reconstruct who/what/allowed/dry-run;
  SQLite rows are filterable by session; rate-limit denials are captured
  in the trail too, not just successes.
- **Both transports** (`test_http_transport.py`, `test_mcp_stdio.py`) —
  the same guardrails hold when driven through FastAPI's `TestClient` and
  through the real `FastMCP` server's async `call_tool`/`list_tools`, not
  just through the transport-agnostic core.
- **CLI** (`test_cli.py`) — `tools` and `demo` (with and without
  `--allow-writes`) run end to end without error via `typer.testing.
  CliRunner`.

## Deviations from the spec, and why

- **Python 3.10, not 3.11+.** The dev/CI environment ships 3.10; nothing
  in this codebase uses a 3.11-only feature, so the `requires-python`
  floor was relaxed rather than blocking on an interpreter upgrade. CI
  pins 3.10 to match what's actually tested.
- **SQLite, not PostgreSQL**, for the audit log. The spec allows either;
  Docker/Postgres aren't available in this environment. The audit schema
  (`audit_log` table in `audit.py`) is plain SQL with no SQLite-only
  syntax, so migrating to Postgres later is a driver swap
  (`sqlite3.connect` → `psycopg2`/`asyncpg`) plus `AUTOINCREMENT` →
  `SERIAL`/`IDENTITY`, not a redesign.
- **Auth passthrough over stdio uses an explicit `token` argument, not a
  transport header.** MCP's stdio transport is a single local process
  with no per-request headers, so there's nothing to intercept the way
  HTTP's `Authorization` header gives the HTTP transport (`http_app.py`)
  a real per-request credential. Passing the token explicitly keeps the
  *effect* (a resolved, non-default identity gating every call) identical
  and testable on both transports; it's a documented simplification, not
  a claim that stdio has "real" multi-user auth. A production multi-user
  deployment should run the HTTP transport, or a stdio transport wrapped
  by an authenticating proxy that injects the real credential upstream of
  this code.
- **No OAuth/JWT/mTLS in `MockIdentityProvider`.** It's a static
  token→user dict, clearly dev-only per the spec's own risk note. Swapping
  in real verification means implementing `AuthMiddleware.authenticate`'s
  token lookup against a real IdP; the rest of the pipeline (registry,
  limiter, dry-run, audit) is unaffected since it only depends on getting
  back a `User`.
- **Cut: v0.1 git tag.** Milestone 4 calls for tagging a `v0.1` release.
  This repo is commit-per-user-story rather than PR-per-milestone, so
  tagging is left for the maintainer to do once this lands on a default
  branch with CI green (`git tag v0.1.0 && git push --tags`) rather than
  self-tagging a repo that was never pushed anywhere.
- **Cut: no persistent `session_limits`/`tool_registry` tables.** The spec's
  data model lists `session_limits` and `tool_registry` as tables
  alongside `audit_log`. `tool_registry` classification lives in
  `server.yaml` (arguably a better single source of truth than a DB table
  a reviewer would have to query), and `session_limits` is in-memory only
  (`limiter.py`), which is correct for a single-process starter but won't
  survive a restart or scale across processes — call out as the first
  thing to fix (e.g. Redis-backed counters) before running this behind
  more than one server process.
- **Two example tools, not three-plus.** The spec asks for "2-3" — shipped
  exactly two (one read, one write), since a third read-only tool wouldn't
  exercise a guardrail the first two don't already cover.

## Project layout

```
src/mcp_starter/
  identity.py    mock identity provider (dev-only) + User model
  auth.py        auth passthrough middleware
  config.py      server.yaml loading/validation (pydantic)
  registry.py    tool registry: classification + allowlist enforcement
  limiter.py     per-session fixed-window rate/spend limiter
  audit.py       JSONL + SQLite structured audit logging
  dryrun.py      "[DRY RUN]" audit-line formatting
  errors.py      structured MCPError + error codes
  server.py      MCPStarterServer.call_tool — the orchestration core
  mcp_app.py     real MCP stdio server (official MCP Python SDK)
  http_app.py    FastAPI HTTP transport (Authorization header passthrough)
  cli.py         `mcp-starter` CLI: tools / demo / serve-http / serve-stdio
  tools/
    docs.py      search_docs (read-only example tool)
    tickets.py   create_ticket (write example tool) + TicketSystemClient
tests/           37 tests across every guardrail and both transports
server.yaml      tool classification, allowlist, dry-run, rate limits
```

## License

MIT — see [LICENSE](LICENSE).
