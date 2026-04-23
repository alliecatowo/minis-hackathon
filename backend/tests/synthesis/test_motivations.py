"""Tests for the goals + motivations extractor (ALLIE-429).

Covers:
- infer_motivations() returns MotivationsProfile from evidence-rich DB
- Returned shape matches schema contract (motivations + chains + summary)
- Motivation chains populate when evidence supports causal links
- evidence_ids are populated on returned Motivation objects
- Falls back cleanly with empty profile when no evidence exists
- build_motivations_block() renders non-empty block for rich profile
- build_motivations_block() returns empty string for empty/None profile
- spirit.build_system_prompt() injects MOTIVATIONS block when supplied
- spirit.build_system_prompt() omits MOTIVATIONS block when None
- spirit.build_system_prompt() is backward-compatible without motivations arg
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.schemas import Motivation, MotivationChain, MotivationsProfile
from app.synthesis.motivations import (
    MOTIVATION_EVIDENCE_ITEM_TYPES,
    _build_user_prompt,
    _sample_balanced_evidence,
    build_motivations_block,
    infer_motivations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mini_id() -> str:
    return str(uuid4())


def _make_finding(
    id: str,
    category: str = "value",
    content: str = "Consistently writes tests before code",
    confidence: float = 0.9,
    source_type: str = "github",
) -> MagicMock:
    row = MagicMock()
    row.id = id
    row.category = category
    row.content = content
    row.confidence = confidence
    row.source_type = source_type
    return row


def _make_quote(
    id: str,
    quote: str = "I never merge without tests",
    context: str = "PR review",
    significance: str = "behavioral_boundary",
    source_type: str = "github",
) -> MagicMock:
    row = MagicMock()
    row.id = id
    row.quote = quote
    row.context = context
    row.significance = significance
    row.source_type = source_type
    return row


def _make_evidence(
    id: str,
    item_type: str = "review_comment",
    content: str = "Requesting tests for this PR",
    source_type: str = "github",
    evidence_date: datetime | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = id
    row.item_type = item_type
    row.content = content
    row.source_type = source_type
    row.evidence_date = evidence_date
    row.created_at = created_at
    return row


def _make_db_session(
    findings: list | None = None,
    quotes: list | None = None,
    evidence: list | None = None,
) -> MagicMock:
    """Build a mock async DB session with three sequential execute() calls:
    1st → findings, 2nd → quotes, 3rd → evidence.
    """
    findings = findings or []
    quotes = quotes or []
    evidence = evidence or []

    session = MagicMock()

    findings_result = MagicMock()
    findings_result.scalars.return_value.all.return_value = findings

    quotes_result = MagicMock()
    quotes_result.scalars.return_value.all.return_value = quotes

    evidence_result = MagicMock()
    evidence_result.scalars.return_value.all.return_value = evidence

    call_count = [0]

    async def _execute(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            return findings_result
        if call_count[0] == 2:
            return quotes_result
        return evidence_result

    session.execute = _execute
    return session


def _make_agent_output(
    motivations: list | None = None,
    chains: list | None = None,
    summary: str = "Driven by craftsmanship and autonomy.",
) -> MagicMock:
    """Build a mock _MotivationsInferenceResult-like output."""
    if motivations is None:
        motivations = [
            MagicMock(
                value="craftsmanship",
                category="terminal_value",
                evidence_ids=["f-1", "f-2"],
                confidence=0.9,
            ),
            MagicMock(
                value="ship_v1",
                category="short_term_goal",
                evidence_ids=["f-3"],
                confidence=0.8,
            ),
        ]
    if chains is None:
        chains = [
            MagicMock(
                motivation="craftsmanship",
                implied_framework="always write tests before merging",
                observed_behavior="blocks PRs without tests",
                evidence_ids=["f-1", "e-1"],
            )
        ]

    output = MagicMock()
    output.motivations = motivations
    output.motivation_chains = chains
    output.summary = summary
    return output


# ---------------------------------------------------------------------------
# _build_user_prompt — pure function, no I/O
# ---------------------------------------------------------------------------


class TestBuildUserPrompt:
    def test_includes_username(self):
        prompt = _build_user_prompt(
            username="torvalds",
            findings=[],
            quotes=[],
            evidence_sample=[],
        )
        assert "torvalds" in prompt

    def test_includes_finding_content(self):
        prompt = _build_user_prompt(
            username="torvalds",
            findings=[
                {
                    "id": "f-1",
                    "category": "value",
                    "source_type": "github",
                    "content": "unique-finding-abc",
                    "confidence": 0.9,
                }
            ],
            quotes=[],
            evidence_sample=[],
        )
        assert "unique-finding-abc" in prompt

    def test_includes_quote_text(self):
        prompt = _build_user_prompt(
            username="torvalds",
            findings=[],
            quotes=[
                {
                    "id": "q-1",
                    "source_type": "github",
                    "quote": "unique-quote-xyz",
                    "context": "PR",
                    "significance": "behavioral",
                }
            ],
            evidence_sample=[],
        )
        assert "unique-quote-xyz" in prompt

    def test_includes_evidence_content(self):
        prompt = _build_user_prompt(
            username="torvalds",
            findings=[],
            quotes=[],
            evidence_sample=[
                {
                    "id": "e-1",
                    "source_type": "github",
                    "item_type": "commit",
                    "content": "unique-evidence-123",
                }
            ],
        )
        assert "unique-evidence-123" in prompt

    def test_includes_evidence_date_when_available(self):
        prompt = _build_user_prompt(
            username="torvalds",
            findings=[],
            quotes=[],
            evidence_sample=[
                {
                    "id": "e-1",
                    "source_type": "github",
                    "item_type": "review",
                    "content": "Requesting tests for this PR",
                    "evidence_date": "2025-01-15",
                }
            ],
        )
        assert "2025-01-15" in prompt

    def test_empty_evidence_still_returns_string(self):
        prompt = _build_user_prompt("torvalds", [], [], [])
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ---------------------------------------------------------------------------
# Evidence sampling — pure functions, no I/O
# ---------------------------------------------------------------------------


class TestEvidenceSampling:
    def test_current_github_review_type_is_included(self):
        assert "review" in MOTIVATION_EVIDENCE_ITEM_TYPES
        assert "pr" in MOTIVATION_EVIDENCE_ITEM_TYPES
        assert "review_comment" in MOTIVATION_EVIDENCE_ITEM_TYPES

    def test_balanced_sample_uses_evidence_date_not_ingestion_date(self):
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [
            _make_evidence(
                f"new-{i}",
                item_type="review",
                evidence_date=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
                created_at=created_at,
            )
            for i in range(9)
        ]
        rows += [
            _make_evidence(
                f"mid-{i}",
                item_type="review",
                evidence_date=datetime(2025, 1, i + 1, tzinfo=timezone.utc),
                created_at=created_at,
            )
            for i in range(9)
        ]
        rows += [
            _make_evidence(
                f"old-{i}",
                item_type="review",
                evidence_date=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                created_at=created_at,
            )
            for i in range(9)
        ]

        sample = _sample_balanced_evidence(rows, limit=9)

        sampled_years = {row.evidence_date.year for row in sample}
        assert sampled_years == {2024, 2025, 2026}

    def test_balanced_sample_interleaves_item_types_within_temporal_buckets(self):
        evidence_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        rows = [
            _make_evidence(f"review-{i}", item_type="review", evidence_date=evidence_date)
            for i in range(4)
        ]
        rows += [
            _make_evidence(f"issue-{i}", item_type="issue_comment", evidence_date=evidence_date)
            for i in range(4)
        ]

        sample = _sample_balanced_evidence(rows, limit=4, bucket_count=1)

        assert [row.item_type for row in sample] == [
            "review",
            "issue_comment",
            "review",
            "issue_comment",
        ]


# ---------------------------------------------------------------------------
# build_motivations_block — pure function, no I/O
# ---------------------------------------------------------------------------


class TestBuildMotivationsBlock:
    def test_empty_profile_returns_empty_string(self):
        profile = MotivationsProfile(motivations=[], motivation_chains=[], summary="")
        assert build_motivations_block(profile) == ""

    def test_none_returns_empty_string(self):
        result = build_motivations_block(None)  # type: ignore[arg-type]
        assert result == ""

    def test_terminal_values_rendered(self):
        profile = MotivationsProfile(
            motivations=[
                Motivation(
                    value="craftsmanship",
                    category="terminal_value",
                    evidence_ids=["f-1"],
                    confidence=0.9,
                ),
            ],
            motivation_chains=[],
            summary="Driven by craftsmanship.",
        )
        result = build_motivations_block(profile)
        assert "craftsmanship" in result
        assert "Terminal values" in result

    def test_anti_goals_rendered(self):
        profile = MotivationsProfile(
            motivations=[
                Motivation(
                    value="looking_incompetent",
                    category="anti_goal",
                    evidence_ids=["f-2"],
                    confidence=0.8,
                ),
            ],
            motivation_chains=[],
            summary="Avoids looking incompetent.",
        )
        result = build_motivations_block(profile)
        assert "looking_incompetent" in result
        assert "Anti-goals" in result

    def test_short_term_goals_rendered(self):
        profile = MotivationsProfile(
            motivations=[
                Motivation(
                    value="ship_demo", category="short_term_goal", evidence_ids=[], confidence=0.75
                ),
            ],
            motivation_chains=[],
            summary="Working on V1 demo.",
        )
        result = build_motivations_block(profile)
        assert "ship_demo" in result
        assert "Short-term" in result

    def test_motivation_chains_rendered(self):
        profile = MotivationsProfile(
            motivations=[
                Motivation(
                    value="craftsmanship",
                    category="terminal_value",
                    evidence_ids=["f-1"],
                    confidence=0.9,
                ),
            ],
            motivation_chains=[
                MotivationChain(
                    motivation="craftsmanship",
                    implied_framework="always write tests before merging",
                    observed_behavior="blocks PRs without tests",
                    evidence_ids=["f-1"],
                )
            ],
            summary="Driven by craftsmanship.",
        )
        result = build_motivations_block(profile)
        assert "craftsmanship" in result
        assert "always write tests before merging" in result
        assert "blocks PRs without tests" in result

    def test_motivations_block_header_present(self):
        profile = MotivationsProfile(
            motivations=[
                Motivation(
                    value="autonomy",
                    category="terminal_value",
                    evidence_ids=["f-1"],
                    confidence=0.85,
                ),
            ],
            motivation_chains=[],
            summary="Values autonomy.",
        )
        result = build_motivations_block(profile)
        assert "MOTIVATIONS" in result


# ---------------------------------------------------------------------------
# infer_motivations — mocked LLM
# ---------------------------------------------------------------------------


class TestInferMotivations:
    @pytest.mark.asyncio
    async def test_returns_motivations_profile_type(self):
        """infer_motivations() always returns a MotivationsProfile."""
        mini_id = _mini_id()
        findings = [_make_finding(f"f-{i}") for i in range(3)]
        quotes = [_make_quote(f"q-{i}") for i in range(2)]
        evidence = [_make_evidence(f"e-{i}") for i in range(2)]
        session = _make_db_session(findings=findings, quotes=quotes, evidence=evidence)

        mock_output = _make_agent_output()
        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.synthesis.motivations.Agent", return_value=mock_agent
        ):
            result = await infer_motivations(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert isinstance(result, MotivationsProfile)

    @pytest.mark.asyncio
    async def test_motivations_match_contract(self):
        """Returned motivations have correct shape (value, category, evidence_ids, confidence)."""
        mini_id = _mini_id()
        session = _make_db_session(
            findings=[_make_finding("f-1"), _make_finding("f-2"), _make_finding("f-3")],
        )

        mock_output = _make_agent_output()
        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.synthesis.motivations.Agent", return_value=mock_agent
        ):
            result = await infer_motivations(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert len(result.motivations) == 2
        craftsmanship = next((m for m in result.motivations if m.value == "craftsmanship"), None)
        assert craftsmanship is not None
        assert craftsmanship.category == "terminal_value"
        assert craftsmanship.confidence == 0.9
        assert "f-1" in craftsmanship.evidence_ids

    @pytest.mark.asyncio
    async def test_motivation_chains_populate_when_evidence_supports(self):
        """Chains are returned when the LLM output contains them."""
        mini_id = _mini_id()
        session = _make_db_session(
            findings=[_make_finding("f-1"), _make_finding("f-2")],
            evidence=[_make_evidence("e-1")],
        )

        mock_output = _make_agent_output()
        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.synthesis.motivations.Agent", return_value=mock_agent
        ):
            result = await infer_motivations(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert len(result.motivation_chains) == 1
        chain = result.motivation_chains[0]
        assert chain.motivation == "craftsmanship"
        assert "tests" in chain.implied_framework
        assert "blocks" in chain.observed_behavior
        assert "f-1" in chain.evidence_ids

    @pytest.mark.asyncio
    async def test_evidence_ids_populated_on_motivations(self):
        """evidence_ids on Motivation objects are non-empty when LLM provides them."""
        mini_id = _mini_id()
        session = _make_db_session(
            findings=[_make_finding("f-1"), _make_finding("f-2"), _make_finding("f-3")],
        )

        mock_output = _make_agent_output()
        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.synthesis.motivations.Agent", return_value=mock_agent
        ):
            result = await infer_motivations(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        # Every returned motivation that has evidence_ids must have at least one
        for m in result.motivations:
            assert isinstance(m.evidence_ids, list)

        # The craftsmanship motivation specifically has ["f-1", "f-2"]
        craftsmanship = next((m for m in result.motivations if m.value == "craftsmanship"), None)
        assert craftsmanship is not None
        assert len(craftsmanship.evidence_ids) >= 1

    @pytest.mark.asyncio
    async def test_returns_empty_profile_when_no_evidence(self):
        """No evidence → minimal empty MotivationsProfile, no crash."""
        mini_id = _mini_id()
        session = _make_db_session(findings=[], quotes=[], evidence=[])

        result = await infer_motivations(
            mini_id=mini_id,
            db_session=session,
            username="torvalds",
        )

        assert isinstance(result, MotivationsProfile)
        assert len(result.motivations) == 0
        assert len(result.motivation_chains) == 0
        assert result.summary != ""

    @pytest.mark.asyncio
    async def test_summary_is_populated(self):
        """Summary field is set from LLM output."""
        mini_id = _mini_id()
        session = _make_db_session(
            findings=[_make_finding("f-1"), _make_finding("f-2")],
        )

        mock_output = _make_agent_output(summary="Values craftsmanship and ships with confidence.")
        mock_result = MagicMock()
        mock_result.output = mock_output

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=mock_result)

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.synthesis.motivations.Agent", return_value=mock_agent
        ):
            result = await infer_motivations(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert "craftsmanship" in result.summary


# ---------------------------------------------------------------------------
# spirit.build_system_prompt() integration
# ---------------------------------------------------------------------------


class TestSpiritIntegration:
    def test_motivations_block_included_when_supplied(self):
        """build_system_prompt() injects MOTIVATIONS block when profile is provided."""
        from app.synthesis.spirit import build_system_prompt

        profile = MotivationsProfile(
            motivations=[
                Motivation(
                    value="craftsmanship",
                    category="terminal_value",
                    evidence_ids=["f-1"],
                    confidence=0.9,
                )
            ],
            motivation_chains=[
                MotivationChain(
                    motivation="craftsmanship",
                    implied_framework="always write tests before merging",
                    observed_behavior="blocks PRs without tests",
                    evidence_ids=["f-1"],
                )
            ],
            summary="Driven by craftsmanship.",
        )

        prompt = build_system_prompt(
            username="torvalds",
            spirit_content="spirit here",
            memory_content="memory here",
            motivations=profile,
        )

        assert "MOTIVATIONS" in prompt
        assert "craftsmanship" in prompt

    def test_motivations_block_omitted_when_none(self):
        """build_system_prompt() omits MOTIVATIONS when motivations=None."""
        from app.synthesis.spirit import build_system_prompt

        prompt = build_system_prompt(
            username="torvalds",
            spirit_content="spirit here",
            memory_content="memory here",
            motivations=None,
        )

        assert "MOTIVATIONS" not in prompt

    def test_backward_compatible_no_motivations_arg(self):
        """Existing callers without motivations kwarg still work."""
        from app.synthesis.spirit import build_system_prompt

        prompt = build_system_prompt("torvalds", "spirit", "memory")
        assert isinstance(prompt, str)
        assert "torvalds" in prompt

    def test_motivation_chains_appear_in_prompt(self):
        """Motivation chains are visible in the generated system prompt."""
        from app.synthesis.spirit import build_system_prompt

        profile = MotivationsProfile(
            motivations=[
                Motivation(
                    value="autonomy", category="terminal_value", evidence_ids=[], confidence=0.8
                ),
            ],
            motivation_chains=[
                MotivationChain(
                    motivation="autonomy",
                    implied_framework="deep work protected",
                    observed_behavior="declines meetings >30min",
                    evidence_ids=[],
                )
            ],
            summary="Values autonomy deeply.",
        )

        prompt = build_system_prompt(
            username="torvalds",
            spirit_content="spirit here",
            memory_content="memory here",
            motivations=profile,
        )

        assert "deep work protected" in prompt
        assert "declines meetings" in prompt
