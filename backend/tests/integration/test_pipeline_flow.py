"""Integration tests: verify data flow across the three pipeline stages.

Tests in this module drive the pipeline with mocked HTTP + LLM, using
real in-memory logic for the FETCH → EXPLORE → SYNTHESIZE boundaries.
They assert on observable side-effects that exercise the stage contracts:

  - Evidence rows exist after FETCH
  - ExplorerProgress reaches "completed" after EXPLORE
  - MiniRevision / system_prompt populated after SYNTHESIZE

All external I/O (GitHub API, LLM calls) is fully mocked.
No real DB connection is required — the mocked session_factory tracks
inserts in-memory and surfaces them for assertions.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import PipelineEvent
from app.plugins.base import EvidenceItem, IngestionResult
from app.synthesis.explorers.base import ExplorerReport, MemoryEntry
from app.synthesis.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# In-memory session helpers
# ---------------------------------------------------------------------------


class InMemorySession:
    """Minimal in-memory SQLAlchemy session substitute.

    Tracks ``add()`` calls so tests can inspect persisted objects.
    Does NOT support real queries — ``execute()`` always returns an empty result.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self._begin_ctx: "_BeginCtx | None" = None

    async def execute(self, stmt: Any) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar_one_or_none.return_value = None
        result.scalar.return_value = 0
        result.scalar_one.return_value = 0
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    def begin(self) -> "_BeginCtx":
        self._begin_ctx = _BeginCtx()
        return self._begin_ctx


class _BeginCtx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: Any) -> None:
        return None


def make_session_factory(extra_execute_side_effect=None):
    """Build a session_factory that yields an InMemorySession.

    Returns (factory, shared_session) so tests can inspect what was persisted.
    """
    session = InMemorySession()

    @asynccontextmanager
    async def factory():
        yield session

    return factory, session


# ---------------------------------------------------------------------------
# Helpers for mock mini objects
# ---------------------------------------------------------------------------


def make_mock_mini(mini_id: str = "mini-flow-1") -> MagicMock:
    mini = MagicMock()
    mini.id = mini_id
    mini.spirit_content = None
    mini.system_prompt = None
    mini.memory_content = None
    mini.values_json = None
    mini.status = "processing"
    return mini


def build_pipeline_session_factory(mini: MagicMock):
    """Build a session factory whose execute() returns the given mini."""
    session = MagicMock()

    cfg_result = MagicMock()
    cfg_result.scalars.return_value.all.return_value = []

    mini_result = MagicMock()
    mini_result.scalar_one_or_none.return_value = mini

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return cfg_result
        if "count" in str(stmt).lower():
            return count_result
        return mini_result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    session.add = MagicMock()

    @asynccontextmanager
    async def factory():
        begin_ctx = MagicMock()
        begin_ctx.__aenter__ = AsyncMock(return_value=None)
        begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=begin_ctx)
        yield session

    return factory


# ---------------------------------------------------------------------------
# 3. Stage boundary: fetch_items output contract
# ---------------------------------------------------------------------------


class TestFetchOutputContract:
    """GitHubSource.fetch_items() emits EvidenceItems with expected structure."""

    @pytest.mark.asyncio
    async def test_github_fetch_items_yields_evidence_items(self):
        from app.ingestion.github import GitHubData
        from app.plugins.sources.github import GitHubSource

        github_data = GitHubData(
            profile={"login": "ada", "name": "Ada", "bio": "Dev", "avatar_url": "http://x.com/img"},
            repos=[],
            commits=[
                {
                    "sha": "abc123",
                    "commit": {"message": "init commit", "author": {"name": "Ada"}},
                    "repository": {"full_name": "ada/engine"},
                }
            ],
            pull_requests=[],
            review_comments=[],
            issue_comments=[],
            pull_request_reviews=[],
            repo_languages={"ada/engine": {"Python": 1000}},
            commit_diffs=[],
            pr_review_threads=[],
            issue_threads=[],
        )

        with patch(
            "app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)
        ):
            source = GitHubSource()
            items = [
                item async for item in source.fetch_items("ada", mini_id="test-mini", session=None)
            ]

        assert len(items) >= 1
        for item in items:
            assert isinstance(item, EvidenceItem)
            assert item.external_id
            assert item.source_type == "github"
            assert item.content
        commit_items = [i for i in items if i.item_type == "commit"]
        assert commit_items, "expected at least one commit item"
        assert all(i.context == "commit_message" for i in commit_items)

    @pytest.mark.asyncio
    async def test_github_fetch_items_empty_data_yields_nothing(self):
        from app.ingestion.github import GitHubData
        from app.plugins.sources.github import GitHubSource

        github_data = GitHubData()

        with patch(
            "app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)
        ):
            source = GitHubSource()
            items = [
                item
                async for item in source.fetch_items("nobody", mini_id="test-mini", session=None)
            ]

        assert items == []


# ---------------------------------------------------------------------------
# 4. GitHubData field coverage (ALLIE-368 regression guard)
# ---------------------------------------------------------------------------


class TestGitHubDataFieldCoverage:
    """Every field accessed by GitHubSource must exist on GitHubData."""

    ACCESSED_FIELDS = {
        # Direct attribute access in GitHubSource.fetch_items() and helpers
        "profile",
        "repos",
        "commits",
        "pull_requests",
        "review_comments",
        "issue_comments",
        "pull_request_reviews",
        "repo_languages",
        "commit_diffs",
        "pr_review_threads",
        "issue_threads",
    }

    def test_all_accessed_fields_exist_on_githubdata_dataclass(self):
        import dataclasses
        from app.ingestion.github import GitHubData

        dc_fields = {f.name for f in dataclasses.fields(GitHubData)}
        missing = self.ACCESSED_FIELDS - dc_fields
        assert not missing, (
            f"GitHubData is missing fields accessed by GitHubSource: {missing}\n"
            "This is a regression of ALLIE-368 — add the missing field(s) to the dataclass."
        )

    def test_all_accessed_fields_have_sensible_defaults(self):
        from app.ingestion.github import GitHubData

        # Should be constructible with no arguments (all have defaults)
        try:
            obj = GitHubData()
        except TypeError as e:
            pytest.fail(f"GitHubData() construction without args failed: {e}")

        for field in self.ACCESSED_FIELDS:
            val = getattr(obj, field)
            # Should be a falsy but valid empty collection, not None
            assert val is not None, (
                f"GitHubData.{field} default is None — should be empty collection"
            )

    def test_repo_languages_is_dict(self):
        from app.ingestion.github import GitHubData

        data = GitHubData()
        assert isinstance(data.repo_languages, dict), (
            "GitHubData.repo_languages must be a dict — "
            "_aggregate_languages() iterates .values() on it"
        )

    def test_list_fields_are_lists(self):
        from app.ingestion.github import GitHubData

        data = GitHubData()
        list_fields = [
            "repos",
            "commits",
            "pull_requests",
            "review_comments",
            "issue_comments",
            "pull_request_reviews",
            "commit_diffs",
            "pr_review_threads",
            "issue_threads",
        ]
        for field in list_fields:
            val = getattr(data, field)
            assert isinstance(val, list), (
                f"GitHubData.{field} should default to a list, got {type(val).__name__}"
            )


# ---------------------------------------------------------------------------
# 5. End-to-end dry-run through run_pipeline (all external I/O mocked)
# ---------------------------------------------------------------------------


class TestPipelineDryRun:
    """Drive run_pipeline through all stages with mocked sources and LLM."""

    def _make_patches(self, soul_doc="Soul content", system_prompt_text="System prompt"):
        """Common patches needed for a full pipeline run."""
        return [
            patch(
                "app.synthesis.pipeline.run_chief_synthesizer",
                AsyncMock(return_value=soul_doc),
            ),
            patch(
                "app.synthesis.pipeline.run_chief_synthesis",
                AsyncMock(return_value=soul_doc),
            ),
            patch(
                "app.synthesis.pipeline._store_evidence_items_in_db",
                AsyncMock(return_value=(3, 0)),
            ),
            patch(
                "app.synthesis.pipeline._build_structured_from_db",
                AsyncMock(return_value=({"nodes": [], "edges": []}, {"principles": []})),
            ),
            patch(
                "app.synthesis.pipeline._build_synthetic_reports_from_db",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.synthesis.pipeline.build_soul_prompt",
                return_value=system_prompt_text,
            ),
            patch(
                "app.synthesis.pipeline.build_full_system_prompt",
                return_value=system_prompt_text,
            ),
            patch(
                "app.synthesis.memory_assembler.extract_values_json",
                return_value='{"values": []}',
            ),
            patch(
                "app.synthesis.memory_assembler.extract_roles_llm",
                AsyncMock(return_value='{"roles": []}'),
            ),
            patch(
                "app.synthesis.memory_assembler.extract_skills_llm",
                AsyncMock(return_value='{"skills": []}'),
            ),
            patch(
                "app.synthesis.memory_assembler.extract_traits_llm",
                AsyncMock(return_value='{"traits": []}'),
            ),
            patch(
                "app.synthesis.memory_assembler._merge_knowledge_graphs",
                return_value=MagicMock(model_dump=lambda **kw: {}),
            ),
            patch(
                "app.synthesis.memory_assembler._merge_principles",
                return_value=MagicMock(model_dump=lambda **kw: {}),
            ),
            patch("app.synthesis.pipeline._generate_embeddings", AsyncMock()),
        ]

    def _make_ingestion_result(self, source_name: str = "github") -> IngestionResult:
        return IngestionResult(
            source_name=source_name,
            identifier="testuser",
            evidence="## GitHub Profile\nTest user\n\n## Commits\nAdd feature",
            raw_data={
                "profile": {"name": "Test User", "bio": "Dev", "avatar_url": "http://x.com/img"},
                "repos_summary": {
                    "languages": {},
                    "primary_languages": {},
                    "repo_count": 1,
                    "top_repos": [],
                },
                "pull_requests_full": [],
                "review_comments_full": [],
                "issue_comments_full": [],
                "pull_request_reviews_full": [],
                "commits_full": [],
                "commit_diffs": [],
                "pr_review_threads": [],
                "issue_threads": [],
            },
        )

    @pytest.mark.asyncio
    async def test_all_pipeline_stages_emit_events(self):
        """Happy path: every stage emits started + completed events."""
        from contextlib import ExitStack

        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent) -> None:
            events.append(event)

        mini = make_mock_mini("mini-dryrun-1")
        mock_source = MagicMock()

        async def _fake_fetch_items(*args, **kwargs):
            yield EvidenceItem(
                external_id="commit:abc123",
                source_type="github",
                item_type="commit",
                content="init commit",
                context="commit_message",
            )

        mock_source.fetch_items = _fake_fetch_items
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(
                source_name="github",
                personality_findings="Likes clean code",
                memory_entries=[
                    MemoryEntry(
                        category="expertise",
                        topic="Python",
                        content="Uses Python",
                        confidence=0.9,
                        source_type="github",
                    )
                ],
            )
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches(soul_doc="Soul doc", system_prompt_text="## System"):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                on_progress=collect,
                sources=["github"],
                mini_id="mini-dryrun-1",
            )

        stage_statuses = {(e.stage, e.status) for e in events}
        assert ("fetch", "started") in stage_statuses
        assert ("fetch", "completed") in stage_statuses
        assert ("explore", "started") in stage_statuses
        assert ("explore", "completed") in stage_statuses
        assert ("synthesize", "started") in stage_statuses
        assert ("synthesize", "completed") in stage_statuses
        assert ("save", "started") in stage_statuses
        assert ("save", "completed") in stage_statuses

    @pytest.mark.asyncio
    async def test_mini_status_becomes_ready_after_success(self):
        """After a successful pipeline run, mini.status == 'ready'."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-2")
        mock_source = MagicMock()

        async def _fetch_items_dryrun2(*a, **kw):
            yield EvidenceItem(
                external_id="c:1",
                source_type="github",
                item_type="commit",
                content="x",
                context="commit_message",
            )

        mock_source.fetch_items = _fetch_items_dryrun2
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches():
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-2",
            )

        assert mini.status == "ready"

    @pytest.mark.asyncio
    async def test_system_prompt_set_after_synthesize(self):
        """mini.system_prompt is populated after a successful run."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-3")
        mock_source = MagicMock()

        async def _fetch_items_dryrun3(*a, **kw):
            yield EvidenceItem(
                external_id="c:1",
                source_type="github",
                item_type="commit",
                content="x",
                context="commit_message",
            )

        mock_source.fetch_items = _fetch_items_dryrun3
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches(system_prompt_text="You are Ada."):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-3",
            )

        assert mini.system_prompt == "You are Ada."

    @pytest.mark.asyncio
    async def test_spirit_content_set_after_synthesize(self):
        """mini.spirit_content is populated with the chief's soul doc."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-4")
        mock_source = MagicMock()

        async def _fetch_items_dryrun4(*a, **kw):
            yield EvidenceItem(
                external_id="c:1",
                source_type="github",
                item_type="commit",
                content="x",
                context="commit_message",
            )

        mock_source.fetch_items = _fetch_items_dryrun4
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches(soul_doc="The soul of Ada."):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-4",
            )

        assert mini.spirit_content == "The soul of Ada."

    @pytest.mark.asyncio
    async def test_source_fetch_items_called_with_identifier(self):
        """fetch_items is called with the correct per-source identifier."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-5")
        mock_source = MagicMock()
        called_with: list[str] = []

        async def _fetch_items_dryrun5(identifier, *args, **kwargs):
            called_with.append(identifier)
            yield EvidenceItem(
                external_id="hn:1",
                source_type="hackernews",
                item_type="comment",
                content="x",
                context="hackernews_comment",
            )

        mock_source.fetch_items = _fetch_items_dryrun5
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="hackernews", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches():
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="ghuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["hackernews"],
                mini_id="mini-dryrun-5",
                source_identifiers={"hackernews": "hn-user"},
            )

        # Should have been called with "hn-user", not "ghuser"
        assert called_with and called_with[0] == "hn-user"

    @pytest.mark.asyncio
    async def test_failed_source_emits_error_event(self):
        """When all sources fail, the pipeline emits an error event."""
        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent) -> None:
            events.append(event)

        mock_source = MagicMock()

        async def _failing_fetch_items(*a, **kw):
            raise RuntimeError("network failure")
            yield  # make it an async generator

        mock_source.fetch_items = _failing_fetch_items

        with patch("app.synthesis.pipeline.registry") as mock_registry:
            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="failuser",
                session_factory=build_pipeline_session_factory(make_mock_mini()),
                on_progress=collect,
                sources=["github"],
            )

        error_events = [e for e in events if e.stage == "error"]
        assert len(error_events) >= 1

    @pytest.mark.asyncio
    async def test_evidence_items_stored_in_db_called_per_source(self):
        """_store_evidence_items_in_db must be called once per source with evidence."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-6")
        mock_source = MagicMock()

        async def _fetch_items_dryrun6(*a, **kw):
            yield EvidenceItem(
                external_id="c:abc",
                source_type="github",
                item_type="commit",
                content="init",
                context="commit_message",
            )

        mock_source.fetch_items = _fetch_items_dryrun6
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        store_calls: list[dict] = []

        async def mock_store(mini_id, source_name, items, session_factory, **kwargs):
            store_calls.append({"mini_id": mini_id, "source_name": source_name})
            return (len(items), 0)

        # Build patches manually, replacing _store_evidence_items_in_db with our spy
        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            stack.enter_context(
                patch("app.synthesis.pipeline._store_evidence_items_in_db", mock_store)
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline.run_chief_synthesizer",
                    AsyncMock(return_value="Soul doc"),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline.run_chief_synthesis",
                    AsyncMock(return_value="Soul doc"),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline._build_structured_from_db",
                    AsyncMock(return_value=({"nodes": [], "edges": []}, {"principles": []})),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline._build_synthetic_reports_from_db",
                    AsyncMock(return_value=[]),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline.build_soul_prompt",
                    return_value="System prompt",
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline.build_full_system_prompt",
                    return_value="System prompt",
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_values_json",
                    return_value='{"values": []}',
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_roles_llm",
                    AsyncMock(return_value='{"roles": []}'),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_skills_llm",
                    AsyncMock(return_value='{"skills": []}'),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_traits_llm",
                    AsyncMock(return_value='{"traits": []}'),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler._merge_knowledge_graphs",
                    return_value=MagicMock(model_dump=lambda **kw: {}),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler._merge_principles",
                    return_value=MagicMock(model_dump=lambda **kw: {}),
                )
            )
            stack.enter_context(patch("app.synthesis.pipeline._generate_embeddings", AsyncMock()))

            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-6",
            )

        assert len(store_calls) == 1
        assert store_calls[0]["source_name"] == "github"
        assert store_calls[0]["mini_id"] == "mini-dryrun-6"
