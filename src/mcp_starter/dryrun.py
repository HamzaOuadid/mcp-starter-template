"""Dry-run formatting + logging.

The guarantee that a write tool never touches the real downstream API in
dry-run mode lives in the tool's own handler (see
``tools/tickets.py:create_ticket``, which short-circuits before calling
``TicketSystemClient.create``). This module supplies the one bit of
shared behaviour every write tool needs on top of that: a consistent,
greppable ``[DRY RUN]`` log line describing the endpoint and payload the
call would have hit -- what an operator running dry-run mode actually
reads to see what a write tool *would* have done.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mcp_starter.dryrun")

DRY_RUN_MARKER = "[DRY RUN]"


def format_dry_run_detail(tool_name: str, arguments: dict[str, Any]) -> str:
    """Build the ``[DRY RUN]`` log line for a simulated write call.

    Example: ``"[DRY RUN] would call create_ticket(title='...', body='...')"``.
    """
    args_repr = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
    return f"{DRY_RUN_MARKER} would call {tool_name}({args_repr})"


def log_dry_run(tool_name: str, arguments: dict[str, Any]) -> str:
    """Format and emit the dry-run log line; returns the formatted string
    so callers (e.g. the audit log, added in a later commit) can reuse it
    without reformatting."""
    detail = format_dry_run_detail(tool_name, arguments)
    logger.info(detail)
    return detail
