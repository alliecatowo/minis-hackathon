"""BehavioralContextAgent — infers how a developer's communication shifts by context.

Reads Evidence rows grouped by context_type (the `context` column added by ALLIE-428).
For each context bucket with ≥MIN_ITEMS items, uses a STANDARD-tier LLM call to
extract a ContextPersona: register, tone descriptors, key phrases, values emphasized,
and sampled quote IDs.

Cross-context contradictions are surfaced when two buckets show opposing signals
(e.g. praises pairing publicly, dreads it privately).  These are not judgements
— they are real dimensions of a person that the soul document should reflect.

Returns a `BehavioralContext` (from app.models.schemas) that gets persisted to
`Mini.behavioral_context_json` by the chief synthesizer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Evidence, ExplorerQuote
from app.models.schemas import BehavioralContext, BehavioralContextEntry

logger = logging.getLogger(__name__)
_AI_LIKE_STATUS = "ai_like"

# Minimum number of evidence items in a bucket before we bother analyzing it.
MIN_ITEMS_PER_CONTEXT = 3


# ---------------------------------------------------------------------------
# Internal types — not exported; used only for the LLM structured call.
# ---------------------------------------------------------------------------


def _build_context_analysis_prompt(
    username: str,
    context_type: str,
    snippets: list[str],
    sample_quotes: list[dict[str, str]],
) -> str:
    """Build the user prompt for a single-context LLM analysis call."""
    snippets_text = "\n\n".join(f"[{i + 1}] {s[:800]}" for i, s in enumerate(snippets[:30]))
    quotes_text = ""
    if sample_quotes:
        quotes_text = "\n\nSampled behavioral quotes from this context:\n" + "\n".join(
            f'- "{q["quote"]}" (context: {q.get("context", "")})' for q in sample_quotes[:10]
        )

    return f"""\
Analyze how **{username}** behaves in the **{context_type}** context.

Evidence snippets from this context:
{snippets_text}
{quotes_text}

Return a JSON object with these fields:
- "summary": 2-3 sentence description of their behavior in this context
- "behaviors": list of 3-6 specific observable behaviors (strings)
- "communication_style": one sentence on register (formal/casual/blunt/warm/etc.)
- "decision_style": one sentence on how they make decisions here
- "motivators": list of 2-4 things that drive them in this context
- "stressors": list of 2-4 things that frustrate or block them in this context
- "evidence": list of 2-4 short evidence citations (paraphrased, not verbatim)
- "formality_score": float 0.0 (very casual) to 1.0 (highly formal)
- "tone_descriptors": list of 3-6 adjectives describing their tone here

Be concrete and specific. Focus on HOW behavior DIFFERS from their baseline.
Only include what the evidence actually supports.
"""


def _build_contradictions_prompt(
    username: str,
    context_summaries: dict[str, str],
) -> str:
    """Build prompt for surfacing cross-context contradictions."""
    summaries_text = "\n".join(
        f"**{ctx}**: {summary}" for ctx, summary in context_summaries.items()
    )
    return f"""\
Compare {username}'s behavior across these contexts:

{summaries_text}

Identify genuine contradictions or tensions — cases where the person behaves or
values something differently in one context vs another.  These are NOT hypocrisies
— they are real dimensions of a person (e.g. "Enthusiastically endorses pair
programming in public PRs, but private journal entries show they find it draining").

Return a JSON array of objects, each with:
- "description": one clear sentence describing the contradiction
- "context_a": name of first context
- "behavior_a": what they do/say in context A
- "context_b": name of second context
- "behavior_b": what they do/say in context B
- "significance": why this matters for understanding them authentically

Return an empty array [] if no meaningful contradictions exist.
Only surface genuine tensions supported by the evidence — don't manufacture them.
"""


async def _call_llm_for_context(
    username: str,
    context_type: str,
    snippets: list[str],
    sample_quotes: list[dict[str, str]],
    model: str | None = None,
) -> dict[str, Any]:
    """Call the LLM to analyze a single context bucket.

    Returns a dict compatible with BehavioralContextEntry fields.
    Falls back to a minimal dict on any error.
    """
    from app.core.models import ModelTier, get_model

    resolved_model = model or get_model(ModelTier.STANDARD)

    prompt = _build_context_analysis_prompt(username, context_type, snippets, sample_quotes)

    try:
        from pydantic_ai import Agent

        agent: Agent[None, str] = Agent(
            model=resolved_model,
            system_prompt=(
                "You are an expert behavioral analyst. "
                "Analyze how a developer's communication and behavior shifts by context. "
                "Return valid JSON only — no markdown fences, no explanation outside JSON."
            ),
            result_type=str,
        )
        result = await agent.run(prompt)
        raw = result.data.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        parsed = json.loads(raw)
        return parsed
    except Exception as exc:
        logger.warning(
            "LLM context analysis failed for context=%s: %s",
            context_type,
            exc,
            exc_info=True,
        )
        return {
            "summary": f"Analysis unavailable for context {context_type!r}.",
            "behaviors": [],
            "communication_style": None,
            "decision_style": None,
            "motivators": [],
            "stressors": [],
            "evidence": [],
            "formality_score": 0.5,
            "tone_descriptors": [],
        }


async def _call_llm_for_contradictions(
    username: str,
    context_summaries: dict[str, str],
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Call the LLM to surface cross-context contradictions.

    Returns a list of contradiction dicts.  Falls back to [] on any error.
    """
    if len(context_summaries) < 2:
        return []

    from app.core.models import ModelTier, get_model

    resolved_model = model or get_model(ModelTier.STANDARD)
    prompt = _build_contradictions_prompt(username, context_summaries)

    try:
        from pydantic_ai import Agent

        agent: Agent[None, str] = Agent(
            model=resolved_model,
            system_prompt=(
                "You are an expert behavioral analyst identifying authentic tensions "
                "in a person's behavior across different contexts. "
                "Return valid JSON only — no markdown fences."
            ),
            result_type=str,
        )
        result = await agent.run(prompt)
        raw = result.data.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return []
    except Exception as exc:
        logger.warning("LLM contradiction surfacing failed: %s", exc, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def infer_behavioral_context(
    mini_id: str,
    db_session: AsyncSession,
    username: str = "",
    model: str | None = None,
    min_items: int = MIN_ITEMS_PER_CONTEXT,
) -> BehavioralContext:
    """Infer structured behavioral context from evidence grouped by context_type.

    Args:
        mini_id: The database ID of the Mini being synthesized.
        db_session: An open async SQLAlchemy session.
        username: Developer's username (used in prompts for personalisation).
        model: Optional LLM model override.  Defaults to STANDARD tier.
        min_items: Minimum evidence items per context bucket to trigger analysis.

    Returns:
        BehavioralContext — the structured map of how communication shifts.
        If fewer than 2 context buckets exist, returns a minimal object.
    """
    if not username:
        # Fall back to looking up the username from the Mini record
        from app.models.mini import Mini

        result = await db_session.execute(select(Mini).where(Mini.id == mini_id))
        mini = result.scalar_one_or_none()
        username = (mini.username if mini else "") or "unknown"

    # ── 1. Fetch all evidence grouped by context_type ────────────────────
    stmt = select(
        Evidence.context,
        Evidence.content,
        Evidence.source_type,
    ).where(
        Evidence.mini_id == mini_id,
        or_(
            Evidence.ai_contamination_status.is_(None),
            Evidence.ai_contamination_status != _AI_LIKE_STATUS,
        ),
    )
    rows = await db_session.execute(stmt)
    evidence_rows = rows.all()

    # Group by context
    by_context: dict[str, list[str]] = {}
    for row in evidence_rows:
        ctx = row.context or "general"
        by_context.setdefault(ctx, []).append(row.content)

    # Filter buckets below threshold
    eligible_contexts = {
        ctx: snippets for ctx, snippets in by_context.items() if len(snippets) >= min_items
    }

    if not eligible_contexts:
        logger.info(
            "behavioral_context: no context bucket meets min_items=%d for mini_id=%s "
            "(found %d raw contexts, all below threshold)",
            min_items,
            mini_id,
            len(by_context),
        )
        return BehavioralContext(
            summary="Insufficient context-tagged evidence to infer behavioral context map.",
            contexts=[],
        )

    logger.info(
        "behavioral_context: analyzing %d context buckets for mini_id=%s (username=%s)",
        len(eligible_contexts),
        mini_id,
        username,
    )

    # ── 2. Fetch behavioral quotes per context ───────────────────────────
    quotes_stmt = select(ExplorerQuote).where(ExplorerQuote.mini_id == mini_id)
    quotes_rows = await db_session.execute(quotes_stmt)
    all_quotes = quotes_rows.scalars().all()

    # Map quote context → list of quote dicts
    quote_by_context: dict[str, list[dict[str, str]]] = {}
    for q in all_quotes:
        # ExplorerQuote.context is free-text, not necessarily a context_type tag.
        # We do a simple substring match to link quotes to context buckets.
        matched = False
        if q.context:
            for ctx_key in eligible_contexts:
                if ctx_key in (q.context or ""):
                    quote_by_context.setdefault(ctx_key, []).append(
                        {"quote": q.quote, "context": q.context or ""}
                    )
                    matched = True
                    break
        if not matched:
            # Assign to "general" bucket if no specific match
            quote_by_context.setdefault("general", []).append(
                {"quote": q.quote, "context": q.context or ""}
            )

    # ── 3. Analyze each eligible context bucket ──────────────────────────
    context_entries: list[BehavioralContextEntry] = []
    context_summaries: dict[str, str] = {}

    for ctx_name, snippets in sorted(eligible_contexts.items()):
        sample_quotes = quote_by_context.get(ctx_name, [])
        analysis = await _call_llm_for_context(
            username=username,
            context_type=ctx_name,
            snippets=snippets,
            sample_quotes=sample_quotes,
            model=model,
        )

        entry = BehavioralContextEntry(
            context=ctx_name,
            summary=analysis.get("summary", ""),
            behaviors=analysis.get("behaviors", []),
            communication_style=analysis.get("communication_style"),
            decision_style=analysis.get("decision_style"),
            motivators=analysis.get("motivators", []),
            stressors=analysis.get("stressors", []),
            evidence=analysis.get("evidence", []),
        )
        context_entries.append(entry)
        context_summaries[ctx_name] = analysis.get("summary", "")

        logger.debug(
            "behavioral_context: analyzed context=%s items=%d",
            ctx_name,
            len(snippets),
        )

    # ── 4. Surface cross-context contradictions ──────────────────────────
    contradictions = await _call_llm_for_contradictions(
        username=username,
        context_summaries=context_summaries,
        model=model,
    )

    # ── 5. Build top-level summary ────────────────────────────────────────
    context_names = ", ".join(sorted(eligible_contexts.keys()))
    contradiction_count = len(contradictions)
    summary = (
        f"{username} shows distinct behavioral patterns across {len(context_entries)} "
        f"context types: {context_names}."
    )
    if contradiction_count:
        summary += (
            f" {contradiction_count} cross-context tension(s) identified — "
            f"these reflect authentic multi-dimensionality, not inconsistency."
        )

    # Embed contradictions into the summary field as structured text so they
    # survive round-trips through `BehavioralContext.summary` (a plain string).
    # A richer schema can surface them as a dedicated list in a later PR.
    if contradictions:
        contradiction_lines = ["\n\n## Cross-Context Contradictions"]
        for c in contradictions:
            contradiction_lines.append(
                f"- **{c.get('context_a', '?')} vs {c.get('context_b', '?')}**: "
                f"{c.get('description', '')} "
                f"(significance: {c.get('significance', '')})"
            )
        summary += "".join(contradiction_lines)

    logger.info(
        "behavioral_context: complete for mini_id=%s — %d contexts, %d contradictions",
        mini_id,
        len(context_entries),
        contradiction_count,
    )

    return BehavioralContext(summary=summary, contexts=context_entries)


# ---------------------------------------------------------------------------
# System-prompt helper
# ---------------------------------------------------------------------------


def build_context_block(ctx: BehavioralContext) -> str:
    """Render a BehavioralContext into a BEHAVIORAL CONTEXT MAP prompt block.

    Designed to be embedded in the system prompt produced by
    `spirit.build_system_prompt()`.
    """
    if not ctx or not ctx.contexts:
        return ""

    lines: list[str] = ["## BEHAVIORAL CONTEXT MAP (inferred)"]

    for entry in ctx.contexts:
        lines.append(f"\n### In {entry.context}")
        if entry.communication_style:
            lines.append(f"- Register: {entry.communication_style}")
        if entry.behaviors:
            behaviors_str = "; ".join(entry.behaviors[:4])
            lines.append(f"- Behaviors: {behaviors_str}")
        if entry.motivators:
            lines.append(f"- Motivated by: {', '.join(entry.motivators[:3])}")
        if entry.stressors:
            lines.append(f"- Frustrated by: {', '.join(entry.stressors[:3])}")

    # Extract contradictions from summary (stored as structured text)
    if ctx.summary and "## Cross-Context Contradictions" in ctx.summary:
        contradiction_section = ctx.summary.split("## Cross-Context Contradictions", 1)[1]
        lines.append("\n### Notable Contradictions (authentic, not flaws)")
        lines.append(contradiction_section.strip())

    return "\n".join(lines)
