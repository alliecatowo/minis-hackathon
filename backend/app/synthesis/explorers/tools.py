"""Standardized tool suite for explorer agents.

Builds AgentTool instances that operate on the Evidence, ExplorerFinding,
ExplorerQuote, and ExplorerProgress tables via an async SQLAlchemy session.

Write operations (save_*, mark_explored, finish) each open their own session
via *session_factory* so that concurrent PydanticAI tool calls don't share a
single session and hit SQLAlchemy "already in progress" / "transaction closed"
errors.

Read operations (browse_evidence, search_evidence, read_item, get_progress) use
the shared *db_session* since they don't write.
"""

from __future__ import annotations

import datetime
import json
import logging
import re

from sqlalchemy import func, select, update

from app.core.agent import AgentTool
from app.models.evidence import (
    Evidence,
    ExplorerFinding,
    ExplorerProgress,
    ExplorerQuote,
)
from app.models.knowledge import NodeType, RelationType

logger = logging.getLogger(__name__)

# Evidence items with contamination score >= this threshold are considered
# AI-generated and excluded from browse/search when exclude_contaminated=True.
_CONTAMINATION_THRESHOLD = 0.5

_SIGNAL_SEARCH_CANDIDATE_LIMIT = 200

_CONFLICT_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("explicit_disagreement", re.compile(r"\bi disagree\b", re.IGNORECASE)),
    ("skeptical_pushback", re.compile(r"\bi don't think\b|\bi wouldn't\b", re.IGNORECASE)),
    (
        "blocking_language",
        re.compile(r"\bblock(?:er|ing)?\b|\bchanges requested\b|\brequest changes\b", re.IGNORECASE),
    ),
    (
        "concern_language",
        re.compile(r"\bconcern(?:ed)?\b|\bthis breaks\b|\bthis will cause\b", re.IGNORECASE),
    ),
    (
        "preference_language",
        re.compile(r"\bprefer\b|\brather than\b|\binstead\b|\bplease don't\b", re.IGNORECASE),
    ),
    (
        "review_nit",
        re.compile(r"\bnit:?\b|\bshouldn't we\b|\bhave you considered\b", re.IGNORECASE),
    ),
    ("course_correction", re.compile(r"\bactually,?\b|\bhowever,?\b|\blet's not\b", re.IGNORECASE)),
)

_APPROVAL_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lgtm", re.compile(r"\blgtm\b", re.IGNORECASE)),
    ("looks_good", re.compile(r"\blooks?\s+good\b|\bship it\b", re.IGNORECASE)),
    ("approval_state", re.compile(r"\bapproved?\b", re.IGNORECASE)),
    ("praise", re.compile(r"\blove this\b|\bnice work\b|\bwell done\b", re.IGNORECASE)),
    ("quality_callout", re.compile(r"\bgood catch\b|\bclean\b|\belegant\b", re.IGNORECASE)),
    ("gratitude", re.compile(r"\bthanks for fixing\b|\bthank you\b", re.IGNORECASE)),
)

_GITHUB_ITEM_TYPE_SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "review": {"conflict": 3.0, "approval": 2.5, "high_signal": 3.0},
    "issue_comment": {"conflict": 2.4, "approval": 1.8, "high_signal": 2.4},
    "pr": {"conflict": 1.7, "approval": 1.9, "high_signal": 1.8},
    "commit": {"conflict": 0.5, "approval": 0.2, "high_signal": 0.4},
}

_SIGNAL_MODE_ENUM = [
    "all",
    "high_signal_first",
    "conflicts_first",
    "approvals_first",
    "conflicts_only",
    "approvals_only",
]


def _match_signal_patterns(
    content: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[str]:
    """Return the names of signal patterns that match the evidence content."""
    return [name for name, pattern in patterns if pattern.search(content)]


def _github_signal_weight(item_type: str, signal_name: str, source_type: str) -> float:
    """Return a GitHub-specific item type boost for a signal family."""
    if source_type != "github":
        return 0.0
    return _GITHUB_ITEM_TYPE_SIGNAL_WEIGHTS.get(item_type, {}).get(signal_name, 0.0)


def _signal_sort_timestamp(row: Evidence) -> float:
    """Return a sortable timestamp, newest-first friendly."""
    created_at = getattr(row, "created_at", None)
    if created_at is None:
        return 0.0
    return created_at.timestamp()


def _build_signal_metadata(row: Evidence) -> dict[str, object]:
    """Classify an evidence row for explorer signal prioritization."""
    content = getattr(row, "content", "") or ""
    item_type = getattr(row, "item_type", "") or ""
    source_type = getattr(row, "source_type", "") or ""

    conflict_matches = _match_signal_patterns(content, _CONFLICT_SIGNAL_PATTERNS)
    approval_matches = _match_signal_patterns(content, _APPROVAL_SIGNAL_PATTERNS)

    conflict_score = len(conflict_matches) * 2.0 + _github_signal_weight(
        item_type, "conflict", source_type
    )
    approval_score = len(approval_matches) * 2.0 + _github_signal_weight(
        item_type, "approval", source_type
    )
    high_signal_score = max(
        conflict_score,
        approval_score,
        _github_signal_weight(item_type, "high_signal", source_type),
    )

    dominant_signal: str | None = None
    if conflict_matches and conflict_score >= approval_score:
        dominant_signal = "conflict"
    elif approval_matches:
        dominant_signal = "approval"

    return {
        "conflict_score": round(conflict_score, 2),
        "approval_score": round(approval_score, 2),
        "high_signal_score": round(high_signal_score, 2),
        "dominant_signal": dominant_signal,
        "conflict_matches": conflict_matches,
        "approval_matches": approval_matches,
    }


def _include_for_signal_mode(signal_mode: str, signal: dict[str, object]) -> bool:
    """Decide whether an evidence row should be included for a signal mode."""
    if signal_mode == "conflicts_only":
        return bool(signal["conflict_matches"])
    if signal_mode == "approvals_only":
        return bool(signal["approval_matches"])
    return True


def _score_for_signal_mode(signal_mode: str, signal: dict[str, object]) -> float:
    """Return the primary ranking score for the requested signal mode."""
    if signal_mode in {"conflicts_first", "conflicts_only"}:
        return float(signal["conflict_score"])
    if signal_mode in {"approvals_first", "approvals_only"}:
        return float(signal["approval_score"])
    return float(signal["high_signal_score"])


def _serialize_evidence_row(row: Evidence, signal_mode: str) -> dict[str, object]:
    """Serialize an Evidence row for browse/search responses."""
    signal = _build_signal_metadata(row)
    payload: dict[str, object] = {
        "id": row.id,
        "item_type": row.item_type,
        "content_preview": row.content[:200],
        "explored": row.explored,
        "source_privacy": row.source_privacy,
        "signal": {
            **signal,
            "signal_mode": signal_mode,
        },
    }
    source_type = getattr(row, "source_type", None)
    if isinstance(source_type, str):
        payload["source_type"] = source_type
    return payload


def _prioritize_rows(rows: list[Evidence], signal_mode: str) -> list[Evidence]:
    """Filter/sort rows for explorer high-signal evidence mining."""
    annotated: list[tuple[Evidence, dict[str, object]]] = []
    for row in rows:
        signal = _build_signal_metadata(row)
        if _include_for_signal_mode(signal_mode, signal):
            annotated.append((row, signal))

    annotated.sort(
        key=lambda item: (
            item[0].explored,
            -_score_for_signal_mode(signal_mode, item[1]),
            -(len(item[1]["conflict_matches"]) + len(item[1]["approval_matches"])),
            -_signal_sort_timestamp(item[0]),
        )
    )
    return [row for row, _ in annotated]


def build_explorer_tools(
    mini_id: str,
    source_type: str,
    db_session,
    session_factory=None,
) -> list[AgentTool]:
    """Construct the full explorer tool suite.

    Each tool closes over *mini_id*, *source_type*, *db_session*, and
    *session_factory* so the agent never needs to pass them explicitly.

    Write operations use *session_factory* (if provided) to create an isolated
    session per call, avoiding SQLAlchemy concurrency errors when PydanticAI
    dispatches multiple tool calls concurrently.  Read operations use the
    shared *db_session*.
    """

    # ── helper ─────────────────────────────────────────────────────────────

    async def _increment_progress(field: str) -> None:
        """Increment a counter on the ExplorerProgress record."""
        col = getattr(ExplorerProgress, field)
        stmt = (
            update(ExplorerProgress)
            .where(
                ExplorerProgress.mini_id == mini_id,
                ExplorerProgress.source_type == source_type,
            )
            .values({field: col + 1})
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                await write_session.execute(stmt)
                await write_session.commit()
        else:
            await db_session.execute(stmt)
            await db_session.commit()

    # ── browse_evidence ────────────────────────────────────────────────────

    async def browse_evidence(
        source_type: str = source_type,
        page: int = 1,
        page_size: int = 20,
        signal_mode: str = "all",
        exclude_contaminated: bool = True,
    ) -> str:
        if signal_mode not in _SIGNAL_MODE_ENUM:
            return json.dumps(
                {
                    "error": (
                        f"Invalid signal_mode '{signal_mode}'. "
                        f"Valid: {_SIGNAL_MODE_ENUM}"
                    )
                }
            )

        base_conditions = [
            Evidence.mini_id == mini_id,
            Evidence.source_type == source_type,
        ]
        if exclude_contaminated:
            # Include rows with NULL score (not yet scored) and rows below threshold
            from sqlalchemy import or_

            base_conditions.append(
                or_(
                    Evidence.ai_contamination_score.is_(None),
                    Evidence.ai_contamination_score < _CONTAMINATION_THRESHOLD,
                )
            )

        offset = (page - 1) * page_size
        if signal_mode == "all":
            stmt = (
                select(Evidence)
                .where(*base_conditions)
                .order_by(Evidence.created_at)
                .offset(offset)
                .limit(page_size)
            )
            result = await db_session.execute(stmt)
            rows = result.scalars().all()

            count_stmt = (
                select(func.count())
                .select_from(Evidence)
                .where(*base_conditions)
            )
            total = (await db_session.execute(count_stmt)).scalar() or 0
        else:
            stmt = select(Evidence).where(*base_conditions)
            result = await db_session.execute(stmt)
            prioritized = _prioritize_rows(result.scalars().all(), signal_mode)
            total = len(prioritized)
            rows = prioritized[offset : offset + page_size]

        items = [_serialize_evidence_row(r, signal_mode) for r in rows]
        return json.dumps(
            {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "signal_mode": signal_mode,
                "exclude_contaminated": exclude_contaminated,
            }
        )

    # ── search_evidence ────────────────────────────────────────────────────

    async def search_evidence(
        query: str,
        source_type: str | None = None,
        signal_mode: str = "all",
        exclude_contaminated: bool = True,
    ) -> str:
        if signal_mode not in _SIGNAL_MODE_ENUM:
            return json.dumps(
                {
                    "error": (
                        f"Invalid signal_mode '{signal_mode}'. "
                        f"Valid: {_SIGNAL_MODE_ENUM}"
                    )
                }
            )

        conditions = [
            Evidence.mini_id == mini_id,
            Evidence.content.ilike(f"%{query}%"),
        ]
        if source_type:
            conditions.append(Evidence.source_type == source_type)
        if exclude_contaminated:
            from sqlalchemy import or_

            conditions.append(
                or_(
                    Evidence.ai_contamination_score.is_(None),
                    Evidence.ai_contamination_score < _CONTAMINATION_THRESHOLD,
                )
            )

        stmt = select(Evidence).where(*conditions).limit(
            50 if signal_mode == "all" else _SIGNAL_SEARCH_CANDIDATE_LIMIT
        )
        result = await db_session.execute(stmt)
        rows = result.scalars().all()

        if signal_mode != "all":
            rows = _prioritize_rows(rows, signal_mode)[:50]

        items = [_serialize_evidence_row(r, signal_mode) for r in rows]
        return json.dumps(
            {
                "matches": items,
                "query": query,
                "count": len(items),
                "signal_mode": signal_mode,
                "exclude_contaminated": exclude_contaminated,
            }
        )

    # ── read_item ──────────────────────────────────────────────────────────

    async def read_item(item_id: str) -> str:
        stmt = select(Evidence).where(Evidence.id == item_id, Evidence.mini_id == mini_id)
        result = await db_session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return json.dumps({"error": f"Evidence item {item_id} not found"})
        return json.dumps(
            {
                "id": row.id,
                "source_type": row.source_type,
                "item_type": row.item_type,
                "content": row.content,
                "metadata": row.metadata_json,
                "explored": row.explored,
                "source_privacy": row.source_privacy,
            }
        )

    # ── save_finding ───────────────────────────────────────────────────────

    async def save_finding(
        category: str,
        content: str,
        confidence: float = 0.5,
    ) -> str:
        finding = ExplorerFinding(
            mini_id=mini_id,
            source_type=source_type,
            category=category,
            content=content,
            confidence=confidence,
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                write_session.add(finding)
                await write_session.commit()
        else:
            db_session.add(finding)
            await db_session.commit()

        await _increment_progress("findings_count")
        return json.dumps({"saved": True, "category": category, "id": finding.id})

    # ── save_memory ────────────────────────────────────────────────────────

    async def save_memory(
        category: str,
        content: str,
        context_type: str = "general",
    ) -> str:
        finding = ExplorerFinding(
            mini_id=mini_id,
            source_type=source_type,
            category=f"memory:{category}",
            content=json.dumps({"text": content, "context_type": context_type}),
            confidence=0.7,
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                write_session.add(finding)
                await write_session.commit()
        else:
            db_session.add(finding)
            await db_session.commit()

        await _increment_progress("memories_count")
        return json.dumps({"saved": True, "category": category})

    # ── save_quote ─────────────────────────────────────────────────────────

    async def save_quote(
        quote: str,
        context: str,
        significance: str,
        evidence_id: str | None = None,
    ) -> str:
        # Reject quotes sourced from high-contamination evidence (ALLIE-433).
        if evidence_id is not None:
            stmt = select(Evidence).where(Evidence.id == evidence_id, Evidence.mini_id == mini_id)
            ev_result = await db_session.execute(stmt)
            ev_row = ev_result.scalar_one_or_none()
            if ev_row is not None:
                score = ev_row.ai_contamination_score
                if score is not None and score >= _CONTAMINATION_THRESHOLD:
                    return json.dumps(
                        {
                            "saved": False,
                            "rejected": True,
                            "reason": (
                                f"Evidence item {evidence_id} has high AI contamination "
                                f"score ({score:.2f} >= {_CONTAMINATION_THRESHOLD}). "
                                "Quote rejected to protect voice authenticity."
                            ),
                        }
                    )

        q = ExplorerQuote(
            mini_id=mini_id,
            source_type=source_type,
            quote=quote,
            context=context,
            significance=significance,
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                write_session.add(q)
                await write_session.commit()
        else:
            db_session.add(q)
            await db_session.commit()

        await _increment_progress("quotes_count")
        return json.dumps({"saved": True, "id": q.id})

    # ── save_knowledge_node ────────────────────────────────────────────────

    async def save_knowledge_node(
        name: str,
        type: str,
        depth: float = 0.5,
        confidence: float = 0.5,
    ) -> str:
        # Validate type against NodeType enum
        try:
            NodeType(type)
        except ValueError:
            valid = [t.value for t in NodeType]
            return json.dumps({"error": f"Invalid type '{type}'. Valid: {valid}"})

        node_data = {
            "name": name,
            "type": type,
            "depth": depth,
            "confidence": confidence,
        }
        finding = ExplorerFinding(
            mini_id=mini_id,
            source_type=source_type,
            category="knowledge_node",
            content=json.dumps(node_data),
            confidence=confidence,
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                write_session.add(finding)
                await write_session.commit()
        else:
            db_session.add(finding)
            await db_session.commit()

        await _increment_progress("nodes_count")
        return json.dumps({"saved": True, "node": name, "type": type})

    # ── save_knowledge_edge ────────────────────────────────────────────────

    async def save_knowledge_edge(
        source_node: str,
        target_node: str,
        relation: str,
        weight: float = 0.5,
    ) -> str:
        try:
            RelationType(relation)
        except ValueError:
            valid = [r.value for r in RelationType]
            return json.dumps({"error": f"Invalid relation '{relation}'. Valid: {valid}"})

        edge_data = {
            "source": source_node,
            "target": target_node,
            "relation": relation,
            "weight": weight,
        }
        finding = ExplorerFinding(
            mini_id=mini_id,
            source_type=source_type,
            category="knowledge_edge",
            content=json.dumps(edge_data),
            confidence=weight,
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                write_session.add(finding)
                await write_session.commit()
        else:
            db_session.add(finding)
            await db_session.commit()

        return json.dumps({"saved": True, "edge": f"{source_node} -> {target_node}"})

    # ── save_principle ─────────────────────────────────────────────────────

    async def save_principle(
        trigger: str,
        action: str,
        value: str,
        intensity: int = 5,
    ) -> str:
        principle_data = {
            "trigger": trigger,
            "action": action,
            "value": value,
            "intensity": intensity,
        }
        finding = ExplorerFinding(
            mini_id=mini_id,
            source_type=source_type,
            category="principle",
            content=json.dumps(principle_data),
            confidence=intensity / 10.0,
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                write_session.add(finding)
                await write_session.commit()
        else:
            db_session.add(finding)
            await db_session.commit()

        return json.dumps({"saved": True, "principle": f"{trigger} -> {action}"})

    # ── mark_explored ──────────────────────────────────────────────────────

    async def mark_explored(item_id: str) -> str:
        stmt = (
            update(Evidence)
            .where(Evidence.id == item_id, Evidence.mini_id == mini_id)
            .values(explored=True)
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                result = await write_session.execute(stmt)
                await write_session.commit()
        else:
            result = await db_session.execute(stmt)
            await db_session.commit()

        if result.rowcount == 0:
            return json.dumps({"error": f"Evidence item {item_id} not found"})

        await _increment_progress("explored_items")
        return json.dumps({"marked": True, "item_id": item_id})

    # ── get_progress ───────────────────────────────────────────────────────

    async def get_progress() -> str:
        stmt = select(ExplorerProgress).where(
            ExplorerProgress.mini_id == mini_id,
            ExplorerProgress.source_type == source_type,
        )
        result = await db_session.execute(stmt)
        progress = result.scalar_one_or_none()
        if not progress:
            return json.dumps({"error": "No progress record found"})
        return json.dumps(
            {
                "total_items": progress.total_items,
                "explored_items": progress.explored_items,
                "findings_count": progress.findings_count,
                "memories_count": progress.memories_count,
                "quotes_count": progress.quotes_count,
                "nodes_count": progress.nodes_count,
                "status": progress.status,
            }
        )

    # ── finish ─────────────────────────────────────────────────────────────

    async def finish(summary: str) -> str:
        stmt = (
            update(ExplorerProgress)
            .where(
                ExplorerProgress.mini_id == mini_id,
                ExplorerProgress.source_type == source_type,
            )
            .values(
                status="completed",
                finished_at=datetime.datetime.now(datetime.timezone.utc),
                last_explored_at=datetime.datetime.now(datetime.timezone.utc),
                summary=summary,
            )
        )
        if session_factory is not None:
            async with session_factory() as write_session:
                await write_session.execute(stmt)
                await write_session.commit()
        else:
            await db_session.execute(stmt)
            await db_session.commit()

        return json.dumps({"completed": True, "summary": summary})

    # ── Assemble tool list ─────────────────────────────────────────────────

    return [
        AgentTool(
            name="browse_evidence",
            description="Paginate through evidence items for this source. Use to survey available data before diving deep.",
            parameters={
                "type": "object",
                "properties": {
                    "source_type": {
                        "type": "string",
                        "description": "Evidence source type to browse (e.g. github, blog, hackernews)",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default 1)",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page (default 20)",
                    },
                    "signal_mode": {
                        "type": "string",
                        "enum": _SIGNAL_MODE_ENUM,
                        "description": (
                            "Optional prioritization mode. Use high_signal_first, "
                            "conflicts_first, approvals_first, conflicts_only, or approvals_only "
                            "to surface higher-signal evidence before chronological browsing."
                        ),
                    },
                    "exclude_contaminated": {
                        "type": "boolean",
                        "description": (
                            "When true (default), exclude evidence items likely generated by AI "
                            "(contamination score >= 0.5). Set to false to include all items."
                        ),
                    },
                },
                "required": ["source_type"],
            },
            handler=browse_evidence,
        ),
        AgentTool(
            name="search_evidence",
            description="Keyword search across evidence content for this mini. Returns matching items with content preview.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or phrase",
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Optional source type filter",
                    },
                    "signal_mode": {
                        "type": "string",
                        "enum": _SIGNAL_MODE_ENUM,
                        "description": (
                            "Optional prioritization mode. Use conflicts_first or approvals_first "
                            "to rank matched evidence by conflict/approval signal; use *_only "
                            "to filter to those signals."
                        ),
                    },
                    "exclude_contaminated": {
                        "type": "boolean",
                        "description": (
                            "When true (default), exclude evidence items likely generated by AI "
                            "(contamination score >= 0.5). Set to false to include all items."
                        ),
                    },
                },
                "required": ["query"],
            },
            handler=search_evidence,
        ),
        AgentTool(
            name="read_item",
            description="Read a specific evidence item in full detail (complete content + metadata).",
            parameters={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "ID of the evidence item to read",
                    },
                },
                "required": ["item_id"],
            },
            handler=read_item,
        ),
        AgentTool(
            name="save_finding",
            description="Persist a structured finding about the developer. Categories: personality, values, skills, communication_style, opinions, anti_values.",
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Finding category (personality, values, skills, communication_style, opinions, anti_values)",
                    },
                    "content": {
                        "type": "string",
                        "description": "The finding content",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level 0.0-1.0 (default 0.5)",
                    },
                },
                "required": ["category", "content"],
            },
            handler=save_finding,
        ),
        AgentTool(
            name="save_memory",
            description="Save a memory entry (factual knowledge about the developer). Similar to findings but used by memory_assembler.",
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Memory category (projects, expertise, opinions, workflow, etc.)",
                    },
                    "content": {
                        "type": "string",
                        "description": "The memory content",
                    },
                    "context_type": {
                        "type": "string",
                        "description": "Context type (general, code_review, documentation, etc.)",
                    },
                },
                "required": ["category", "content"],
            },
            handler=save_memory,
        ),
        AgentTool(
            name="save_quote",
            description="Save a behavioral quote from the developer with context and significance.",
            parameters={
                "type": "object",
                "properties": {
                    "quote": {
                        "type": "string",
                        "description": "The exact quote from the developer",
                    },
                    "context": {
                        "type": "string",
                        "description": "Where/when this quote appeared",
                    },
                    "significance": {
                        "type": "string",
                        "description": "What this quote reveals about the developer",
                    },
                    "evidence_id": {
                        "type": "string",
                        "description": (
                            "Optional ID of the evidence item this quote came from. "
                            "When provided, quotes from high-contamination evidence "
                            "(AI-generated prose) are automatically rejected."
                        ),
                    },
                },
                "required": ["quote", "context", "significance"],
            },
            handler=save_quote,
        ),
        AgentTool(
            name="save_knowledge_node",
            description="Add a node to the knowledge graph (skill, project, concept, etc.).",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the entity (e.g. 'React', 'Clean Code')",
                    },
                    "type": {
                        "type": "string",
                        "enum": [t.value for t in NodeType],
                        "description": "Type of knowledge node",
                    },
                    "depth": {
                        "type": "number",
                        "description": "Expertise depth 0.0-1.0 (default 0.5)",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level 0.0-1.0 (default 0.5)",
                    },
                },
                "required": ["name", "type"],
            },
            handler=save_knowledge_node,
        ),
        AgentTool(
            name="save_knowledge_edge",
            description="Add a relationship between two knowledge graph nodes.",
            parameters={
                "type": "object",
                "properties": {
                    "source_node": {
                        "type": "string",
                        "description": "Name of the source node",
                    },
                    "target_node": {
                        "type": "string",
                        "description": "Name of the target node",
                    },
                    "relation": {
                        "type": "string",
                        "enum": [r.value for r in RelationType],
                        "description": "Type of relationship",
                    },
                    "weight": {
                        "type": "number",
                        "description": "Strength of relationship 0.0-1.0 (default 0.5)",
                    },
                },
                "required": ["source_node", "target_node", "relation"],
            },
            handler=save_knowledge_edge,
        ),
        AgentTool(
            name="save_principle",
            description="Add a decision principle (trigger -> action -> value).",
            parameters={
                "type": "object",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "description": "Situation that triggers the rule",
                    },
                    "action": {
                        "type": "string",
                        "description": "Action taken in response",
                    },
                    "value": {
                        "type": "string",
                        "description": "Underlying value",
                    },
                    "intensity": {
                        "type": "integer",
                        "description": "Strength 1-10 (default 5)",
                    },
                },
                "required": ["trigger", "action", "value"],
            },
            handler=save_principle,
        ),
        AgentTool(
            name="mark_explored",
            description="Mark an evidence item as explored (already analyzed).",
            parameters={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "ID of the evidence item to mark",
                    },
                },
                "required": ["item_id"],
            },
            handler=mark_explored,
        ),
        AgentTool(
            name="get_progress",
            description="Check exploration progress: total items, explored items, counts of findings/quotes/nodes.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_progress,
        ),
        AgentTool(
            name="finish",
            description="Signal that exploration is complete. Updates progress to 'completed' with a summary.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of exploration findings",
                    },
                },
                "required": ["summary"],
            },
            handler=finish,
        ),
    ]
