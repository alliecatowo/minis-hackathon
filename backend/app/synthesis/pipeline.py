"""Pipeline orchestration: FETCH → EXPLORE → SYNTHESIZE with SSE progress.

Three stages:
1. FETCH — Ingest raw data from sources, store as Evidence DB records
2. EXPLORE — Parallel PydanticAI agents analyze evidence via tools.py
3. SYNTHESIZE — Chief synthesizer crafts soul document from DB findings
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.ingestion.delta import get_latest_external_ids
from app.ingestion.hashing import hash_evidence_content
from app.models.evidence import Evidence, ExplorerProgress
from app.models.mini import Mini
from app.models.schemas import PipelineEvent
from app.plugins.base import EvidenceItem, IngestionResult
from app.plugins.registry import registry
from app.synthesis.explorers import get_explorer
from app.synthesis.explorers.base import ExplorerReport
from app.synthesis.spirit import build_system_prompt

# Chief synthesizer — DB-driven version is preferred; legacy fallback for tests
try:
    from app.synthesis.chief import run_chief_synthesizer, run_chief_synthesis
except ImportError:  # pragma: no cover

    async def run_chief_synthesizer(mini_id, db_session, **kwargs):  # type: ignore[misc]
        raise NotImplementedError("Chief synthesizer not available")

    async def run_chief_synthesis(username, reports, **kwargs):  # type: ignore[misc]
        raise NotImplementedError("Chief synthesizer not available")


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


def _evidence_item_envelope(item: EvidenceItem) -> dict[str, object]:
    return {
        "source_uri": item.source_uri,
        "author_id": item.author_id,
        "audience_id": item.audience_id,
        "target_id": item.target_id,
        "scope": item.scope,
        "raw_body": item.raw_body,
        "raw_body_ref": item.raw_body_ref,
        "raw_context": item.raw_context,
        "provenance": item.provenance,
    }


def _evidence_item_hash_metadata(item: EvidenceItem) -> dict[str, object]:
    hash_metadata: dict[str, object] = dict(item.metadata or {})
    hash_metadata["_context"] = item.context
    envelope = {
        key: value for key, value in _evidence_item_envelope(item).items() if value is not None
    }
    if envelope:
        hash_metadata["_envelope"] = envelope
    return hash_metadata


# ── Token budget (ALLIE-405) ─────────────────────────────────────────────────


class TokenBudgetExceeded(Exception):
    """Raised when a pipeline run exceeds its cumulative token budget."""

    pass


class TokenBudget:
    """Track cumulative token usage across all pipeline stages.

    Hard cap is enforced after every update; soft cap is checked per-agent
    (exceeding it marks that agent as failed but lets the pipeline continue).
    """

    def __init__(self, hard_cap: int, soft_cap: int, mini_id: str | None = None) -> None:
        self.hard_cap = hard_cap
        self.soft_cap = soft_cap
        self.mini_id = mini_id
        self._total_in = 0
        self._total_out = 0

    @property
    def total_tokens(self) -> int:
        return self._total_in + self._total_out

    def record(self, tokens_in: int, tokens_out: int, source: str = "unknown") -> None:
        """Add tokens from a completed agent call and enforce the hard cap."""
        self._total_in += tokens_in
        self._total_out += tokens_out
        logger.info(
            "token_budget source=%s tokens_in=%d tokens_out=%d cumulative=%d hard_cap=%d",
            source,
            tokens_in,
            tokens_out,
            self.total_tokens,
            self.hard_cap,
        )
        if self.total_tokens > self.hard_cap:
            logger.error(
                "token_budget HARD_CAP_EXCEEDED mini_id=%s cumulative=%d hard_cap=%d",
                self.mini_id,
                self.total_tokens,
                self.hard_cap,
            )
            raise TokenBudgetExceeded(
                f"Token budget exceeded: {self.total_tokens} > {self.hard_cap} "
                f"(mini_id={self.mini_id})"
            )

    def check_soft_cap(self, source: str = "unknown") -> bool:
        """Return True if cumulative tokens have exceeded the per-agent soft cap."""
        if self.total_tokens > self.soft_cap:
            logger.warning(
                "token_budget SOFT_CAP_EXCEEDED source=%s cumulative=%d soft_cap=%d",
                source,
                self.total_tokens,
                self.soft_cap,
            )
            return True
        return False


# ---------------------------------------------------------------------------
# Defensive imports for the embeddings module (built by a parallel agent).
# If the module isn't available yet, _EMBEDDINGS_AVAILABLE stays False and
# embedding generation is silently skipped.
# ---------------------------------------------------------------------------
_EMBEDDINGS_AVAILABLE = False
try:
    from app.core.embeddings import embed_texts  # type: ignore[import]
    from app.models.embeddings import Embedding  # type: ignore[import]

    _EMBEDDINGS_AVAILABLE = True
except ImportError:
    logger.debug("Embeddings module not available; skipping embedding generation")


def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split *text* into chunks of at most *chunk_size* characters.

    Tries to split on paragraph boundaries first, then sentence boundaries,
    then hard-cuts at *chunk_size*.
    """
    if not text:
        return []
    # Split on double-newlines (paragraphs) first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > chunk_size and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        # If a single paragraph exceeds chunk_size, hard-split it
        if len(para) > chunk_size:
            for i in range(0, len(para), chunk_size):
                chunks.append(para[i : i + chunk_size])
        else:
            current.append(para)
            current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


async def _generate_embeddings(
    mini_id: str,
    memory_content: str,
    evidence_cache: str,
    knowledge_graph_json: dict | None,
    session_factory: Any,
) -> None:
    """Generate and persist embeddings for a mini after the SAVE stage.

    This function never raises — any failure is logged as a warning so it
    cannot block pipeline completion.
    """
    if not _EMBEDDINGS_AVAILABLE:
        return
    try:
        chunks_with_type: list[tuple[str, str]] = []

        # Memory chunks
        for chunk in _chunk_text(memory_content or ""):
            chunks_with_type.append((chunk, "memory"))

        # Evidence chunks
        for chunk in _chunk_text(evidence_cache or ""):
            chunks_with_type.append((chunk, "evidence"))

        # Knowledge graph node descriptions
        if knowledge_graph_json:
            nodes = knowledge_graph_json.get("nodes", [])
            for node in nodes:
                description = node.get("description") or node.get("name") or ""
                if description.strip():
                    chunks_with_type.append((description.strip(), "knowledge_node"))

        if not chunks_with_type:
            return

        texts = [c for c, _ in chunks_with_type]
        source_types = [t for _, t in chunks_with_type]

        # Embed all texts in one call (implementation may batch internally)
        vectors = await embed_texts(texts)

        async with session_factory() as session:
            async with session.begin():
                # Delete existing embeddings for this mini (re-train scenario)
                from sqlalchemy import delete as sa_delete

                await session.execute(sa_delete(Embedding).where(Embedding.mini_id == mini_id))
                for text, source_type, vector in zip(texts, source_types, vectors):
                    session.add(
                        Embedding(
                            mini_id=mini_id,
                            source_type=source_type,
                            content=text,
                            embedding=vector,
                        )
                    )

        logger.info(
            "Stored %d embeddings for mini %s (%s memory, %s evidence, %s kg)",
            len(chunks_with_type),
            mini_id,
            sum(1 for _, t in chunks_with_type if t == "memory"),
            sum(1 for _, t in chunks_with_type if t == "evidence"),
            sum(1 for _, t in chunks_with_type if t == "knowledge_node"),
        )

    except Exception:
        logger.warning(
            "Embedding generation failed for mini %s — continuing without embeddings",
            mini_id,
            exc_info=True,
        )


async def _store_evidence_items_in_db(
    mini_id: str,
    source_name: str,
    items: list[EvidenceItem],
    session_factory: Any,
) -> tuple[int, int]:
    """Upsert a list of EvidenceItem objects into the Evidence table.

    For each item:
    - If no row with that (mini_id, source_type, external_id) exists → INSERT.
    - If a row exists and the content_hash differs → UPDATE content, content_hash,
      last_fetched_at, source_privacy.
    - If a row exists and the hash is unchanged → UPDATE last_fetched_at only
      (touch the timestamp so delta queries stay accurate).

    Also upserts an ExplorerProgress row for the source.

    Returns:
        (inserted_count, updated_count)
    """
    now = datetime.now(timezone.utc)
    inserted = 0
    updated = 0

    async with session_factory() as session:
        async with session.begin():
            for item in items:
                hash_metadata = _evidence_item_hash_metadata(item)
                new_hash = hash_evidence_content(item.content, metadata=hash_metadata)

                # Check for existing row
                stmt = select(Evidence).where(
                    Evidence.mini_id == mini_id,
                    Evidence.source_type == item.source_type,
                    Evidence.external_id == item.external_id,
                )
                existing = (await session.execute(stmt)).scalar_one_or_none()

                if existing is None:
                    session.add(
                        Evidence(
                            mini_id=mini_id,
                            source_type=item.source_type,
                            item_type=item.item_type,
                            content=item.content,
                            context=item.context,
                            metadata_json=item.metadata,
                            source_privacy=item.privacy,
                            retention_policy=item.retention_policy,
                            retention_expires_at=item.retention_expires_at,
                            source_authorization=item.source_authorization,
                            authorization_revoked_at=item.authorization_revoked_at,
                            access_classification=item.access_classification or item.privacy,
                            lifecycle_audit_json=item.lifecycle_audit,
                            source_uri=item.source_uri,
                            author_id=item.author_id,
                            audience_id=item.audience_id,
                            target_id=item.target_id,
                            scope_json=item.scope,
                            raw_body=item.raw_body,
                            raw_body_ref=item.raw_body_ref,
                            raw_context_json=item.raw_context,
                            provenance_json=item.provenance,
                            external_id=item.external_id,
                            evidence_date=item.evidence_date,
                            last_fetched_at=now,
                            content_hash=new_hash,
                        )
                    )
                    inserted += 1
                elif existing.content_hash != new_hash:
                    existing.content = item.content
                    existing.context = item.context
                    existing.content_hash = new_hash
                    existing.evidence_date = item.evidence_date
                    existing.last_fetched_at = now
                    existing.source_privacy = item.privacy
                    existing.retention_policy = item.retention_policy
                    existing.retention_expires_at = item.retention_expires_at
                    existing.source_authorization = item.source_authorization
                    existing.authorization_revoked_at = item.authorization_revoked_at
                    existing.access_classification = item.access_classification or item.privacy
                    existing.lifecycle_audit_json = item.lifecycle_audit
                    existing.metadata_json = item.metadata
                    existing.source_uri = item.source_uri
                    existing.author_id = item.author_id
                    existing.audience_id = item.audience_id
                    existing.target_id = item.target_id
                    existing.scope_json = item.scope
                    existing.raw_body = item.raw_body
                    existing.raw_body_ref = item.raw_body_ref
                    existing.raw_context_json = item.raw_context
                    existing.provenance_json = item.provenance
                    existing.explored = False  # re-explore mutated items
                    updated += 1
                else:
                    # Unchanged — just refresh timestamp
                    existing.last_fetched_at = now

            # Upsert ExplorerProgress
            prog = ExplorerProgress(
                mini_id=mini_id,
                source_type=source_name,
                total_items=len(items),
                status="pending",
            )
            session.add(prog)

    return inserted, updated


async def _build_structured_from_db(
    mini_id: str,
    session_factory: Any,
) -> tuple[dict, dict]:
    """Reconstruct knowledge graph and principles dicts from DB findings.

    Returns (kg_json, principles_json) dicts compatible with the Mini model.
    """
    from app.models.evidence import ExplorerFinding
    from app.models.knowledge import (
        KnowledgeEdge,
        KnowledgeGraph,
        KnowledgeNode,
        NodeType,
        Principle,
        PrinciplesMatrix,
        RelationType,
    )

    kg = KnowledgeGraph()
    pm = PrinciplesMatrix()
    principle_payloads: list[dict[str, Any]] = []

    async with session_factory() as session:
        stmt = select(ExplorerFinding).where(
            ExplorerFinding.mini_id == mini_id,
            ExplorerFinding.category.in_(["knowledge_node", "knowledge_edge", "principle"]),
        )
        rows = await session.execute(stmt)
        findings = rows.scalars().all()

    for f in findings:
        try:
            data = json.loads(f.content)
        except (json.JSONDecodeError, TypeError):
            continue

        if f.category == "knowledge_node":
            try:
                node = KnowledgeNode(
                    id=data.get("name", "").lower().replace(" ", "-"),
                    name=data.get("name", ""),
                    type=NodeType(data.get("type", "skill")),
                    depth=data.get("depth", 0.5),
                    confidence=data.get("confidence", 0.5),
                )
                kg.nodes.append(node)
            except Exception:
                pass
        elif f.category == "knowledge_edge":
            try:
                edge = KnowledgeEdge(
                    source=data.get("source", ""),
                    target=data.get("target", ""),
                    relation=RelationType(data.get("relation", "related_to")),
                    weight=data.get("weight", 0.5),
                )
                kg.edges.append(edge)
            except Exception:
                pass
        elif f.category == "principle":
            try:
                evidence = _dedupe_json_strings(
                    _json_string_list(data.get("evidence_ids"))
                    + _json_string_list(data.get("evidence"))
                )
                evidence_provenance = _json_dict_list(data.get("evidence_provenance"))
                source_dates = _principle_source_dates(
                    data.get("source_dates"),
                    evidence_provenance,
                )
                support_count = _principle_support_count(
                    data.get("support_count"),
                    evidence,
                    evidence_provenance,
                )
                p = Principle(
                    trigger=data.get("trigger", ""),
                    action=data.get("action", ""),
                    value=data.get("value", ""),
                    intensity=float(data.get("intensity", 5)) / 10.0,
                    evidence=evidence,
                )
                pm.principles.append(p)
                payload = p.model_dump(mode="json")
                payload.update(
                    {
                        "evidence_ids": evidence,
                        "evidence_provenance": evidence_provenance,
                        "source_type": data.get("source_type") or f.source_type,
                        "source_dates": source_dates,
                        "support_count": support_count,
                    }
                )
                principle_payloads.append(payload)
            except Exception:
                pass

    principles_json = pm.model_dump(mode="json")
    principles_json["principles"] = principle_payloads
    return kg.model_dump(mode="json"), principles_json


def _json_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _json_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe_json_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _principle_source_dates(
    stored_dates: Any,
    evidence_provenance: list[dict[str, Any]],
) -> list[str]:
    dates = _json_string_list(stored_dates)
    for provenance in evidence_provenance:
        evidence_date = provenance.get("evidence_date")
        created_at = provenance.get("created_at")
        if isinstance(evidence_date, str) and evidence_date:
            dates.append(evidence_date)
        elif isinstance(created_at, str) and created_at:
            dates.append(created_at)
    return _dedupe_json_strings(dates)


def _principle_support_count(
    stored_count: Any,
    evidence: list[str],
    evidence_provenance: list[dict[str, Any]],
) -> int:
    try:
        parsed_count = int(stored_count)
    except (TypeError, ValueError):
        parsed_count = 0
    return max(parsed_count, len(evidence), len(evidence_provenance))


async def _build_synthetic_reports_from_db(
    mini_id: str,
    session_factory: Any,
) -> list["ExplorerReport"]:
    """Build ExplorerReport objects from DB findings, quotes, and context evidence.

    Used so that extract_roles_llm / extract_skills_llm / extract_traits_llm
    (which expect ExplorerReport lists) can process DB-persisted findings.

    ALLIE-440: Previously this function dropped ExplorerQuote rows and
    context_evidence buckets, so behavioral quotes never reached the extractor
    layer. Now it reconstructs the full ExplorerReport including:
    - behavioral_quotes from ExplorerQuote rows
    - context_evidence buckets from Evidence.context column (ALLIE-428)
    """
    from app.models.evidence import Evidence, ExplorerFinding, ExplorerQuote
    from app.synthesis.explorers.base import ExplorerReport, MemoryEntry

    async with session_factory() as session:
        # Fetch findings
        findings_stmt = select(ExplorerFinding).where(
            ExplorerFinding.mini_id == mini_id,
        )
        findings_rows = await session.execute(findings_stmt)
        findings = findings_rows.scalars().all()

        # Fetch quotes (ALLIE-440)
        quotes_stmt = select(ExplorerQuote).where(
            ExplorerQuote.mini_id == mini_id,
        )
        quotes_rows = await session.execute(quotes_stmt)
        quotes = quotes_rows.scalars().all()

        # Fetch evidence context buckets (ALLIE-440 + ALLIE-428)
        # Only non-default context values carry signal worth passing downstream
        evidence_stmt = select(Evidence.source_type, Evidence.context, Evidence.content).where(
            Evidence.mini_id == mini_id,
            Evidence.context != "general",
        )
        evidence_rows = await session.execute(evidence_stmt)
        context_evidence_rows = evidence_rows.all()

    # Early exit only when there's nothing at all
    if not findings and not quotes and not context_evidence_rows:
        return []

    # Group by source_type
    by_source_findings: dict[str, list] = {}
    for f in findings:
        by_source_findings.setdefault(f.source_type, []).append(f)

    by_source_quotes: dict[str, list] = {}
    for q in quotes:
        by_source_quotes.setdefault(q.source_type, []).append(q)

    by_source_context: dict[str, dict[str, list[str]]] = {}
    for row in context_evidence_rows:
        src = row.source_type
        ctx = row.context
        # Use a short excerpt from the evidence content as the quote
        excerpt = (row.content or "")[:500]
        by_source_context.setdefault(src, {}).setdefault(ctx, []).append(excerpt)

    # Merge all source keys
    all_sources = set(by_source_findings) | set(by_source_quotes) | set(by_source_context)

    reports: list[ExplorerReport] = []
    for source_type in all_sources:
        source_findings = by_source_findings.get(source_type, [])
        source_quotes = by_source_quotes.get(source_type, [])
        source_context = by_source_context.get(source_type, {})

        personality_parts: list[str] = []
        memory_entries: list[MemoryEntry] = []

        for f in source_findings:
            if f.category.startswith("memory:"):
                try:
                    data = json.loads(f.content)
                    text = data.get("text", f.content)
                    cat = f.category.replace("memory:", "")
                    memory_entries.append(
                        MemoryEntry(
                            category=cat,
                            topic="",
                            content=text,
                            confidence=f.confidence,
                            source_type=source_type,
                        )
                    )
                except (json.JSONDecodeError, TypeError):
                    memory_entries.append(
                        MemoryEntry(
                            category=f.category,
                            topic="",
                            content=f.content,
                            confidence=f.confidence,
                            source_type=source_type,
                        )
                    )
            elif f.category in ("knowledge_node", "knowledge_edge", "principle"):
                # These are handled separately in _build_structured_from_db
                pass
            else:
                personality_parts.append(f"[{f.category}] {f.content}")

        # Reconstruct behavioral_quotes from DB ExplorerQuote rows (ALLIE-440)
        behavioral_quotes = [
            {
                "context": q.context or "",
                "quote": q.quote,
                "signal_type": q.significance or "behavioral",
            }
            for q in source_quotes
        ]

        reports.append(
            ExplorerReport(
                source_name=source_type,
                personality_findings="\n\n".join(personality_parts),
                memory_entries=memory_entries,
                behavioral_quotes=behavioral_quotes,
                context_evidence=source_context,
                confidence_summary=(
                    f"DB-backed: {len(source_findings)} findings, "
                    f"{len(source_quotes)} quotes, "
                    f"{sum(len(v) for v in source_context.values())} context items"
                ),
            )
        )

    return reports


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
    3. SYNTHESIZE — chief synthesizer crafts soul document + save

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

    # ── Source expansion (ALLIE-370) ─────────────────────────────────────────
    # When NO sources are provided at all (the default), automatically run ALL
    # available sources — this fixes the quality gap where only GitHub was used.
    # When sources are explicitly provided in the request, honor that list.
    if sources is None:
        # Auto-expand to all registered sources (with graceful not-found handling)
        all_possible_sources = registry.list_sources()
        # Remove the explicit default, start fresh with all available sources
        source_names = all_possible_sources if all_possible_sources else ["github"]

        # Only include review_outcomes if ReviewCycle records with human outcomes exist
        if "review_outcomes" in source_names:
            if mini_id:
                from app.models.evidence import ReviewCycle

                async with session_factory() as check_session:
                    stmt = (
                        select(ReviewCycle)
                        .where(
                            ReviewCycle.mini_id == mini_id,
                            ReviewCycle.human_review_outcome.is_not(None),
                        )
                        .limit(1)
                    )
                    res = await check_session.execute(stmt)
                    if not res.scalar_one_or_none():
                        source_names = [s for s in source_names if s != "review_outcomes"]
            else:
                # No mini_id yet (initial creation), exclude review_outcomes
                source_names = [s for s in source_names if s != "review_outcomes"]

        logger.info(
            "auto-expanding sources from default to %s for username=%s",
            source_names,
            username,
        )
    else:
        # User explicitly specified sources — honor their selection
        source_names = list(sources)

    # ── Token budget (ALLIE-405) ──────────────────────────────────────
    from app.core.config import settings as _budget_settings

    _token_budget = TokenBudget(
        hard_cap=_budget_settings.max_pipeline_tokens_per_mini,
        soft_cap=_budget_settings.max_agent_tokens,
        mini_id=mini_id,
    )

    # ── Langfuse tracing (no-op when disabled) ────────────────────────
    trace = None
    langfuse_client = None
    try:
        from app.core.feature_flags import FLAGS

        if FLAGS["LANGFUSE_ENABLED"].is_enabled():
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
        await emit(
            PipelineEvent(
                stage="fetch",
                status="started",
                message=f"Fetching data from {', '.join(source_names)}...",
                progress=0.0,
            )
        )

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

            # Use per-source identifier if provided, otherwise fall back to username.
            # claude_code uses a data_dir path as identifier when owner_id is set.
            identifier = username
            if source_identifiers:
                identifier = source_identifiers.get(source_name, username)
            if source_name == "claude_code" and owner_id is not None:
                identifier = f"data/uploads/{owner_id}/claude_code"

            # ── Fetch structured items and store in DB ────────────────────────
            try:
                since_ids: set[str] = set()
                if mini_id is not None:
                    async with session_factory() as fetch_session:
                        async with fetch_session.begin():
                            since_ids = await get_latest_external_ids(
                                fetch_session, mini_id, source_name
                            )

                collected: list[EvidenceItem] = []
                if mini_id is not None:
                    async with session_factory() as item_session:
                        async with item_session.begin():
                            async for item in source.fetch_items(
                                identifier,
                                mini_id,
                                item_session,
                                since_external_ids=since_ids,
                            ):
                                collected.append(item)
                else:
                    async for item in source.fetch_items(
                        identifier,
                        mini_id="",
                        session=None,
                        since_external_ids=since_ids,
                    ):
                        collected.append(item)

                inserted = 0
                updated = 0
                if mini_id is not None and collected:
                    inserted, updated = await _store_evidence_items_in_db(
                        mini_id=mini_id,
                        source_name=source_name,
                        items=collected,
                        session_factory=session_factory,
                    )
                    logger.info(
                        "Fetch for '%s' (mini %s): %d inserted, %d updated, %d skipped (unchanged)",
                        source_name,
                        mini_id,
                        inserted,
                        updated,
                        len(since_ids),
                    )

                # Build a synthetic IngestionResult so the rest of the pipeline
                # (explorer wiring, evidence_cache) still works unchanged.
                combined_evidence = "\n\n---\n\n".join(
                    item.content for item in collected if item.content
                )
                result = IngestionResult(
                    source_name=source_name,
                    identifier=identifier,
                    evidence=combined_evidence,
                    stats={
                        "items_inserted": inserted,
                        "items_updated": updated,
                        "items_skipped": len(since_ids),
                        "items_total": len(collected),
                    },
                )
                results.append(result)
                all_stats[source_name] = result.stats

            except Exception as e:
                logger.warning(
                    "Fetch for source '%s' failed for %s: %s — skipping",
                    source_name,
                    identifier,
                    e,
                )
                continue

            progress = 0.05 + (0.15 * (i + 1) / len(source_names))
            await emit(
                PipelineEvent(
                    stage="fetch",
                    status="completed",
                    message=f"Fetched data from {source_name}",
                    progress=progress,
                )
            )

        if not results:
            raise ValueError(f"No data fetched from any source: {source_names}")

        # Filter out excluded repos from evidence
        if excluded_repos:
            for r in results:
                if r.source_name == "github" and r.raw_data.get("repos_summary"):
                    r.raw_data["repos_summary"]["top_repos"] = [
                        repo
                        for repo in r.raw_data["repos_summary"].get("top_repos", [])
                        if repo.get("full_name") not in excluded_repos
                    ]

        # Cache evidence for chat tools
        evidence_cache = "\n\n---\n\n".join(r.evidence for r in results if r.evidence)

        if trace:
            fetch_span.end()

        # ── Stage 2: EXPLORE ─────────────────────────────────────────────
        if trace:
            explore_span = trace.span(name="explore", metadata={"explorer_count": len(results)})
        await emit(
            PipelineEvent(
                stage="explore",
                status="started",
                message=f"Launching {len(results)} explorer agent(s)...",
                progress=0.2,
            )
        )

        explorer_tasks = []
        explorer_source_names = []
        # Track configured explorers so we can close their sessions after the
        # parallel gather completes.
        configured_explorers: list[Any] = []

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

            # Inject DB context so the explorer uses the full 12-tool DB suite
            if mini_id is not None:
                # Each explorer gets its own session to allow parallel execution
                explore_session = session_factory()
                explorer._db_session = await explore_session.__aenter__()
                explorer._mini_id = mini_id
                explorer._session_factory = session_factory
                explorer._explore_session_ctx = explore_session
            else:
                explorer._db_session = None
                explorer._mini_id = None
                explorer._session_factory = None
                explorer._explore_session_ctx = None

            configured_explorers.append(explorer)
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
                src = explorer_source_names[i]
                if isinstance(result_or_exc, Exception):
                    logger.error(
                        "Explorer '%s' failed: %s",
                        src,
                        result_or_exc,
                    )
                else:
                    report: ExplorerReport = result_or_exc
                    # ── Token budget accounting (ALLIE-405) ──────────────────
                    try:
                        _token_budget.record(
                            report.tokens_in,
                            report.tokens_out,
                            source=src,
                        )
                    except TokenBudgetExceeded as _tbe:
                        logger.error(
                            "token_budget hard cap exceeded after explorer '%s', "
                            "marking mini failed: %s",
                            src,
                            _tbe,
                        )
                        # Mark mini as failed and surface to caller
                        if mini_id is not None:
                            try:
                                async with session_factory() as _fail_session:
                                    async with _fail_session.begin():
                                        _mini_q = await _fail_session.execute(
                                            select(Mini).where(Mini.id == mini_id)
                                        )
                                        _mini_obj = _mini_q.scalar_one_or_none()
                                        if _mini_obj:
                                            _mini_obj.status = "failed"
                                            _mini_obj.metadata_json = {
                                                **(
                                                    _mini_obj.metadata_json
                                                    if isinstance(_mini_obj.metadata_json, dict)
                                                    else {}
                                                ),
                                                "failure_reason": "token budget exceeded",
                                            }
                            except Exception:
                                logger.exception("Failed to mark mini as failed after token cap")
                        await emit(
                            PipelineEvent(
                                stage="explore",
                                status="failed",
                                message=f"Pipeline stopped: token budget exceeded ({_token_budget.total_tokens} tokens)",
                                progress=0.4,
                            )
                        )
                        raise _tbe

                    # Per-agent soft cap check — mark ExplorerProgress failed but continue
                    if _token_budget.check_soft_cap(source=src) and mini_id is not None:
                        try:
                            async with session_factory() as _soft_session:
                                async with _soft_session.begin():
                                    _ep_q = await _soft_session.execute(
                                        select(ExplorerProgress).where(
                                            ExplorerProgress.mini_id == mini_id,
                                            ExplorerProgress.source_type == src,
                                        )
                                    )
                                    _ep = _ep_q.scalar_one_or_none()
                                    if _ep:
                                        _ep.status = "failed"
                                        _ep.summary = "Per-agent token soft cap exceeded"
                        except Exception:
                            logger.warning(
                                "Failed to mark ExplorerProgress as failed for source=%s", src
                            )

                    explorer_reports.append(report)

        # Close all explorer sessions using the tracked instances
        for exp in configured_explorers:
            ctx = getattr(exp, "_explore_session_ctx", None)
            if ctx is not None:
                try:
                    await ctx.__aexit__(None, None, None)
                except Exception:
                    logger.debug("Error closing explorer session: %s", exp, exc_info=True)
                exp._explore_session_ctx = None
                exp._db_session = None

        await emit(
            PipelineEvent(
                stage="explore",
                status="completed",
                message=f"Exploration complete: {len(explorer_reports)} report(s) from "
                f"{', '.join(r.source_name for r in explorer_reports)}",
                progress=0.5,
            )
        )

        if not explorer_reports:
            raise ValueError("No explorer reports produced — cannot synthesize")

        if trace:
            explore_span.end()

        # ── Stage 3: SYNTHESIZE + SAVE ───────────────────────────────────
        if trace:
            synthesize_span = trace.span(name="synthesize")
        await emit(
            PipelineEvent(
                stage="synthesize",
                status="started",
                message="Chief synthesizer crafting soul document...",
                progress=0.55,
            )
        )

        # ── Use DB-driven synthesizer when mini_id is available ──────────
        if mini_id is not None:
            # DB path: run_chief_synthesizer reads directly from ExplorerFinding /
            # ExplorerQuote tables populated by the explorer agents above.
            async with session_factory() as synth_session:
                spirit_content = await run_chief_synthesizer(
                    mini_id=mini_id,
                    db_session=synth_session,
                )

            # Build memory content from DB findings (memory:* category)
            from app.models.evidence import ExplorerFinding as _EF
            from sqlalchemy import select as _select

            memory_parts: list[str] = []
            async with session_factory() as mem_session:
                mem_stmt = (
                    _select(_EF)
                    .where(
                        _EF.mini_id == mini_id,
                        _EF.category.like("memory:%"),
                    )
                )
                mem_rows = await mem_session.execute(mem_stmt)
                findings = list(mem_rows.scalars().all())
                
                # Shuffle items with the same confidence to counteract recency bias
                random.shuffle(findings)
                findings.sort(key=lambda f: f.confidence, reverse=True)

                for finding in findings:
                    try:
                        data = json.loads(finding.content)
                        text = data.get("text", finding.content)
                        ctx = data.get("context_type", finding.category)
                        memory_parts.append(f"[{ctx}] {text}")
                    except (json.JSONDecodeError, TypeError):
                        memory_parts.append(finding.content)

            # Also collect from in-memory report entries (fallback / supplemental)
            for report in explorer_reports:
                for entry in report.memory_entries:
                    memory_parts.append(f"[{entry.category}/{entry.topic}] {entry.content}")

            memory_content = "\n".join(memory_parts)

        else:
            # Legacy path (tests / no DB): pass explorer reports as text blobs
            all_context_evidence: dict[str, list[str]] = {}
            for report in explorer_reports:
                for ctx_key, ctx_quotes in report.context_evidence.items():
                    all_context_evidence.setdefault(ctx_key, []).extend(ctx_quotes)

            spirit_content = await run_chief_synthesis(
                username,
                explorer_reports,
                context_evidence=all_context_evidence if all_context_evidence else None,
            )

            memory_parts = []
            for report in explorer_reports:
                for entry in report.memory_entries:
                    memory_parts.append(f"[{entry.category}/{entry.topic}] {entry.content}")
            memory_content = "\n".join(memory_parts)

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

        # ── Personality typology inference (ALLIE-430) ───────────────────
        # Run after chief synthesis so all explorer findings/quotes are in DB.
        # Never blocks the pipeline — logged + skipped on failure.
        personality_typology = None
        if mini_id is not None:
            try:
                from app.synthesis.personality import infer_personality_typology

                async with session_factory() as typology_session:
                    personality_typology = await infer_personality_typology(
                        mini_id=mini_id,
                        db_session=typology_session,
                        username=username,
                    )
                logger.info(
                    "personality_typology inferred for mini_id=%s: %d frameworks",
                    mini_id,
                    len(personality_typology.frameworks) if personality_typology else 0,
                )
            except Exception:
                logger.warning(
                    "personality_typology inference failed for mini_id=%s — continuing",
                    mini_id,
                    exc_info=True,
                )

        # ── Behavioral context inference (ALLIE-431) ────────────────────
        # Run after the soul doc is assembled.  Failure is non-blocking —
        # pipeline continues and behavioral_context_json stays None.
        behavioral_ctx = None
        if mini_id is not None:
            try:
                from app.synthesis.behavioral_context import infer_behavioral_context

                async with session_factory() as bctx_session:
                    behavioral_ctx = await infer_behavioral_context(
                        mini_id=mini_id,
                        db_session=bctx_session,
                        username=username,
                    )
                logger.info(
                    "behavioral_context inferred for mini_id=%s (%d contexts)",
                    mini_id,
                    len(behavioral_ctx.contexts) if behavioral_ctx else 0,
                )
            except Exception:
                logger.warning(
                    "behavioral_context inference failed for mini_id=%s — continuing",
                    mini_id,
                    exc_info=True,
                )

        # ── Motivations inference (ALLIE-429) ───────────────────────────
        # Run after behavioral context.  Failure is non-blocking —
        # pipeline continues and motivations_json stays None.
        motivations_profile = None
        if mini_id is not None:
            try:
                from app.synthesis.motivations import infer_motivations

                async with session_factory() as motiv_session:
                    motivations_profile = await infer_motivations(
                        mini_id=mini_id,
                        db_session=motiv_session,
                        username=username,
                    )
                logger.info(
                    "motivations inferred for mini_id=%s: %d motivations, %d chains",
                    mini_id,
                    len(motivations_profile.motivations) if motivations_profile else 0,
                    len(motivations_profile.motivation_chains) if motivations_profile else 0,
                )
            except Exception:
                logger.warning(
                    "motivations inference failed for mini_id=%s — continuing",
                    mini_id,
                    exc_info=True,
                )

        await emit(
            PipelineEvent(
                stage="synthesize",
                status="completed",
                message="Soul document generated",
                progress=0.9,
            )
        )

        if trace:
            synthesize_span.end()

        # ── SAVE ─────────────────────────────────────────────────────────
        if trace:
            save_span = trace.span(name="save")
        await emit(
            PipelineEvent(
                stage="save",
                status="started",
                message="Saving mini...",
                progress=0.9,
            )
        )

        # Extract structured data from DB findings (DB path) or explorer reports
        # (legacy path).
        from app.synthesis.memory_assembler import (
            _merge_knowledge_graphs,
            _merge_principles,
            extract_roles_llm,
            extract_skills_llm,
            extract_traits_llm,
            extract_values_json,
        )

        if mini_id is not None:
            # DB path: reconstruct KG and principles from stored findings
            kg_json, principles_json = await _build_structured_from_db(
                mini_id=mini_id,
                session_factory=session_factory,
            )
            # For roles/skills/traits, pass DB findings as synthetic reports
            db_reports = await _build_synthetic_reports_from_db(
                mini_id=mini_id,
                session_factory=session_factory,
            )
            reports_for_extraction = db_reports if db_reports else explorer_reports
        else:
            reports_for_extraction = explorer_reports
            merged_kg = _merge_knowledge_graphs(explorer_reports)
            merged_principles = _merge_principles(explorer_reports)
            kg_json = merged_kg.model_dump(mode="json")
            principles_json = merged_principles.model_dump(mode="json")

        from app.synthesis.decision_frameworks import attach_decision_frameworks

        principles_json = attach_decision_frameworks(principles_json, motivations_profile)

        # Build system prompt now that decision_frameworks are attached to
        # principles_json — so every mini response is shaped by learned
        # framework confidence from the start.
        system_prompt = build_system_prompt(
            username,
            spirit_content,
            memory_content,
            typology=personality_typology,
            behavioral_context=behavioral_ctx,
            motivations=motivations_profile,
            principles_json=principles_json,
        )

        values_json = extract_values_json(reports_for_extraction)
        roles_json, skills_json, traits_json = await asyncio.gather(
            extract_roles_llm(reports_for_extraction),
            extract_skills_llm(reports_for_extraction),
            extract_traits_llm(reports_for_extraction),
        )

        async with session_factory() as session:
            async with session.begin():
                if mini_id is not None:
                    result = await session.execute(select(Mini).where(Mini.id == mini_id))
                else:
                    result = await session.execute(select(Mini).where(Mini.username == username))
                mini = result.scalar_one_or_none()

                if mini is None:
                    logger.error(
                        "Mini not found (id=%s, username=%s) during save", mini_id, username
                    )
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

                    session.add(
                        MiniRevision(
                            mini_id=mini.id,
                            revision_number=next_rev,
                            spirit_content=mini.spirit_content,
                            memory_content=mini.memory_content,
                            system_prompt=mini.system_prompt,
                            values_json=json.dumps(mini.values_json)
                            if isinstance(mini.values_json, (dict, list))
                            else mini.values_json,
                            trigger=trigger,
                        )
                    )

                mini.display_name = display_name
                mini.avatar_url = avatar_url
                mini.bio = bio
                mini.spirit_content = spirit_content
                mini.memory_content = memory_content
                mini.system_prompt = system_prompt
                mini.values_json = (
                    json.loads(values_json) if isinstance(values_json, str) else values_json
                )
                mini.roles_json = (
                    json.loads(roles_json) if isinstance(roles_json, str) else roles_json
                )
                mini.skills_json = (
                    json.loads(skills_json) if isinstance(skills_json, str) else skills_json
                )
                mini.traits_json = (
                    json.loads(traits_json) if isinstance(traits_json, str) else traits_json
                )
                mini.knowledge_graph_json = kg_json
                mini.principles_json = principles_json
                if personality_typology is not None:
                    mini.personality_typology_json = personality_typology.model_dump(mode="json")
                mini.metadata_json = all_stats
                mini.sources_used = [r.source_name for r in results]
                mini.evidence_cache = evidence_cache
                # Persist behavioral context map (ALLIE-431)
                if behavioral_ctx is not None:
                    mini.behavioral_context_json = json.loads(behavioral_ctx.model_dump_json())
                # Persist motivations profile (ALLIE-429)
                if motivations_profile is not None:
                    mini.motivations_json = json.loads(motivations_profile.model_dump_json())
                mini.status = "ready"

        if trace:
            save_span.end()

        await emit(
            PipelineEvent(
                stage="save",
                status="completed",
                message="Mini is ready!",
                progress=1.0,
            )
        )

        # ── EMBED (optional, non-blocking) ───────────────────────────────
        await _generate_embeddings(
            mini_id=mini.id,
            memory_content=memory_content,
            evidence_cache=evidence_cache,
            knowledge_graph_json=kg_json,
            session_factory=session_factory,
        )

    except Exception as e:
        logger.exception("Pipeline failed for %s: %s", username, e)
        await emit(
            PipelineEvent(
                stage="error",
                status="failed",
                message=f"Pipeline failed: {str(e)}",
                progress=0.0,
            )
        )

        # Update status to failed in DB
        try:
            async with session_factory() as session:
                async with session.begin():
                    if mini_id is not None:
                        result = await session.execute(select(Mini).where(Mini.id == mini_id))
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
        username,
        session_factory,
        on_progress=push_event,
        sources=sources,
        owner_id=owner_id,
        mini_id=mini_id,
        source_identifiers=source_identifiers,
    )

    # Signal completion
    await queue.put(None)
