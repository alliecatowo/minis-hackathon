"""Shared fixtures for backend tests."""

from __future__ import annotations

import pytest

from app.synthesis.explorers.base import ExplorerReport, MemoryEntry


def make_memory(
    category: str = "expertise",
    topic: str = "Python",
    content: str = "Uses Python extensively.",
    confidence: float = 0.9,
    source_type: str = "github",
    evidence_quote: str = "I love Python",
) -> MemoryEntry:
    """Factory helper for creating MemoryEntry instances."""
    return MemoryEntry(
        category=category,
        topic=topic,
        content=content,
        confidence=confidence,
        source_type=source_type,
        evidence_quote=evidence_quote,
    )


def make_report(
    source_name: str = "github",
    personality_findings: str = "",
    memory_entries: list[MemoryEntry] | None = None,
    behavioral_quotes: list[dict] | None = None,
) -> ExplorerReport:
    """Factory helper for creating ExplorerReport instances."""
    return ExplorerReport(
        source_name=source_name,
        personality_findings=personality_findings,
        memory_entries=memory_entries or [],
        behavioral_quotes=behavioral_quotes or [],
    )
