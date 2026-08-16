"""Structured audit logging.

Every tool call -- allowed or denied, real or dry-run -- produces one
:class:`AuditRecord`. Records are appended to a JSON-lines file (one
compact JSON object per line, matching the architecture's "structured
(JSON lines) record of every tool call") and mirrored into a SQLite
``audit_log`` table matching the spec's data model, so the same history
can be tailed as text or queried with SQL.

The point of both forms: a reviewer unfamiliar with the code should be
able to read either one and reconstruct exactly what happened in a test
session -- who called what, whether it was a write, whether it was
allowed, whether it actually executed or was a dry-run, and how long it
took.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AuditRecord:
    timestamp: float
    session_id: str
    user_id: str
    tool_name: str
    read_or_write: str  # "read" | "write"
    dry_run: bool
    allowed: bool
    latency_ms: float
    error_code: Optional[str] = None
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    read_or_write TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    allowed INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    error_code TEXT,
    detail TEXT
)
"""


class AuditLogger:
    """Writes every :class:`AuditRecord` to both a JSONL file and SQLite.

    ``jsonl_path`` and/or ``sqlite_path`` may be ``None`` to disable that
    sink (tests commonly disable both and just inspect ``records`` /
    query ``connection`` directly). An in-memory list of every record
    written is always kept for easy assertions in tests.
    """

    def __init__(
        self,
        jsonl_path: Optional[str | Path] = None,
        sqlite_path: Optional[str | Path] = None,
    ) -> None:
        self.records: list[AuditRecord] = []
        self._jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self._jsonl_path:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        self._sqlite_path = str(sqlite_path) if sqlite_path else ":memory:"
        # check_same_thread=False: callers such as the FastAPI HTTP
        # transport dispatch request handlers onto a worker thread pool,
        # while the AuditLogger (and its connection) is created once at
        # server startup on the main thread. Writes are still serialized
        # by SQLite's own locking, so this is safe for the single-process,
        # low-concurrency use case this starter targets.
        self._conn = sqlite3.connect(self._sqlite_path, check_same_thread=False)
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()

    def log(self, record: AuditRecord) -> None:
        self.records.append(record)

        if self._jsonl_path:
            with self._jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(record.to_json() + "\n")

        self._conn.execute(
            "INSERT INTO audit_log "
            "(timestamp, session_id, user_id, tool_name, read_or_write, "
            "dry_run, allowed, latency_ms, error_code, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.timestamp,
                record.session_id,
                record.user_id,
                record.tool_name,
                record.read_or_write,
                int(record.dry_run),
                int(record.allowed),
                record.latency_ms,
                record.error_code,
                record.detail,
            ),
        )
        self._conn.commit()

    def query(self, session_id: Optional[str] = None) -> list[sqlite3.Row]:
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.cursor()
        if session_id:
            cur.execute(
                "SELECT * FROM audit_log WHERE session_id = ? ORDER BY id", (session_id,)
            )
        else:
            cur.execute("SELECT * FROM audit_log ORDER BY id")
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()


def now() -> float:
    return time.time()
