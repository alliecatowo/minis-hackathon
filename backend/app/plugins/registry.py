"""Plugin registry — central place to register and look up sources and clients."""

from __future__ import annotations

import logging
from typing import Any

from app.plugins.base import ClientPlugin, IngestionSource

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry for ingestion sources and client plugins."""

    def __init__(self) -> None:
        self._sources: dict[str, IngestionSource] = {}
        self._clients: dict[str, ClientPlugin] = {}

    # -- Sources --

    def register_source(self, source: IngestionSource) -> None:
        """Register an ingestion source plugin."""
        if source.name in self._sources:
            logger.warning("Overwriting source plugin: %s", source.name)
        self._sources[source.name] = source
        logger.info("Registered ingestion source: %s", source.name)

    def get_source(self, name: str) -> IngestionSource:
        """Get a registered source by name. Raises KeyError if not found."""
        return self._sources[name]

    def list_sources(self) -> list[str]:
        """Return names of all registered ingestion sources."""
        return list(self._sources.keys())

    # -- Clients --

    def register_client(self, client: ClientPlugin) -> None:
        """Register a client plugin."""
        if client.name in self._clients:
            logger.warning("Overwriting client plugin: %s", client.name)
        self._clients[client.name] = client
        logger.info("Registered client plugin: %s", client.name)

    def get_client(self, name: str) -> ClientPlugin:
        """Get a registered client by name. Raises KeyError if not found."""
        return self._clients[name]

    def list_clients(self) -> list[str]:
        """Return names of all registered client plugins."""
        return list(self._clients.keys())

    async def setup_clients(self, app: Any) -> None:
        """Initialize all registered client plugins."""
        for client in self._clients.values():
            await client.setup(app)


# Singleton registry instance
registry = PluginRegistry()
