"""Pipeline orchestration: runs the full ingestion-to-spirit flow with progress events.

The pipeline produces two documents:
1. Spirit Document — personality engram (soul document from chief synthesizer)
2. Memory Document — factual knowledge assembled from explorer reports

Both are stored on the Mini and used together at chat time.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select

from app.models.mini import Mini
from app.models.schemas import PipelineEvent
from app.plugins.base import IngestionResult
from app.plugins.registry import registry
from app.synthesis.chief import run_chief_synthesis
from app.synthesis.explorers import get_explorer
from app.synthesis.explorers.base import ExplorerReport
from app.synthesis.memory_assembler import assemble_memory, extract_values_json
from app.synthesis.spirit import build_system_prompt

# Import explorer modules to trigger registration
import app.synthesis.explorers.github_explorer  # noqa: F401
import app.synthesis.explorers.claude_code_explorer  # noqa: F401
import app.synthesis.explorers.blog_explorer  # noqa: F401
import app.synthesis.explorers.hackernews_explorer  # noqa: F401
import app.synthesis.explorers.stackoverflow_explorer  # noqa: F401
import app.synthesis.explorers.devto_explorer  # noqa: F401

logger = logging.getLogger(__name__)

# Type alias for progress callbacks
ProgressCallback = Callable[[PipelineEvent], Coroutine[Any, Any, None]]


async def _noop_callback(event: PipelineEvent) -> None:
    pass


async def run_pipeline(
    username: str,
    session_factory: Any,
    on_progress: ProgressCallback | None = None,
    sources: list[str] | None = None,
    owner_id: int | None = None,
) -> None:
    """Run the full mini creation pipeline.

    Stages:
    1. FETCH — get data from ingestion sources
    2. EXPLORE — launch explorer agents per source in parallel
    3. ASSEMBLE MEMORY — pure-Python memory assembly from reports
    4. SYNTHESIZE — chief synthesizer crafts soul document
    5. SAVE — persist to database

    Args:
        username: Primary identifier (GitHub username, etc.) to create a mini for.
        session_factory: Async session factory for database access.
        on_progress: Optional async callback for pipeline progress events.
        sources: List of ingestion source names to use. Defaults to ["github"].
        owner_id: Optional owner ID for user-specific data directories.
    """
    emit = on_progress or _noop_callback
    source_names = sources or ["github"]

    try:
        # ── Stage 1: FETCH ───────────────────────────────────────────────
        await emit(PipelineEvent(
            stage="fetch", status="started",
            message=f"Fetching data from {', '.join(source_names)}...",
            progress=0.0,
        ))

        results: list[IngestionResult] = []
        all_stats: dict[str, Any] = {}

        for i, source_name in enumerate(source_names):
            try:
                source = registry.get_source(source_name)
            except KeyError:
                logger.warning("Unknown source: %s, skipping", source_name)
                continue

            if source_name == "claude_code" and owner_id is not None:
                result = await source.fetch(username, data_dir=f"data/uploads/{owner_id}/claude_code")
            else:
                result = await source.fetch(username)
            results.append(result)
            all_stats[source_name] = result.stats

            progress = 0.05 + (0.15 * (i + 1) / len(source_names))
            await emit(PipelineEvent(
                stage="fetch", status="completed",
                message=f"Fetched data from {source_name}",
                progress=progress,
            ))

        if not results:
            raise ValueError(f"No data fetched from any source: {source_names}")

        # Cache evidence for chat tools
        evidence_cache = "\n\n---\n\n".join(r.evidence for r in results if r.evidence)

        # ── Stage 2: EXPLORE ─────────────────────────────────────────────
        await emit(PipelineEvent(
            stage="explore", status="started",
            message=f"Launching {len(results)} explorer agent(s)...",
            progress=0.2,
        ))

        explorer_tasks = []
        explorer_source_names = []

        for ingestion_result in results:
            source_name = ingestion_result.source_name
            try:
                explorer = get_explorer(source_name)
            except KeyError:
                logger.warning(
                    "No explorer registered for source '%s', skipping exploration",
                    source_name,
                )
                continue

            explorer_tasks.append(
                explorer.explore(
                    username,
                    ingestion_result.evidence,
                    ingestion_result.raw_data,
                )
            )
            explorer_source_names.append(source_name)

        # Run all explorers in parallel
        explorer_reports: list[ExplorerReport] = []
        if explorer_tasks:
            completed = await asyncio.gather(*explorer_tasks, return_exceptions=True)
            for i, result_or_exc in enumerate(completed):
                if isinstance(result_or_exc, Exception):
                    logger.error(
                        "Explorer '%s' failed: %s",
                        explorer_source_names[i],
                        result_or_exc,
                    )
                else:
                    explorer_reports.append(result_or_exc)

        await emit(PipelineEvent(
            stage="explore", status="completed",
            message=f"Exploration complete: {len(explorer_reports)} report(s) from "
                    f"{', '.join(r.source_name for r in explorer_reports)}",
            progress=0.5,
        ))

        if not explorer_reports:
            raise ValueError("No explorer reports produced — cannot synthesize")

        # ── Stage 3: ASSEMBLE MEMORY ─────────────────────────────────────
        await emit(PipelineEvent(
            stage="assemble", status="started",
            message="Assembling memory from explorer reports...",
            progress=0.5,
        ))

        memory_content = assemble_memory(explorer_reports, username)
        values_json = extract_values_json(explorer_reports)

        await emit(PipelineEvent(
            stage="assemble", status="completed",
            message=f"Memory assembled ({len(memory_content)} chars)",
            progress=0.6,
        ))

        # ── Stage 4: SYNTHESIZE ──────────────────────────────────────────
        await emit(PipelineEvent(
            stage="synthesize", status="started",
            message="Chief synthesizer crafting soul document...",
            progress=0.6,
        ))

        spirit_content = await run_chief_synthesis(username, explorer_reports)

        # Extract profile info from the first source that has it (prefer github)
        display_name = username
        bio = ""
        avatar_url = ""
        for r in results:
            profile = r.raw_data.get("profile", {})
            if profile:
                display_name = profile.get("name") or display_name
                bio = profile.get("bio") or bio
                avatar_url = profile.get("avatar_url") or avatar_url
                break

        system_prompt = build_system_prompt(username, spirit_content, memory_content)

        await emit(PipelineEvent(
            stage="synthesize", status="completed",
            message="Soul document generated",
            progress=0.9,
        ))

        # ── Stage 5: SAVE ────────────────────────────────────────────────
        await emit(PipelineEvent(
            stage="save", status="started",
            message="Saving mini...", progress=0.9,
        ))

        async with session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(Mini).where(Mini.username == username)
                )
                mini = result.scalar_one_or_none()

                if mini is None:
                    logger.error("Mini not found for username %s during save", username)
                    return

                mini.display_name = display_name
                mini.avatar_url = avatar_url
                mini.bio = bio
                mini.spirit_content = spirit_content
                mini.memory_content = memory_content
                mini.system_prompt = system_prompt
                mini.values_json = values_json
                mini.metadata_json = json.dumps(all_stats)
                mini.sources_used = json.dumps(
                    [r.source_name for r in results]
                )
                mini.evidence_cache = evidence_cache
                mini.status = "ready"

        await emit(PipelineEvent(
            stage="save", status="completed",
            message="Mini is ready!",
            progress=1.0,
        ))

    except Exception as e:
        logger.exception("Pipeline failed for %s: %s", username, e)
        await emit(PipelineEvent(
            stage="error", status="failed",
            message=f"Pipeline failed: {str(e)}", progress=0.0,
        ))

        # Update status to failed in DB
        try:
            async with session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        select(Mini).where(Mini.username == username)
                    )
                    mini = result.scalar_one_or_none()
                    if mini:
                        mini.status = "failed"
        except Exception:
            logger.exception("Failed to update mini status to failed for %s", username)


# In-memory store for pipeline events (keyed by username)
# Used by SSE endpoints to stream progress to clients
_pipeline_events: dict[str, asyncio.Queue[PipelineEvent | None]] = {}


def get_event_queue(username: str) -> asyncio.Queue[PipelineEvent | None]:
    """Get or create an event queue for a username's pipeline."""
    if username not in _pipeline_events:
        _pipeline_events[username] = asyncio.Queue()
    return _pipeline_events[username]


def cleanup_event_queue(username: str) -> None:
    """Remove the event queue for a username."""
    _pipeline_events.pop(username, None)


async def run_pipeline_with_events(
    username: str,
    session_factory: Any,
    sources: list[str] | None = None,
    owner_id: int | None = None,
) -> None:
    """Run pipeline and push events to the in-memory queue for SSE streaming."""
    queue = get_event_queue(username)

    async def push_event(event: PipelineEvent) -> None:
        await queue.put(event)

    await run_pipeline(
        username, session_factory, on_progress=push_event, sources=sources, owner_id=owner_id
    )

    # Signal completion
    await queue.put(None)
