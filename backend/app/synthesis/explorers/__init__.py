"""Explorer registry.

Maps source names to Explorer subclasses. Individual explorer modules
register themselves by adding to EXPLORER_MAP on import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.synthesis.explorers.base import Explorer

# Populated by explorer subclass modules when they are imported
EXPLORER_MAP: dict[str, type[Explorer]] = {}


def register_explorer(source_name: str, explorer_cls: type[Explorer]) -> None:
    """Register an explorer class for a given source name."""
    EXPLORER_MAP[source_name] = explorer_cls


def get_explorer(source_name: str) -> Explorer:
    """Get an instantiated explorer for the given source name.

    Raises KeyError if no explorer is registered for that source.
    """
    if source_name not in EXPLORER_MAP:
        raise KeyError(
            f"No explorer registered for source '{source_name}'. "
            f"Available: {list(EXPLORER_MAP.keys())}"
        )
    return EXPLORER_MAP[source_name]()
