"""Mock identity provider.

DEV-ONLY. This resolves a bearer token to a :class:`User` from a static
in-memory table. It exists so the auth-passthrough pattern can be
demonstrated and unit-tested without standing up a real IdP (Okta, Auth0,
internal SSO, ...). Nothing here is production-grade: tokens are plain
strings compared with ``==``, there is no expiry, no signature
verification, and no revocation. A real deployment MUST replace
:class:`MockIdentityProvider` with an implementation that verifies a real
credential (OAuth token introspection, JWT signature + claims, mTLS
client cert, etc.) before it ever reaches ``AuthMiddleware``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class User:
    """The identity a tool call is scoped to.

    ``team`` drives per-user data visibility in the example tools (see
    ``tools/docs.py``) and ``is_admin`` is available for tools that want a
    coarser write/approve distinction. Nothing downstream should ever see
    a shared service-account credential in place of a real ``User``.
    """

    user_id: str
    display_name: str
    team: str
    is_admin: bool = False


class MockIdentityProvider:
    """Resolves opaque bearer tokens to :class:`User` records.

    Two distinct test users are seeded by default (``alice`` on the
    ``engineering`` team, ``bob`` on the ``sales`` team) precisely so the
    acceptance criteria "two distinct mock users see different results
    from the same tool" can be exercised directly against this class.
    """

    def __init__(self, tokens: dict[str, User] | None = None) -> None:
        self._tokens: dict[str, User] = tokens if tokens is not None else _default_tokens()

    def resolve(self, token: str | None) -> User | None:
        """Return the :class:`User` for ``token``, or ``None`` if invalid/missing.

        Deliberately returns ``None`` rather than raising so callers (the
        auth middleware) make one explicit decision about what happens on
        failure, instead of that decision being scattered across
        try/except blocks. Never falls back to a default identity.
        """
        if not token:
            return None
        return self._tokens.get(token)

    def register(self, token: str, user: User) -> None:
        """Add or replace a token->user mapping (used by tests)."""
        self._tokens[token] = user


def _default_tokens() -> dict[str, User]:
    return {
        "token-alice": User(
            user_id="alice",
            display_name="Alice Nguyen",
            team="engineering",
            is_admin=False,
        ),
        "token-bob": User(
            user_id="bob",
            display_name="Bob Reyes",
            team="sales",
            is_admin=False,
        ),
        "token-admin": User(
            user_id="root-admin",
            display_name="Priya Shah",
            team="engineering",
            is_admin=True,
        ),
    }
