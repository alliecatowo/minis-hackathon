"""Plugin loader — registers all built-in plugins at startup."""

from __future__ import annotations

from app.plugins.clients.web import WebClient
from app.plugins.registry import registry
from app.plugins.sources.blog import BlogSource
from app.plugins.sources.claude_code import ClaudeCodeSource
from app.plugins.sources.devblog import DevBlogSource
from app.plugins.sources.github import GitHubSource
from app.plugins.sources.hackernews import HackerNewsSource
from app.plugins.sources.stackoverflow import StackOverflowSource


def load_plugins() -> None:
    """Register all built-in plugins with the global registry."""
    # Ingestion sources
    registry.register_source(GitHubSource())
    registry.register_source(ClaudeCodeSource())
    registry.register_source(BlogSource())
    registry.register_source(StackOverflowSource())
    registry.register_source(DevBlogSource())
    registry.register_source(HackerNewsSource())

    # Client plugins
    registry.register_client(WebClient())
