"""Unit tests: data contracts between pipeline stages.

Verifies:
1. GitHubData field coverage — every field accessed in GitHubSource.fetch_items()
   and _aggregate_* helpers exists on the GitHubData dataclass. Regression
   guard for ALLIE-368 (missing commit_diffs / pr_review_threads / issue_threads).

2. IngestionResult contract — GitHubSource output has the shape the explorer
   and chief synthesizer expect to receive.

3. ExplorerReport contract — ExplorerReport fields that pipeline.py accesses
   (source_name, personality_findings, memory_entries) are all present and typed.

4. Explorer tool suite contract — build_explorer_tools() exposes exactly 12
   documented tools, each with an async handler.

All tests are pure unit tests (no I/O, no DB, no LLM calls).
"""

from __future__ import annotations

import dataclasses
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# 1. GitHubData field coverage (ALLIE-368 regression guard)
# ---------------------------------------------------------------------------


class TestGitHubDataFieldCoverage:
    """Every field that GitHubSource.fetch_items() accesses must exist on GitHubData."""

    # Fields accessed directly in github.py (the plugin source file)
    # Updated whenever a new access pattern is added. This list is the
    # authoritative contract between ingestion and the pipeline.
    FIELDS_ACCESSED_BY_PLUGIN = frozenset(
        {
            "profile",
            "repos",
            "commits",
            "pull_requests",
            "review_comments",
            "issue_comments",
            "repo_languages",
            "commit_diffs",
            "pr_review_threads",
            "issue_threads",
        }
    )

    def _get_githubdata_fields(self):
        from app.ingestion.github import GitHubData

        return {f.name for f in dataclasses.fields(GitHubData)}

    def test_all_plugin_accessed_fields_exist_on_dataclass(self):
        """Regression guard for ALLIE-368: fields accessed by the plugin must exist."""
        dc_fields = self._get_githubdata_fields()
        missing = self.FIELDS_ACCESSED_BY_PLUGIN - dc_fields
        assert not missing, (
            f"GitHubData is missing fields accessed by GitHubSource: {missing}\n"
            "Add the missing field(s) to the GitHubData dataclass in "
            "backend/app/ingestion/github.py"
        )

    def test_githubdata_constructable_with_no_args(self):
        """GitHubData() with no args must succeed (all fields have defaults)."""
        from app.ingestion.github import GitHubData

        try:
            obj = GitHubData()
        except TypeError as exc:
            pytest.fail(
                f"GitHubData() construction without args raised: {exc}\n"
                "All fields must have default values so the plugin can construct "
                "a minimal object."
            )
        assert obj is not None

    def test_list_fields_default_to_empty_list(self):
        """List fields must default to [] not None — downstream code iterates them."""
        from app.ingestion.github import GitHubData

        obj = GitHubData()
        list_fields = [
            "repos",
            "commits",
            "pull_requests",
            "review_comments",
            "issue_comments",
            "commit_diffs",
            "pr_review_threads",
            "issue_threads",
        ]
        for field in list_fields:
            val = getattr(obj, field)
            assert isinstance(val, list), (
                f"GitHubData.{field} should default to list, got {type(val).__name__}"
            )
            assert val == [], f"GitHubData.{field} should default to [], got {val!r}"

    def test_profile_field_defaults_to_dict(self):
        from app.ingestion.github import GitHubData

        obj = GitHubData()
        assert isinstance(obj.profile, dict), (
            f"GitHubData.profile should default to dict, got {type(obj.profile).__name__}"
        )

    def test_repo_languages_field_defaults_to_dict(self):
        """repo_languages must be a dict — _aggregate_languages() calls .values() on it."""
        from app.ingestion.github import GitHubData

        obj = GitHubData()
        assert isinstance(obj.repo_languages, dict), (
            f"GitHubData.repo_languages should default to dict, "
            f"got {type(obj.repo_languages).__name__}"
        )

    def test_all_accessed_fields_are_not_none_by_default(self):
        """None defaults would cause AttributeError on iteration in plugin helpers."""
        from app.ingestion.github import GitHubData

        obj = GitHubData()
        for field in self.FIELDS_ACCESSED_BY_PLUGIN:
            val = getattr(obj, field)
            assert val is not None, (
                f"GitHubData.{field} defaults to None — this will cause errors when "
                "iterating / calling .values() on it. Use an empty collection default."
            )

    def test_new_fields_added_since_initial_version(self):
        """Document that commit_diffs, pr_review_threads, issue_threads were added.

        If any of these were missing the plugin would crash with AttributeError
        (the ALLIE-368 bug). This test explicitly names them so reviewers see
        the regression guard is active.
        """
        from app.ingestion.github import GitHubData

        dc_fields = {f.name for f in dataclasses.fields(GitHubData)}
        extended_fields = {"commit_diffs", "pr_review_threads", "issue_threads"}
        assert extended_fields.issubset(dc_fields), (
            f"Extended GitHubData fields missing: {extended_fields - dc_fields}\n"
            "These fields are accessed in GitHubSource.fetch_items() raw_data building."
        )


# ---------------------------------------------------------------------------
# 2. IngestionResult contract — output shape the rest of pipeline expects
# ---------------------------------------------------------------------------


class TestIngestionResultContract:
    """IngestionResult has the fields and types downstream stages expect."""

    def _make_ingestion_result(self):
        from app.plugins.base import IngestionResult

        return IngestionResult(
            source_name="github",
            identifier="ada",
            evidence="Some evidence text",
            raw_data={"profile": {"login": "ada"}, "repos_summary": {}},
            stats={"repos_count": 0},
        )

    def test_source_name_is_string(self):
        result = self._make_ingestion_result()
        assert isinstance(result.source_name, str)
        assert result.source_name

    def test_identifier_is_string(self):
        result = self._make_ingestion_result()
        assert isinstance(result.identifier, str)

    def test_evidence_is_string(self):
        result = self._make_ingestion_result()
        assert isinstance(result.evidence, str)

    def test_raw_data_is_dict(self):
        result = self._make_ingestion_result()
        assert isinstance(result.raw_data, dict)

    def test_stats_is_dict(self):
        result = self._make_ingestion_result()
        assert isinstance(result.stats, dict)

    def test_raw_data_defaults_to_empty_dict(self):
        from app.plugins.base import IngestionResult

        result = IngestionResult(
            source_name="github",
            identifier="ada",
            evidence="",
        )
        assert result.raw_data == {}

    def test_stats_defaults_to_empty_dict(self):
        from app.plugins.base import IngestionResult

        result = IngestionResult(
            source_name="github",
            identifier="ada",
            evidence="",
        )
        assert result.stats == {}


# ---------------------------------------------------------------------------
# 3. ExplorerReport contract — pipeline accesses these fields
# ---------------------------------------------------------------------------


class TestExplorerReportContract:
    """ExplorerReport fields that pipeline.py / memory_assembler.py access."""

    REQUIRED_FIELDS = {
        "source_name",
        "personality_findings",
        "memory_entries",
        "behavioral_quotes",
        "context_evidence",
        "confidence_summary",
        "knowledge_graph",
        "principles",
    }

    def test_all_required_fields_present(self):
        from app.synthesis.explorers.base import ExplorerReport

        report = ExplorerReport(
            source_name="github",
            personality_findings="some findings",
        )
        for field in self.REQUIRED_FIELDS:
            assert hasattr(report, field), (
                f"ExplorerReport is missing field '{field}' — "
                f"pipeline.py or memory_assembler.py accesses it"
            )

    def test_memory_entries_is_list(self):
        from app.synthesis.explorers.base import ExplorerReport

        report = ExplorerReport(source_name="github", personality_findings="")
        assert isinstance(report.memory_entries, list)

    def test_behavioral_quotes_is_list(self):
        from app.synthesis.explorers.base import ExplorerReport

        report = ExplorerReport(source_name="github", personality_findings="")
        assert isinstance(report.behavioral_quotes, list)

    def test_context_evidence_is_dict(self):
        from app.synthesis.explorers.base import ExplorerReport

        report = ExplorerReport(source_name="github", personality_findings="")
        assert isinstance(report.context_evidence, dict)

    def test_source_name_is_string(self):
        from app.synthesis.explorers.base import ExplorerReport

        report = ExplorerReport(source_name="blog", personality_findings="")
        assert isinstance(report.source_name, str)
        assert report.source_name == "blog"

    def test_personality_findings_is_string(self):
        from app.synthesis.explorers.base import ExplorerReport

        report = ExplorerReport(source_name="github", personality_findings="findings text")
        assert isinstance(report.personality_findings, str)


class TestMemoryEntryContract:
    """MemoryEntry fields used by memory_assembler.py."""

    REQUIRED_FIELDS = {
        "category",
        "topic",
        "content",
        "confidence",
        "source_type",
        "evidence_quote",
    }

    def test_all_required_fields_present(self):
        from app.synthesis.explorers.base import MemoryEntry

        entry = MemoryEntry(
            category="expertise",
            topic="Python",
            content="Expert in Python",
            confidence=0.9,
            source_type="github",
        )
        for field in self.REQUIRED_FIELDS:
            assert hasattr(entry, field), f"MemoryEntry missing field: '{field}'"

    def test_confidence_between_0_and_1(self):
        from app.synthesis.explorers.base import MemoryEntry
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MemoryEntry(
                category="x",
                topic="y",
                content="z",
                confidence=1.5,  # invalid — must be <= 1.0
                source_type="github",
            )

    def test_evidence_quote_defaults_to_empty_string(self):
        from app.synthesis.explorers.base import MemoryEntry

        entry = MemoryEntry(
            category="x",
            topic="y",
            content="z",
            confidence=0.5,
            source_type="github",
        )
        assert entry.evidence_quote == ""


# ---------------------------------------------------------------------------
# 4. Explorer tool suite contract
# ---------------------------------------------------------------------------


EXPECTED_TOOL_NAMES = {
    "browse_evidence",
    "search_evidence",
    "read_item",
    "save_finding",
    "save_memory",
    "save_quote",
    "save_knowledge_node",
    "save_knowledge_edge",
    "save_principle",
    "mark_explored",
    "get_progress",
    "finish",
}


class TestExplorerToolSuiteContract:
    """build_explorer_tools() exposes the 12 documented tools with async handlers."""

    @pytest.fixture
    def tools(self):
        from app.synthesis.explorers.tools import build_explorer_tools

        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar_one_or_none.return_value = None
        result.scalar.return_value = 0
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()
        session.add = MagicMock()

        return build_explorer_tools(
            mini_id="contract-mini-id",
            source_type="github",
            db_session=session,
        )

    def test_returns_exactly_12_tools(self, tools):
        assert len(tools) == 12, f"Expected 12 tools, got {len(tools)}: {[t.name for t in tools]}"

    def test_all_expected_names_present(self, tools):
        names = {t.name for t in tools}
        missing = EXPECTED_TOOL_NAMES - names
        assert not missing, f"Missing tools: {missing}"

    def test_no_unexpected_tools(self, tools):
        names = {t.name for t in tools}
        extra = names - EXPECTED_TOOL_NAMES
        assert not extra, f"Unexpected tools added: {extra}"

    def test_all_handlers_are_async(self, tools):
        for tool in tools:
            assert inspect.iscoroutinefunction(tool.handler), (
                f"Tool '{tool.name}' handler is not async — PydanticAI requires async tool handlers"
            )

    def test_all_handlers_are_callable(self, tools):
        for tool in tools:
            assert callable(tool.handler), f"Tool '{tool.name}' handler is not callable"

    def test_all_tools_have_descriptions(self, tools):
        for tool in tools:
            assert tool.description, f"Tool '{tool.name}' has empty description"
            assert len(tool.description) > 5, (
                f"Tool '{tool.name}' description too short: {tool.description!r}"
            )

    def test_all_parameters_are_json_schema_objects(self, tools):
        import json as json_mod

        for tool in tools:
            assert isinstance(tool.parameters, dict), f"Tool '{tool.name}' parameters is not a dict"
            assert tool.parameters.get("type") == "object", (
                f"Tool '{tool.name}' parameters.type != 'object'"
            )
            # Must be JSON-serialisable
            try:
                json_mod.dumps(tool.parameters)
            except (TypeError, ValueError) as exc:
                pytest.fail(f"Tool '{tool.name}' parameters not JSON-serializable: {exc}")

    def test_write_tools_exist_for_all_save_operations(self, tools):
        """The 6 write tools (save_* family) must all be present."""
        save_tools = {t.name for t in tools if t.name.startswith("save_")}
        expected_save = {
            "save_finding",
            "save_memory",
            "save_quote",
            "save_knowledge_node",
            "save_knowledge_edge",
            "save_principle",
        }
        assert save_tools == expected_save, (
            f"save_* tools mismatch. Expected: {expected_save}, got: {save_tools}"
        )

    def test_finish_tool_has_summary_parameter(self, tools):
        finish = next(t for t in tools if t.name == "finish")
        assert "summary" in finish.parameters.get("properties", {}), (
            "finish tool must have 'summary' parameter — used by pipeline to store completion note"
        )

    def test_browse_evidence_has_source_type_param(self, tools):
        browse = next(t for t in tools if t.name == "browse_evidence")
        assert "source_type" in browse.parameters.get("properties", {}), (
            "browse_evidence must accept source_type parameter"
        )

    def test_save_finding_has_category_and_content_params(self, tools):
        save = next(t for t in tools if t.name == "save_finding")
        props = save.parameters.get("properties", {})
        assert "category" in props, "save_finding missing 'category' param"
        assert "content" in props, "save_finding missing 'content' param"


# ---------------------------------------------------------------------------
# 5. Pipeline stage boundary: PipelineEvent schema
# ---------------------------------------------------------------------------


class TestPipelineEventContract:
    """PipelineEvent schema matches what run_pipeline emits."""

    VALID_STAGES = {"fetch", "explore", "synthesize", "save", "error"}
    VALID_STATUSES = {"started", "completed", "failed", "progress"}

    def test_pipeline_event_constructable(self):
        from app.models.schemas import PipelineEvent

        event = PipelineEvent(
            stage="fetch",
            status="started",
            message="Starting fetch",
            progress=0.0,
        )
        assert event.stage == "fetch"
        assert event.status == "started"

    def test_pipeline_event_has_required_fields(self):
        from app.models.schemas import PipelineEvent

        event = PipelineEvent(
            stage="explore",
            status="completed",
            message="Done",
            progress=0.5,
        )
        assert hasattr(event, "stage")
        assert hasattr(event, "status")
        assert hasattr(event, "message")
        assert hasattr(event, "progress")
        assert hasattr(event, "error_code")

    def test_pipeline_event_stage_values_used_by_pipeline(self):
        """Verify the stages emitted by run_pipeline are valid PipelineEvent values."""
        from app.models.schemas import PipelineEvent

        # These are the exact stage strings emitted in pipeline.py
        for stage in self.VALID_STAGES:
            event = PipelineEvent(
                stage=stage,
                status="started",
                message="test",
                progress=0.0,
            )
            assert event.stage == stage
