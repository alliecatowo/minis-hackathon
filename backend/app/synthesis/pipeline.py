"""Pipeline orchestration: runs the full ingestion-to-spirit flow with progress events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.formatter import format_evidence
from app.ingestion.github import fetch_github_data
from app.models.mini import Mini
from app.models.schemas import PipelineEvent
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
) -> None:
    """Run the full mini creation pipeline.

    Args:
        username: GitHub username to create a mini for.
        session_factory: Async session factory for database access.
        on_progress: Optional async callback for pipeline progress events.
    """
    emit = on_progress or _noop_callback

    try:
        # Stage 1: Fetch GitHub data
        await emit(PipelineEvent(
            stage="fetch", status="started",
            message="Fetching GitHub activity...", progress=0.0,
        ))

        github_data = await fetch_github_data(username)

        await emit(PipelineEvent(
            stage="fetch", status="completed",
            message=f"Fetched {len(github_data.commits)} commits, "
                    f"{len(github_data.pull_requests)} PRs, "
                    f"{len(github_data.review_comments)} reviews",
            progress=0.2,
        ))

        # Stage 2: Format evidence
        await emit(PipelineEvent(
            stage="format", status="started",
            message="Formatting evidence for analysis...", progress=0.25,
        ))

        evidence = format_evidence(github_data)

        await emit(PipelineEvent(
            stage="format", status="completed",
            message=f"Formatted {len(evidence)} characters of evidence",
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

        display_name = github_data.profile.get("name") or username
        bio = github_data.profile.get("bio") or ""
        avatar_url = github_data.profile.get("avatar_url") or ""

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
                mini.metadata_json = json.dumps({
                    "repos_count": len(github_data.repos),
                    "commits_analyzed": len(github_data.commits),
                    "prs_analyzed": len(github_data.pull_requests),
                    "reviews_analyzed": len(github_data.review_comments),
                    "issue_comments_analyzed": len(github_data.issue_comments),
                    "evidence_length": len(evidence),
                })
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
    username: str, session_factory: Any
) -> None:
    """Run pipeline and push events to the in-memory queue for SSE streaming."""
    queue = get_event_queue(username)

    async def push_event(event: PipelineEvent) -> None:
        await queue.put(event)

    await run_pipeline(username, session_factory, on_progress=push_event)

    # Signal completion
    await queue.put(None)
