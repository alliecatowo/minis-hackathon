"""Tests for backend/app/synthesis/pipeline.py.

Focuses on:
- _chunk_text helper
- _generate_embeddings helper (mocked)
- Progress event emission
- get_event_queue / cleanup_event_queue helpers
- run_pipeline_with_events structure
- run_pipeline error handling / stage flow (heavily mocked)
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import PipelineEvent
from app.synthesis.pipeline import (
    _build_structured_from_db,
    _chunk_text,
    _generate_embeddings,
    _noop_callback,
    cleanup_event_queue,
    get_event_queue,
    run_pipeline,
    run_pipeline_with_events,
)


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_empty_string_returns_empty_list(self):
        assert _chunk_text("") == []

    def test_single_short_paragraph(self):
        chunks = _chunk_text("Hello world")
        assert chunks == ["Hello world"]

    def test_splits_on_double_newlines(self):
        text = "First paragraph.\n\nSecond paragraph."
        chunks = _chunk_text(text, chunk_size=500)
        # Both fit in one chunk at size 500
        assert len(chunks) == 1
        assert "First paragraph." in chunks[0]
        assert "Second paragraph." in chunks[0]

    def test_splits_when_cumulative_exceeds_chunk_size(self):
        # Two paragraphs each 60 chars, chunk_size=80 → they should split
        para1 = "A" * 60
        para2 = "B" * 60
        text = f"{para1}\n\n{para2}"
        chunks = _chunk_text(text, chunk_size=80)
        assert len(chunks) == 2
        assert chunks[0] == para1
        assert chunks[1] == para2

    def test_hard_splits_single_oversized_paragraph(self):
        # A single paragraph larger than chunk_size must be hard-cut
        long_para = "X" * 1200
        chunks = _chunk_text(long_para, chunk_size=500)
        assert len(chunks) == 3  # 500 + 500 + 200
        assert all(len(c) <= 500 for c in chunks)

    def test_strips_empty_paragraphs(self):
        text = "\n\n\n\nHello\n\n\n\nWorld\n\n"
        chunks = _chunk_text(text, chunk_size=500)
        assert "Hello" in chunks[0]
        assert "World" in chunks[0]

    def test_preserves_content(self):
        content = "The quick brown fox.\n\nJumped over the lazy dog."
        chunks = _chunk_text(content, chunk_size=500)
        combined = "\n\n".join(chunks)
        assert "The quick brown fox." in combined
        assert "Jumped over the lazy dog." in combined

    def test_default_chunk_size_is_500(self):
        # Default chunk_size=500 — a 400-char text should be one chunk
        text = "Y" * 400
        chunks = _chunk_text(text)
        assert len(chunks) == 1

    def test_multiple_paragraphs_grouped_within_chunk(self):
        # Three small paragraphs should all fit in one chunk
        parts = ["short1", "short2", "short3"]
        text = "\n\n".join(parts)
        chunks = _chunk_text(text, chunk_size=500)
        assert len(chunks) == 1
        assert "short1" in chunks[0]
        assert "short3" in chunks[0]


# ---------------------------------------------------------------------------
# _generate_embeddings (embeddings module unavailable → no-op)
# ---------------------------------------------------------------------------


class TestGenerateEmbeddings:
    @pytest.mark.asyncio
    async def test_returns_without_error_when_embeddings_unavailable(self):
        """When _EMBEDDINGS_AVAILABLE is False the function returns silently."""
        session_factory = MagicMock()
        # Should not raise, regardless of input
        await _generate_embeddings(
            mini_id="test-id",
            memory_content="some memory",
            evidence_cache="some evidence",
            knowledge_graph_json=None,
            session_factory=session_factory,
        )
        # No interaction with session_factory expected
        session_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_empty_inputs_gracefully(self):
        await _generate_embeddings(
            mini_id="test-id",
            memory_content="",
            evidence_cache="",
            knowledge_graph_json=None,
            session_factory=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_processes_knowledge_graph_nodes_when_available(self):
        """With embeddings module mocked, processes KG nodes."""
        import app.synthesis.pipeline as pipeline_mod

        mock_embed = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
        mock_embedding_cls = MagicMock()

        # Build a fake session context manager
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.begin = MagicMock()
        mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield mock_session

        with (
            patch.object(pipeline_mod, "_EMBEDDINGS_AVAILABLE", True),
            patch.object(pipeline_mod, "embed_texts", mock_embed, create=True),
            patch.object(pipeline_mod, "Embedding", mock_embedding_cls, create=True),
        ):
            await _generate_embeddings(
                mini_id="mini-1",
                memory_content="memory text",
                evidence_cache="evidence text",
                knowledge_graph_json={
                    "nodes": [{"name": "Python", "description": "A programming language"}]
                },
                session_factory=fake_session_factory,
            )

        # embed_texts was called with 3 text chunks (memory, evidence, kg node)
        mock_embed.assert_awaited_once()
        call_args = mock_embed.call_args[0][0]
        assert any("memory text" in t for t in call_args)
        assert any("evidence text" in t for t in call_args)
        assert any("A programming language" in t for t in call_args)

    @pytest.mark.asyncio
    async def test_never_raises_on_exception(self):
        """Errors inside _generate_embeddings must not propagate."""
        import app.synthesis.pipeline as pipeline_mod

        with patch.object(pipeline_mod, "_EMBEDDINGS_AVAILABLE", True):
            with patch.object(
                pipeline_mod,
                "embed_texts",
                AsyncMock(side_effect=RuntimeError("boom")),
                create=True,
            ):
                # Must complete without raising
                await _generate_embeddings(
                    mini_id="bad-mini",
                    memory_content="stuff",
                    evidence_cache="",
                    knowledge_graph_json=None,
                    session_factory=MagicMock(),
                )


# ---------------------------------------------------------------------------
# _build_structured_from_db
# ---------------------------------------------------------------------------


class TestBuildStructuredFromDb:
    @pytest.mark.asyncio
    async def test_reconstructs_principle_evidence_provenance(self):
        finding = MagicMock()
        finding.category = "principle"
        finding.source_type = "github"
        finding.created_at = datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc)
        finding.content = json.dumps(
            {
                "trigger": "auth changes",
                "action": "request tests",
                "value": "security",
                "intensity": 9,
                "evidence": ["ev-1"],
                "evidence_ids": ["ev-1"],
                "evidence_provenance": [
                    {
                        "id": "ev-1",
                        "source_type": "github",
                        "item_type": "review",
                        "evidence_date": "2026-04-20T12:00:00+00:00",
                        "created_at": "2026-04-21T12:00:00+00:00",
                    }
                ],
                "source_type": "github",
                "source_dates": ["2026-04-20T12:00:00+00:00"],
                "support_count": 2,
            }
        )

        result = MagicMock()
        result.scalars.return_value.all.return_value = [finding]
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)

        @asynccontextmanager
        async def session_factory():
            yield session

        _, principles_json = await _build_structured_from_db("mini-1", session_factory)

        principle = principles_json["principles"][0]
        assert principle["evidence"] == ["ev-1"]
        assert principle["evidence_ids"] == ["ev-1"]
        assert principle["support_count"] == 2
        assert principle["source_type"] == "github"
        assert principle["source_dates"] == ["2026-04-20T12:00:00+00:00"]
        assert principle["evidence_provenance"] == [
            {
                "id": "ev-1",
                "source_type": "github",
                "item_type": "review",
                "evidence_date": "2026-04-20T12:00:00+00:00",
                "created_at": "2026-04-21T12:00:00+00:00",
            }
        ]


# ---------------------------------------------------------------------------
# _noop_callback
# ---------------------------------------------------------------------------


class TestNoopCallback:
    @pytest.mark.asyncio
    async def test_accepts_any_pipeline_event(self):
        event = PipelineEvent(stage="fetch", status="started", message="hi", progress=0.0)
        # Should not raise
        await _noop_callback(event)


# ---------------------------------------------------------------------------
# get_event_queue / cleanup_event_queue
# ---------------------------------------------------------------------------


class TestEventQueue:
    def test_creates_queue_for_new_mini_id(self):
        mini_id = "queue-test-1"
        cleanup_event_queue(mini_id)  # ensure clean state
        q = get_event_queue(mini_id)
        assert isinstance(q, asyncio.Queue)

    def test_returns_same_queue_for_same_mini_id(self):
        mini_id = "queue-test-2"
        cleanup_event_queue(mini_id)
        q1 = get_event_queue(mini_id)
        q2 = get_event_queue(mini_id)
        assert q1 is q2

    def test_cleanup_removes_queue(self):
        mini_id = "queue-test-3"
        cleanup_event_queue(mini_id)
        get_event_queue(mini_id)  # create it
        cleanup_event_queue(mini_id)
        # After cleanup a new queue object is created
        q_new = get_event_queue(mini_id)
        assert isinstance(q_new, asyncio.Queue)

    def test_cleanup_nonexistent_queue_is_safe(self):
        # Should not raise KeyError
        cleanup_event_queue("does-not-exist-xyz")


# ---------------------------------------------------------------------------
# run_pipeline_with_events — structure
# ---------------------------------------------------------------------------


class TestRunPipelineWithEvents:
    @pytest.mark.asyncio
    async def test_requires_mini_id(self):
        with pytest.raises(ValueError, match="mini_id is required"):
            await run_pipeline_with_events(
                username="torvalds",
                session_factory=MagicMock(),
                mini_id=None,
            )

    @pytest.mark.asyncio
    async def test_puts_none_sentinel_on_queue_after_pipeline(self):
        """A None sentinel must be put on the queue to signal completion."""
        mini_id = "events-test-mini-1"
        cleanup_event_queue(mini_id)

        # Patch run_pipeline to be a no-op so we don't need full DB
        with patch(
            "app.synthesis.pipeline.run_pipeline",
            new=AsyncMock(return_value=None),
        ):
            await run_pipeline_with_events(
                username="testuser",
                session_factory=MagicMock(),
                mini_id=mini_id,
            )

        queue = get_event_queue(mini_id)
        sentinel = queue.get_nowait()
        assert sentinel is None

        cleanup_event_queue(mini_id)


# ---------------------------------------------------------------------------
# run_pipeline — error handling
# ---------------------------------------------------------------------------


class TestRunPipelineErrorHandling:
    """Test that pipeline errors emit error events and update DB status."""

    def _make_session_factory(self, mini=None):
        """Build a session_factory that returns a mock session."""
        mock_session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mini
        mock_session.execute = AsyncMock(return_value=result)
        mock_session.add = MagicMock()

        @asynccontextmanager
        async def factory():
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            begin_ctx = MagicMock()
            begin_ctx.__aenter__ = AsyncMock(return_value=None)
            begin_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_session.begin = MagicMock(return_value=begin_ctx)

            yield mock_session

        return factory

    @pytest.mark.asyncio
    async def test_emits_error_event_on_no_data_fetched(self):
        """When all sources fail to fetch, an error event is emitted."""
        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent):
            events.append(event)

        # Registry returns a source that raises
        mock_source = MagicMock()

        async def _fail_fetch(*a, **kw):
            raise RuntimeError("network error")
            yield

        mock_source.fetch_items = _fail_fetch

        with (
            patch("app.synthesis.pipeline.registry") as mock_registry,
            patch(
                "app.synthesis.pipeline.select",
                return_value=MagicMock(),
            ),
        ):
            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="failuser",
                session_factory=self._make_session_factory(),
                on_progress=collect,
                sources=["github"],
            )

        error_events = [e for e in events if e.stage == "error"]
        assert len(error_events) >= 1
        assert "failed" in error_events[0].status.lower()
        assert error_events[0].error_code == "FETCH_GITHUB_RUNTIMEERROR"

    @pytest.mark.asyncio
    async def test_emits_fetch_started_event(self):
        """Fetch started event must be emitted before any fetch work."""
        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent):
            events.append(event)

        mock_source = MagicMock()

        async def _fail_early(*a, **kw):
            raise RuntimeError("fail early")
            yield

        mock_source.fetch_items = _fail_early

        with patch("app.synthesis.pipeline.registry") as mock_registry:
            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="testuser",
                session_factory=self._make_session_factory(),
                on_progress=collect,
                sources=["github"],
            )

        stages = [e.stage for e in events]
        assert "fetch" in stages
        fetch_started = next(
            (e for e in events if e.stage == "fetch" and e.status == "started"), None
        )
        assert fetch_started is not None

    @pytest.mark.asyncio
    async def test_updates_mini_status_to_failed_on_error(self):
        """When pipeline fails, mini.status should be set to 'failed'."""
        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent):
            events.append(event)

        mock_mini = MagicMock()
        mock_mini.status = "processing"

        mock_source = MagicMock()

        async def _boom1(*a, **kw):
            raise RuntimeError("boom")
            yield

        mock_source.fetch_items = _boom1

        with patch("app.synthesis.pipeline.registry") as mock_registry:
            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="failuser2",
                session_factory=self._make_session_factory(mini=mock_mini),
                on_progress=collect,
                sources=["github"],
            )

        assert mock_mini.status == "failed"

    @pytest.mark.asyncio
    async def test_no_progress_callback_uses_noop(self):
        """Omitting on_progress should not raise."""
        mock_source = MagicMock()

        async def _boom2(*a, **kw):
            raise RuntimeError("boom")
            yield

        mock_source.fetch_items = _boom2

        with patch("app.synthesis.pipeline.registry") as mock_registry:
            mock_registry.get_source.return_value = mock_source

            # Should complete without raising
            await run_pipeline(
                username="quietuser",
                session_factory=self._make_session_factory(),
                on_progress=None,
                sources=["github"],
            )

    @pytest.mark.asyncio
    async def test_unknown_source_is_skipped(self):
        """Sources not in the registry should be skipped gracefully."""
        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent):
            events.append(event)

        with patch("app.synthesis.pipeline.registry") as mock_registry:
            mock_registry.get_source.side_effect = KeyError("unknown_source")

            await run_pipeline(
                username="skipuser",
                session_factory=self._make_session_factory(),
                on_progress=collect,
                sources=["unknown_source"],
            )

        # Should emit error (no results)
        error_events = [e for e in events if e.stage == "error"]
        assert len(error_events) >= 1


# ---------------------------------------------------------------------------
# run_pipeline — happy path (fully mocked)
# ---------------------------------------------------------------------------


class TestRunPipelineHappyPath:
    """Tests for a successful pipeline run end-to-end (all LLM calls mocked)."""

    def _build_session_factory(self, mini):
        """Session factory that returns a mocked session with the given mini."""
        mock_session = MagicMock()

        # Repo config query returns no excluded repos
        cfg_result = MagicMock()
        cfg_result.scalars.return_value.all.return_value = []

        # Mini lookup result
        mini_result = MagicMock()
        mini_result.scalar_one_or_none.return_value = mini

        # Count result for revisions
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        # Track call count to return different results
        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            # First call: MiniRepoConfig query
            if call_count == 1:
                return cfg_result
            # Later calls: Mini query or count
            if "count" in str(stmt).lower():
                return count_result
            return mini_result

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
        mock_session.add = MagicMock()

        @asynccontextmanager
        async def factory():
            begin_ctx = MagicMock()
            begin_ctx.__aenter__ = AsyncMock(return_value=None)
            begin_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_session.begin = MagicMock(return_value=begin_ctx)
            yield mock_session

        return factory

    def _common_patches(self, soul_doc="Soul document content", system_prompt="System prompt"):
        """Return the common context-manager patches used by all happy-path tests."""
        mock_kg = MagicMock()
        mock_kg.model_dump.return_value = {}
        mock_principles = MagicMock()
        mock_principles.model_dump.return_value = {}

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
                AsyncMock(return_value=(1, 0)),
            ),
            patch(
                "app.synthesis.pipeline._build_structured_from_db",
                AsyncMock(return_value=({}, {})),
            ),
            patch(
                "app.synthesis.pipeline._build_synthetic_reports_from_db",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.synthesis.pipeline.build_system_prompt",
                return_value=system_prompt,
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
                return_value=mock_kg,
            ),
            patch(
                "app.synthesis.memory_assembler._merge_principles",
                return_value=mock_principles,
            ),
            patch("app.synthesis.pipeline._generate_embeddings", AsyncMock()),
        ]

    @pytest.mark.asyncio
    async def test_full_pipeline_emits_all_stages(self):
        """Happy path: fetch → explore → synthesize → save events all fired."""
        from app.plugins.base import EvidenceItem
        from app.synthesis.explorers.base import MemoryEntry
        from tests.conftest import make_report

        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent):
            events.append(event)

        mini = MagicMock()
        mini.id = "mini-happy-1"
        mini.spirit_content = None
        mini.system_prompt = None
        mini.memory_content = None
        mini.values_json = None

        explorer_report = make_report(
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

        mock_source = MagicMock()

        async def _fetch_happy1(*a, **kw):
            yield EvidenceItem(
                external_id="c:1", source_type="github", item_type="commit", content="test evidence"
            )

        mock_source.fetch_items = _fetch_happy1

        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(return_value=explorer_report)

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._common_patches():
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=self._build_session_factory(mini),
                on_progress=collect,
                sources=["github"],
                mini_id="mini-happy-1",
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
    async def test_pipeline_uses_source_identifiers(self):
        """source_identifiers override the default username per source."""
        from tests.conftest import make_report

        mini = MagicMock()
        mini.id = "mini-src-id-1"
        mini.spirit_content = None
        mini.system_prompt = None
        mini.memory_content = None
        mini.values_json = None

        explorer_report = make_report(source_name="hackernews")

        called_identifiers: list[str] = []
        mock_source = MagicMock()

        async def _fetch_srcid(identifier, *a, **kw):
            called_identifiers.append(identifier)
            from app.plugins.base import EvidenceItem

            yield EvidenceItem(
                external_id="hn:1",
                source_type="hackernews",
                item_type="comment",
                content="hn evidence",
            )

        mock_source.fetch_items = _fetch_srcid

        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(return_value=explorer_report)

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._common_patches(soul_doc="Soul"):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["hackernews"]

            await run_pipeline(
                username="ghuser",
                session_factory=self._build_session_factory(mini),
                sources=["hackernews"],
                mini_id="mini-src-id-1",
                source_identifiers={"hackernews": "pg"},
            )

        # fetch_items was called with "pg", not "ghuser"
        assert called_identifiers and called_identifiers[0] == "pg"

    @pytest.mark.asyncio
    async def test_pipeline_sets_mini_status_to_ready(self):
        """After successful pipeline mini.status must be 'ready'."""
        from app.plugins.base import EvidenceItem
        from tests.conftest import make_report

        mini = MagicMock()
        mini.id = "mini-ready-1"
        mini.spirit_content = None
        mini.system_prompt = None
        mini.memory_content = None
        mini.values_json = None

        explorer_report = make_report(source_name="github")

        mock_source = MagicMock()

        async def _fetch_ready(*a, **kw):
            yield EvidenceItem(
                external_id="c:1", source_type="github", item_type="commit", content="evidence"
            )

        mock_source.fetch_items = _fetch_ready

        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(return_value=explorer_report)

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._common_patches(soul_doc="Soul doc"):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="readyuser",
                session_factory=self._build_session_factory(mini),
                sources=["github"],
                mini_id="mini-ready-1",
            )

        assert mini.status == "ready"

    @pytest.mark.asyncio
    async def test_pipeline_no_explorer_reports_raises(self):
        """When no explorer produces a report, pipeline should emit error."""
        from app.plugins.base import EvidenceItem

        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent):
            events.append(event)

        mini = MagicMock()
        mini.id = "mini-noexp-1"
        mini.spirit_content = None
        mini.system_prompt = None
        mini.memory_content = None
        mini.values_json = None

        mock_source = MagicMock()

        async def _fetch_items_noexp(*a, **kw):
            yield EvidenceItem(
                external_id="c:1", source_type="github", item_type="commit", content="evidence"
            )

        mock_source.fetch_items = _fetch_items_noexp

        with (
            patch("app.synthesis.pipeline.registry") as mock_registry,
            patch(
                "app.synthesis.pipeline.get_explorer",
                side_effect=KeyError("no explorer"),
            ),
            patch(
                "app.synthesis.pipeline._store_evidence_items_in_db",
                AsyncMock(return_value=(1, 0)),
            ),
        ):
            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="noexpuser",
                session_factory=self._build_session_factory(mini),
                on_progress=collect,
                sources=["github"],
                mini_id="mini-noexp-1",
            )

        error_events = [e for e in events if e.stage == "error"]
        assert len(error_events) >= 1
