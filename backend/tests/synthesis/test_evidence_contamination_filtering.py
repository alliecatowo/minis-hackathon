"""Tests for contamination-aware explorer evidence prioritization."""

from __future__ import annotations

from app.models.evidence import Evidence
from app.synthesis.explorers.tools import _prioritize_rows


def _row(row_id: str, status: str | None, content: str) -> Evidence:
    return Evidence(
        id=row_id,
        mini_id="mini-1",
        source_type="github",
        item_type="review",
        content=content,
        ai_contamination_status=status,
    )


def test_prioritization_excludes_ai_like_and_downranks_uncertain():
    human = _row("human", "human", "I disagree, this will break retry behavior.")
    uncertain = _row("uncertain", "uncertain", "I disagree, this will break retry behavior.")
    contaminated = _row("ai", "ai_like", "I disagree, this will break retry behavior.")

    prioritized = _prioritize_rows([uncertain, contaminated, human], "conflicts_first")

    assert [row.id for row in prioritized] == ["human", "uncertain"]
