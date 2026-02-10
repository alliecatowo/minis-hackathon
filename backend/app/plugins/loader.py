"""Plugin loader — registers all built-in plugins at startup."""

from __future__ import annotations

from app.plugins.clients.web import WebClient
from app.plugins.registry import registry
from app.plugins.sources.claude_code import ClaudeCodeSource
from app.plugins.sources.github import GitHubSource


def load_plugins() -> None:
    """Register all built-in plugins with the global registry."""
    # Ingestion sources
    registry.register_source(GitHubSource())
    registry.register_source(ClaudeCodeSource())

    # Client plugins
    registry.register_client(WebClient())
