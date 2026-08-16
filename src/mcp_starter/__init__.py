"""mcp-starter-template: a security-first MCP server reference scaffold.

Guardrails demonstrated (built up incrementally, story by story): per-user
auth passthrough, read-only-by-default tools with explicit write
allowlisting, dry-run mode for write tools, per-session rate/spend caps,
and structured audit logging.
"""

from .config import ServerConfig
from .errors import ErrorCode, MCPError
from .identity import MockIdentityProvider, User
from .server import MCPStarterServer, ToolCallResult

__all__ = [
    "ServerConfig",
    "ErrorCode",
    "MCPError",
    "MockIdentityProvider",
    "User",
    "MCPStarterServer",
    "ToolCallResult",
]

__version__ = "0.1.0"
