"""``create_ticket`` -- the write example tool.

This is the tool the allowlist gate protects: unlike ``search_docs`` it
has a real side effect on a downstream system, represented here by
``TicketSystemClient`` standing in for a real ticketing API (Jira,
Linear, ServiceNow, ...). Kept as a separate object (rather than a bare
function) so later guardrails -- dry-run in particular -- can be tested
by spying on ``.create`` directly to prove it either was or wasn't
called, not just by inspecting the tool's return value.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..identity import User


@dataclass
class TicketId:
    ticket_id: str
    # Not meaningful yet (dry-run mode lands in a later commit), but part
    # of the response shape from day one so callers don't need to change
    # once it is.
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


def create_ticket(user: User, title: str, body: str, client: TicketSystemClient) -> TicketId:
    """Create a ticket via the downstream client, scoped to the calling user."""
    ticket_id = client.create(title=title, body=body, requester=user.user_id)
    return TicketId(ticket_id=ticket_id)
