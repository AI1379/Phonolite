"""OpenCode-facing MCP adapter for Music Agent Workbench tools."""

from music_mcp.client import DomainApiClient, DomainApiError, JsonObject, JsonValue

__version__ = "0.1.0"

__all__ = [
    "DomainApiClient",
    "DomainApiError",
    "JsonObject",
    "JsonValue",
]
