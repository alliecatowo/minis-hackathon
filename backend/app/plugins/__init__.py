"""Plugin system for Minis — extensible ingestion sources and client outputs."""

from app.plugins.base import ClientPlugin, IngestionResult, IngestionSource
from app.plugins.registry import registry

__all__ = [
    "ClientPlugin",
    "IngestionResult",
    "IngestionSource",
    "registry",
]
