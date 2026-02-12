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
from app.synthesis.memory_assembler import (
    _merge_knowledge_graphs,
    _merge_principles,
    assemble_memory,
    extract_roles_llm,
    extract_skills_llm,
    extract_traits_llm,
    extract_values_json,
)
from app.synthesis.spirit import build_system_prompt

# Import explorer modules to trigger registration
import app.synthesis.explorers.github_explorer  # noqa: F401
import app.synthesis.explorers.claude_code_explorer  # noqa: F401
import app.synthesis.explorers.blog_explorer  # noqa: F401
import app.synthesis.explorers.hackernews_explorer  # noqa: F401
import app.synthesis.explorers.stackoverflow_explorer  # noqa: F401
import app.synthesis.explorers.devto_explorer  # noqa: F401
import app.synthesis.explorers.website_explorer  # noqa: F401

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
    owner_id: str | None = None,
    mini_id: str | None = None,
    source_identifiers: dict[str, str] | None = None,
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
        mini_id: The database ID of the Mini record to update.
        source_identifiers: Per-source identifiers (e.g. {"hackernews": "pg"}).
    """
    emit = on_progress or _noop_callback
    source_names = sources or ["github"]

    # ── Langfuse tracing (no-op when disabled) ────────────────────────
    trace = None
    langfuse_client = None
    try:
        from app.core.config import settings as _settings
        if _settings.langfuse_enabled:
            from langfuse import Langfuse
            langfuse_client = Langfuse()
            trace = langfuse_client.trace(
                name="mini_creation_pipeline",
                user_id=username,
                metadata={"sources": source_names, "mini_id": mini_id},
            )
    except Exception:
        logger.debug("Langfuse tracing unavailable, continuing without it")
        trace = None

    try:
        # ── Stage 1: FETCH ───────────────────────────────────────────────
        if trace:
            fetch_span = trace.span(name="fetch", metadata={"sources": source_names})
        await emit(PipelineEvent(
            stage="fetch", status="started",
            message=f"Fetching data from {', '.join(source_names)}...",
            progress=0.0,
        ))

        results: list[IngestionResult] = []
        all_stats: dict[str, Any] = {}

        # Load excluded repos for this mini
        excluded_repos: set[str] = set()
        if mini_id is not None:
            from app.models.ingestion_data import MiniRepoConfig

            async with session_factory() as _cfg_session:
                cfg_result = await _cfg_session.execute(
                    select(MiniRepoConfig).where(
                        MiniRepoConfig.mini_id == mini_id,
                        MiniRepoConfig.included == False,  # noqa: E712
                    )
                )
                excluded_repos = {c.repo_full_name for c in cfg_result.scalars().all()}

        for i, source_name in enumerate(source_names):
            try:
                source = registry.get_source(source_name)
            except KeyError:
                logger.warning("Unknown source: %s, skipping", source_name)
                continue

            # Use per-source identifier if provided, otherwise fall back to username
            identifier = username
            if source_identifiers:
                identifier = source_identifiers.get(source_name, username)

            # Build kwargs — pass mini_id + session for caching when available
            fetch_kwargs: dict[str, Any] = {}
            if mini_id is not None:
                fetch_kwargs["mini_id"] = mini_id
            if source_name == "claude_code" and owner_id is not None:
                fetch_kwargs["data_dir"] = f"data/uploads/{owner_id}/claude_code"

            # Use a dedicated session for sources that support caching
            if mini_id is not None:
                async with session_factory() as fetch_session:
                    async with fetch_session.begin():
                        fetch_kwargs["session"] = fetch_session
                        result = await source.fetch(identifier, **fetch_kwargs)
            else:
                result = await source.fetch(identifier, **fetch_kwargs)

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

        # Filter out excluded repos from evidence
        if excluded_repos:
            for r in results:
                if r.source_name == "github" and r.raw_data.get("repos_summary"):
                    r.raw_data["repos_summary"]["top_repos"] = [
                        repo for repo in r.raw_data["repos_summary"].get("top_repos", [])
                        if repo.get("full_name") not in excluded_repos
                    ]

        # Cache evidence for chat tools
        evidence_cache = "\n\n---\n\n".join(r.evidence for r in results if r.evidence)

        if trace:
            fetch_span.end()

        # ── Stage 2: EXPLORE ─────────────────────────────────────────────
        if trace:
            explore_span = trace.span(name="explore", metadata={"explorer_count": len(results)})
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

        if trace:
            explore_span.end()

        # ── Stage 3: ASSEMBLE MEMORY ─────────────────────────────────────
        if trace:
            assemble_span = trace.span(name="assemble_memory", metadata={"report_count": len(explorer_reports)})
        await emit(PipelineEvent(
            stage="assemble", status="started",
            message="Assembling memory from explorer reports...",
            progress=0.5,
        ))

        memory_content = assemble_memory(explorer_reports, username)
        values_json = extract_values_json(explorer_reports)
        roles_json, skills_json, traits_json = await asyncio.gather(
            extract_roles_llm(explorer_reports),
            extract_skills_llm(explorer_reports),
            extract_traits_llm(explorer_reports),
        )

        # Persist structured knowledge graph and principles
        merged_kg = _merge_knowledge_graphs(explorer_reports)
        merged_principles = _merge_principles(explorer_reports)
        kg_json = merged_kg.model_dump(mode="json")
        principles_json = merged_principles.model_dump(mode="json")

        await emit(PipelineEvent(
            stage="assemble", status="completed",
            message=f"Memory assembled ({len(memory_content)} chars)",
            progress=0.55,
        ))

        if trace:
            assemble_span.end()

        # ── Stage 4: SYNTHESIZE ──────────────────────────────────────────
        if trace:
            synthesize_span = trace.span(name="synthesize")
        await emit(PipelineEvent(
            stage="synthesize", status="started",
            message="Chief synthesizer crafting soul document...",
            progress=0.6,
        ))

        # Collect context evidence from all explorer reports to pass to chief
        all_context_evidence: dict[str, list[str]] = {}
        for report in explorer_reports:
            for ctx_key, ctx_quotes in report.context_evidence.items():
                all_context_evidence.setdefault(ctx_key, []).extend(ctx_quotes)

        spirit_content = await run_chief_synthesis(
            username, explorer_reports,
            context_evidence=all_context_evidence if all_context_evidence else None,
        )

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

        if trace:
            synthesize_span.end()

        # ── Stage 5: SAVE ────────────────────────────────────────────────
        if trace:
            save_span = trace.span(name="save")
        await emit(PipelineEvent(
            stage="save", status="started",
            message="Saving mini...", progress=0.9,
        ))

        async with session_factory() as session:
            async with session.begin():
                if mini_id is not None:
                    result = await session.execute(
                        select(Mini).where(Mini.id == mini_id)
                    )
                else:
                    result = await session.execute(
                        select(Mini).where(Mini.username == username)
                    )
                mini = result.scalar_one_or_none()

                if mini is None:
                    logger.error("Mini not found (id=%s, username=%s) during save", mini_id, username)
                    return

                # Snapshot current state as a revision before overwriting
                if mini.spirit_content or mini.system_prompt:
                    from app.models.revision import MiniRevision

                    from sqlalchemy import func as sa_func

                    rev_count_result = await session.execute(
                        select(sa_func.count())
                        .select_from(MiniRevision)
                        .where(MiniRevision.mini_id == mini.id)
                    )
                    next_rev = rev_count_result.scalar_one() + 1
                    trigger = "initial" if next_rev == 1 else "manual_retrain"

                    session.add(MiniRevision(
                        mini_id=mini.id,
                        revision_number=next_rev,
                        spirit_content=mini.spirit_content,
                        memory_content=mini.memory_content,
                        system_prompt=mini.system_prompt,
                        values_json=json.dumps(mini.values_json) if isinstance(mini.values_json, (dict, list)) else mini.values_json,
                        trigger=trigger,
                    ))

                mini.display_name = display_name
                mini.avatar_url = avatar_url
                mini.bio = bio
                mini.spirit_content = spirit_content
                mini.memory_content = memory_content
                mini.system_prompt = system_prompt
                mini.values_json = json.loads(values_json) if isinstance(values_json, str) else values_json
                mini.roles_json = json.loads(roles_json) if isinstance(roles_json, str) else roles_json
                mini.skills_json = json.loads(skills_json) if isinstance(skills_json, str) else skills_json
                mini.traits_json = json.loads(traits_json) if isinstance(traits_json, str) else traits_json
                mini.knowledge_graph_json = kg_json
                mini.principles_json = principles_json
                mini.metadata_json = all_stats
                mini.sources_used = [r.source_name for r in results]
                mini.evidence_cache = evidence_cache
                mini.status = "ready"

        if trace:
            save_span.end()

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
                    if mini_id is not None:
                        result = await session.execute(
                            select(Mini).where(Mini.id == mini_id)
                        )
                    else:
                        result = await session.execute(
                            select(Mini).where(Mini.username == username)
                        )
                    mini = result.scalar_one_or_none()
                    if mini:
                        mini.status = "failed"
        except Exception:
            logger.exception("Failed to update mini status to failed for %s", username)

    finally:
        if langfuse_client:
            langfuse_client.flush()


# In-memory store for pipeline events (keyed by mini_id)
# Used by SSE endpoints to stream progress to clients
_pipeline_events: dict[str, asyncio.Queue[PipelineEvent | None]] = {}


def get_event_queue(mini_id: str) -> asyncio.Queue[PipelineEvent | None]:
    """Get or create an event queue for a mini's pipeline."""
    if mini_id not in _pipeline_events:
        _pipeline_events[mini_id] = asyncio.Queue()
    return _pipeline_events[mini_id]


def cleanup_event_queue(mini_id: str) -> None:
    """Remove the event queue for a mini."""
    _pipeline_events.pop(mini_id, None)


async def run_pipeline_with_events(
    username: str,
    session_factory: Any,
    sources: list[str] | None = None,
    owner_id: str | None = None,
    mini_id: str | None = None,
    source_identifiers: dict[str, str] | None = None,
) -> None:
    """Run pipeline and push events to the in-memory queue for SSE streaming."""
    if mini_id is None:
        raise ValueError("mini_id is required for run_pipeline_with_events")
    queue = get_event_queue(mini_id)

    async def push_event(event: PipelineEvent) -> None:
        await queue.put(event)

    await run_pipeline(
        username, session_factory, on_progress=push_event, sources=sources,
        owner_id=owner_id, mini_id=mini_id,
        source_identifiers=source_identifiers,
    )

    # Signal completion
    await queue.put(None)
