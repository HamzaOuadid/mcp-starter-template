"""``create_ticket`` -- the write example tool.

This is the tool both the allowlist gate and dry-run mode protect. Unlike
``search_docs`` it has a real side effect on a downstream system,
represented here by ``TicketSystemClient`` standing in for a real
ticketing API (Jira, Linear, ServiceNow, ...). Kept as a separate object
(rather than a bare function) so dry-run can be tested by spying on
``.create`` directly to prove it either was or wasn't called, not just by
inspecting the tool's return value.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..dryrun import log_dry_run
from ..identity import User


@dataclass
class TicketId:
    ticket_id: str
    dry_run: bool = False


@dataclass
class TicketSystemClient:
    """Stand-in for a real downstream ticket-system API client.

    Records every ticket it creates in ``created`` so tests (and the CLI
    demo) can inspect what really happened downstream, separate from what
    the tool call returned.
    """

    created: list[dict[str, str]] = field(default_factory=list)

    def create(self, title: str, body: str, requester: str) -> str:
        ticket_id = f"TKT-{uuid.uuid4().hex[:8]}"
        self.created.append({"ticket_id": ticket_id, "title": title, "body": body, "requester": requester})
        return ticket_id


def create_ticket(
    user: User,
    title: str,
    body: str,
    client: TicketSystemClient,
    dry_run: bool = False,
) -> TicketId:
    """Create a ticket, or simulate doing so when ``dry_run`` is true.

    When ``dry_run`` is true, this function logs the intended call (with
    a ``[DRY RUN]`` marker) and returns a synthetic ``TicketId`` WITHOUT
    calling ``client.create`` at all -- the real downstream client is
    never touched. This is the actual guarantee under test in
    ``test_dry_run.py``: a spy on ``client.create`` must never fire.
    """
    if dry_run:
        log_dry_run("create_ticket", {"title": title, "body": body})
        synthetic_id = f"DRYRUN-{uuid.uuid4().hex[:8]}"
        return TicketId(ticket_id=synthetic_id, dry_run=True)

    real_id = client.create(title=title, body=body, requester=user.user_id)
    return TicketId(ticket_id=real_id, dry_run=False)
