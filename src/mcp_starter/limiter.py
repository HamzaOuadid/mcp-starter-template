"""Per-session rate/spend limiter.

A fixed-window counter per ``session_id``: within a rolling
``window_seconds`` window a session may make at most ``calls_per_min``
calls and spend at most ``cost_per_session`` cost units (tool cost comes
from the registry). Once either cap is hit, *every* subsequent call in
that session is rejected until the window rolls over -- not just the one
call that tripped it, per the spec's edge case.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from .config import RateLimitConfig
from .errors import ErrorCode, MCPError


@dataclass
class _SessionWindow:
    window_start: float
    call_count: int = 0
    cost_used: int = 0


class SessionLimiter:
    def __init__(self, config: RateLimitConfig, clock: Optional[Callable[[], float]] = None) -> None:
        self._config = config
        self._clock = clock or time.monotonic
        self._sessions: dict[str, _SessionWindow] = {}

    def _current_window(self, session_id: str) -> _SessionWindow:
        now = self._clock()
        window = self._sessions.get(session_id)
        if window is None or (now - window.window_start) >= self._config.window_seconds:
            window = _SessionWindow(window_start=now)
            self._sessions[session_id] = window
        return window

    def check_and_consume(self, session_id: str, cost_units: int) -> None:
        """Consume ``cost_units`` from ``session_id``'s budget or raise.

        Raises :class:`MCPError` with code ``RATE_LIMIT_EXCEEDED`` and a
        ``retry_after`` (seconds until the window resets) when either the
        call-count cap or the cost cap would be exceeded. Nothing is
        consumed on rejection -- a denied call doesn't itself count
        against the budget again once the window resets.
        """
        window = self._current_window(session_id)
        would_be_calls = window.call_count + 1
        would_be_cost = window.cost_used + cost_units

        if would_be_calls > self._config.calls_per_min or would_be_cost > self._config.cost_per_session:
            retry_after = max(0.0, self._config.window_seconds - (self._clock() - window.window_start))
            raise MCPError(
                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                message=(
                    f"Session {session_id!r} exceeded its rate/spend cap "
                    f"({self._config.calls_per_min} calls or "
                    f"{self._config.cost_per_session} cost units per "
                    f"{self._config.window_seconds}s window)."
                ),
                retry_after=round(retry_after, 3),
                details={
                    "calls_in_window": window.call_count,
                    "cost_in_window": window.cost_used,
                },
            )

        window.call_count = would_be_calls
        window.cost_used = would_be_cost

    def usage(self, session_id: str) -> dict[str, int]:
        window = self._sessions.get(session_id)
        if window is None:
            return {"call_count": 0, "cost_used": 0}
        return {"call_count": window.call_count, "cost_used": window.cost_used}
