"""Auth passthrough middleware.

Every tool call is intercepted here before it reaches a tool handler. The
calling user's own identity is resolved from their own token and passed
down to the handler -- the handler never receives (and the server never
holds) a shared service-account credential. If the token is missing or
invalid the call is rejected outright; there is no default identity to
fall back to.
"""

from __future__ import annotations

from .errors import ErrorCode, MCPError
from .identity import MockIdentityProvider, User


class AuthMiddleware:
    """Resolves the calling user for every tool call, or rejects it."""

    def __init__(self, identity_provider: MockIdentityProvider) -> None:
        self._identity_provider = identity_provider

    def authenticate(self, token: str | None) -> User:
        """Resolve ``token`` to a :class:`User`.

        Raises :class:`MCPError` with code ``UNAUTHENTICATED`` when the
        token is missing or unrecognized. This is the only path -- there
        is intentionally no "anonymous" or "default" user a call can fall
        back to, per the edge case in the spec: a missing/invalid token
        must reject the call, not silently proceed as someone else.
        """
        user = self._identity_provider.resolve(token)
        if user is None:
            raise MCPError(
                code=ErrorCode.UNAUTHENTICATED,
                message="Missing or invalid identity token; call rejected.",
            )
        return user
