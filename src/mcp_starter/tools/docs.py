"""``search_docs`` -- the read-only example tool.

Demonstrates per-user auth passthrough with a non-trivial effect: the
corpus contains docs tagged to specific teams (plus a set visible to
everyone), and results are filtered by the *calling user's* team, not by
a shared service-account view of "everything". Two users hitting the
exact same query can and do get different results -- that's the whole
point of the acceptance criteria this tool exists to prove.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..identity import User


@dataclass(frozen=True)
class DocResult:
    doc_id: str
    title: str
    snippet: str
    team: str


# A small, static in-memory "corpus". `team=None` means visible to every
# authenticated user regardless of team (company-wide docs); anything
# else is scoped to that team only.
_CORPUS: list[DocResult] = [
    DocResult(
        doc_id="eng-001",
        title="Runbook: rotating the deploy signing key",
        snippet="Steps to rotate the CI signing key without downtime...",
        team="engineering",
    ),
    DocResult(
        doc_id="eng-002",
        title="Postmortem: 2026-06 ingestion outage",
        snippet="Root cause was an unbounded retry loop in the queue consumer...",
        team="engineering",
    ),
    DocResult(
        doc_id="sales-001",
        title="Q3 pricing sheet (internal)",
        snippet="Enterprise tier pricing bands and discount approval thresholds...",
        team="sales",
    ),
    DocResult(
        doc_id="sales-002",
        title="Competitor battlecard: Acme Corp",
        snippet="Positioning notes for deals where Acme is the incumbent...",
        team="sales",
    ),
    DocResult(
        doc_id="all-001",
        title="Employee handbook: expense policy",
        snippet="Expense reports over $500 require manager approval...",
        team=None,
    ),
]


def search_docs(user: User, query: str) -> list[DocResult]:
    """Search the doc corpus, scoped to ``user``'s visibility.

    A doc is visible if it has no team restriction, or if its team
    matches ``user.team``. This is the auth-passthrough boundary in
    action: the handler receives the *resolved calling user*, never a
    blanket service credential, and enforces visibility from that.
    """
    query_lower = query.lower().strip()
    results = []
    for doc in _CORPUS:
        if doc.team is not None and doc.team != user.team:
            continue
        haystack = f"{doc.title} {doc.snippet}".lower()
        if query_lower == "" or query_lower in haystack:
            results.append(doc)
    return results
