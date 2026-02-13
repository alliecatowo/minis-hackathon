"""Base protocols for the Minis plugin system.

Ingestion sources fetch raw data from external services and format it as evidence
text for the LLM synthesis pipeline. Client plugins expose a mini through different
interfaces (web, MCP, CLI, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IngestionResult:
    """Standard output from an ingestion source."""

    source_name: str
    identifier: str  # e.g. GitHub username, file path, Slack workspace
    evidence: str  # Formatted evidence text ready for LLM analysis
    raw_data: dict[str, Any] = field(default_factory=dict)  # Preserved for metadata
    stats: dict[str, Any] = field(default_factory=dict)  # Source-specific stats


class IngestionSource(ABC):
    """Protocol for data ingestion sources.

    Each source knows how to fetch raw data from an external service and
    format it into evidence text suitable for personality analysis.
    """

    name: str  # Unique identifier, e.g. "github", "claude_code", "slack"
    source_type: str = "voice"  # "voice" or "memory"

    @abstractmethod
    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch data and return formatted evidence.

        Args:
            identifier: Source-specific identifier (username, file path, etc.)
            **config: Optional source-specific configuration.

        Returns:
            IngestionResult with formatted evidence text and metadata.
        """
        ...


class ClientPlugin(ABC):
    """Protocol for output client plugins.

    Each client exposes a mini's personality through a different interface.
    Clients are registered at startup and may add routes, start servers, etc.
    """

    name: str  # Unique identifier, e.g. "web", "mcp", "cli"

    @abstractmethod
    async def setup(self, app: Any) -> None:
        """Initialize the client plugin. Called during app startup.

        Args:
            app: The FastAPI application instance (or None for standalone clients).
        """
        ...
