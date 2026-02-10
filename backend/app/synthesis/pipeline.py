"""Pipeline orchestration: runs the full ingestion-to-spirit flow with progress events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mini import Mini
from app.models.schemas import PipelineEvent
from app.plugins.base import IngestionResult
from app.plugins.registry import registry
from app.synthesis.spirit import build_system_prompt, synthesize_spirit
from app.synthesis.values import extract_values

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

    Args:
        username: Primary identifier (GitHub username, etc.) to create a mini for.
        session_factory: Async session factory for database access.
        on_progress: Optional async callback for pipeline progress events.
        sources: List of ingestion source names to use. Defaults to ["github"].
    """
    emit = on_progress or _noop_callback
    source_names = sources or ["github"]

    try:
        # Stage 1: Fetch data from all requested sources
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

            progress = 0.05 + (0.2 * (i + 1) / len(source_names))
            await emit(PipelineEvent(
                stage="fetch", status="completed",
                message=f"Fetched data from {source_name}",
                progress=progress,
            ))

        if not results:
            raise ValueError(f"No data fetched from any source: {source_names}")

        # Stage 2: Combine evidence from all sources
        await emit(PipelineEvent(
            stage="format", status="started",
            message="Combining evidence from all sources...", progress=0.25,
        ))

        evidence_parts = [r.evidence for r in results if r.evidence]
        evidence = "\n\n---\n\n".join(evidence_parts)

        await emit(PipelineEvent(
            stage="format", status="completed",
            message=f"Combined {len(evidence)} characters of evidence "
                    f"from {len(results)} source(s)",
            progress=0.3,
        ))

        # Stage 3: Extract values
        await emit(PipelineEvent(
            stage="extract", status="started",
            message="Analyzing personality and values...", progress=0.35,
        ))

        values = await extract_values(username, evidence)

        await emit(PipelineEvent(
            stage="extract", status="completed",
            message=f"Extracted {len(values.engineering_values)} engineering values",
            progress=0.55,
        ))

        # Stage 4: Synthesize spirit
        await emit(PipelineEvent(
            stage="synthesize", status="started",
            message="Synthesizing personality document...", progress=0.6,
        ))

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

        spirit_content = await synthesize_spirit(username, display_name, bio, values)
        system_prompt = build_system_prompt(username, spirit_content)

        await emit(PipelineEvent(
            stage="synthesize", status="completed",
            message="Spirit document generated",
            progress=0.85,
        ))

        # Stage 5: Save to database
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
                mini.system_prompt = system_prompt
                mini.values_json = values.model_dump_json()
                mini.metadata_json = json.dumps(all_stats)
                mini.sources_used = json.dumps(
                    [r.source_name for r in results]
                )
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
