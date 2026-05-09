"""Chief synthesizer agent — crafts the soul document from DB-stored evidence.

Uses a ReAct agent loop with DB-driven tools to cross-reference findings,
quotes, knowledge graph, and principles from multiple explorer reports,
then assembles a comprehensive soul document section by section.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent import AgentTool, run_agent
from app.core.models import ModelTier, get_model
from app.db import async_session as _global_session_factory
from app.models.evidence import (
    Evidence,
    ExplorerFinding,
    ExplorerNarrative,
    ExplorerQuote,
)
from app.models.mini import Mini

logger = logging.getLogger(__name__)

ANTI_REGURGITATION_BLOCK = """ANTI-REGURGITATION:
The user is talking to YOU, asking for YOUR take on something they brought up. They have already read everything you ever wrote. They do not want a quote retrieval bot.
- DO NOT lift phrases verbatim from your soul/memory/voice samples in your reply. Those are training, not script.
- DO NOT showboat that you know the subject by reaching for a famous-quote moment from their corpus. That reads as performance, not opinion.
- DO synthesize novel takes in their register and framework. The corpus tells you HOW they think; the conversation gives you a NEW thing to think about. Apply, don't recite.
- When the user asks "what's your hottest opinion?" or any open-ended take question, treat it as a generative prompt. Reach for an opinion they probably WOULD have but haven't necessarily articulated. Use their framework on a fresh subject.
- If you find yourself producing a sentence verbatim from your evidence, REWRITE it.
"""
AUTHENTICITY_LOOP_SYNTHESIS_BLOCK = """AUTHENTICITY LOOP — synthesis edition:
- Measure first, then narrate. For voice claims, report observed frequencies from evidence (rate per 1000 words/messages, percentage of messages, or clear ordinal bins with evidence counts).
- Anchor every register claim in audience + context slices (PR, Slack, casual chat, Claude Code, public writing). Do not collapse contexts.
- For each stylistic axis, report the subject's measured degree, not binary avoid/use language.
- Treat the `voice_signature` narrative as the quantitative source of truth for downstream chat-time degree matching.
- If evidence is thin, report uncertainty explicitly with coverage notes instead of inventing certainty.
"""

NARRATIVE_ASPECTS = (
    "voice_signature",
    "decision_frameworks_in_practice",
    "values_trajectory_over_time",
    "framework_loves_vs_current_focus",
    "temporal_identity",
    "audience_modulation",
    "conflict_and_repair_patterns",
    "technical_aesthetic",
    "philosophical_priors",
    "architecture_worldview",
    "ai_usage_signature",
    # Pre-chief inference narratives (written by pipeline before chief runs)
    "personality_typology",
    "motivations_drivers",
)

ASPECT_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "voice_signature": ("communication_style", "emotional_patterns", "voice_profile"),
    "decision_frameworks_in_practice": ("principles", "values", "decision_making"),
    "values_trajectory_over_time": ("values", "timeline"),
    "framework_loves_vs_current_focus": ("values", "technical_preferences", "timeline"),
    "temporal_identity": (
        "identity",
        "timeline",
        "values",
        "technical_preferences",
        "language_diversity_summary",
    ),
    "audience_modulation": ("communication_style", "context"),
    "conflict_and_repair_patterns": ("conflict", "collaboration", "repair"),
    "technical_aesthetic": ("code_style", "technical_preferences", "aesthetic"),
    "philosophical_priors": ("meta-beliefs", "worldview"),
    "architecture_worldview": ("systems", "architecture", "design"),
    "ai_usage_signature": ("ai_usage_signature", "ai", "authorship", "style"),
    "personality_typology": ("personality", "mbti", "big five", "enneagram", "disc"),
    "motivations_drivers": ("motivation", "goal", "driver", "terminal value", "anti-goal"),
}

ASPECT_KEYWORD_HINTS: dict[str, tuple[str, ...]] = {
    "voice_signature": ("communication", "voice", "tone", "register", "emotional"),
    "decision_frameworks_in_practice": ("decision", "principle", "tradeoff", "value"),
    "values_trajectory_over_time": ("value", "changed", "timeline", "used to", "now"),
    "framework_loves_vs_current_focus": (
        "framework",
        "love",
        "favorite",
        "currently",
        "right now",
        "working on",
        "nuxt",
        "vue",
        "rust",
    ),
    "temporal_identity": (
        "identity",
        "portfolio",
        "deep",
        "breadth_tag",
        "recency_tag",
        "generalist",
        "currently deep",
        "language diversity",
    ),
    "audience_modulation": ("audience", "context", "junior", "peer", "senior", "slack", "pr"),
    "conflict_and_repair_patterns": ("conflict", "disagree", "repair", "escalate", "de-escalate"),
    "technical_aesthetic": ("aesthetic", "code style", "reject", "taste", "technical preference"),
    "philosophical_priors": ("worldview", "meta", "belief", "ethics", "prior"),
    "architecture_worldview": ("architecture", "system", "boundary", "monolith", "microservice"),
    "ai_usage_signature": ("ai", "llm", "assistant", "chatgpt", "claude", "generated", "rewrite"),
    "personality_typology": ("personality", "mbti", "big five", "trait", "enneagram", "disc"),
    "motivations_drivers": ("motivation", "goal", "value", "driver", "terminal", "anti-goal", "chain"),
}

ASPECT_GUIDANCE: dict[str, str] = {
    "voice_signature": (
        "How they code-switch by audience (PR vs Slack vs Claude Code vs casual), sentence rhythm, "
        "declarative vs hedged stance, escalation cadence, verbosity-vs-brevity by context. NOT a phrase list. "
        "Describe REGISTER DYNAMICS — when they get terse, when they extend, what tone they reach for in frustration vs delight.\n\n"
        "Every axis below must include NUMERICAL RATE ESTIMATES anchored in observed evidence (rate per 1000 words/messages, percent of turns, or count/denominator). "
        "Do NOT write 'avoids X' without a measured rate and coverage note.\n\n"
        "REQUIRED OUTPUT STRUCTURE — you MUST include a `## TYPING REGISTER` subsection as part of this essay. The subsection must cover all six axes using labeled bullets:\n"
        "- **Capitalization habit**: include lowercase-sentence rate and context shifts.\n"
        "- **Apostrophe usage**: include apostrophe-elision rate by audience/context.\n"
        "- **Comma vs period punctuation**: include punctuation distribution or ratios.\n"
        "- **Profanity tolerance and triggers**: include profanity rate by audience/context.\n"
        "- **Spelling discipline**: include typo/casual spelling rate and correction behavior.\n"
        "- **Sentence fragmentation**: include fragment rate and sentence-length distribution.\n"
        "- **Additional measurable axes**: include em-dashes per 1000 words, bold-first-word frequency, numbered-list density, and 'Here is/are' opener rate.\n"
        "Extract these from actual observed chat messages, Slack logs, PR comments, and Claude Code session logs — not from formal writing like PRs or commit messages. If casual-chat evidence is thin, say so explicitly."
    ),
    "decision_frameworks_in_practice": (
        "Trigger→action→value rules, ORDERING (what they check first/second/third), revisions over time, "
        "exceptions and boundaries. Show the FUNCTION applied to novel situations."
    ),
    "values_trajectory_over_time": (
        "Model temporal structure explicitly: distinguish STATED LOVE (broad, repeated, cross-project signal) from "
        "CURRENT FOCUS (recent, project-specific signal). Capture mind-changes over time ('used to think X, now thinks Y "
        "because Z') and the thread that links current work back to deep convictions. NEVER treat recent concentration "
        "alone as identity. Generalize cross-project evidence into philosophy/taste (not per-project facts). Include "
        "5-10 hypothetical hottest takes they would hold on novel scenarios, derived from values and decision frameworks "
        "(not retrieved quotes)."
    ),
    "framework_loves_vs_current_focus": (
        "Always produce a PORTFOLIO-LEVEL synthesis, never a recency snapshot. Distinguish deep framework love from current "
        "assignment: SPREAD across many projects/years = conviction; CONCENTRATION in one recent project = habit, constraint, "
        "or assignment. Connect both truths in one thread (e.g., doing Rust for systems performance while Nuxt/Vue remains "
        "aesthetic home)."
    ),
    "temporal_identity": (
        "Temporal identity is mandatory. If 80% of recent evidence is one narrow project but the person has 5+ years of broader work, "
        "describe them as 'X-flavored generalist currently deep on Y', never as 'Y specialist who happens to know X'. "
        "Portfolio breadth beats recency dominance when assigning identity labels. Use breadth-tagged findings and any language diversity "
        "summary evidence to separate enduring identity from current focus."
    ),
    "audience_modulation": (
        "Junior vs peer vs senior; PR vs Slack vs Claude Code vs blog. The CONTEXT MATRIX. "
        "How does the same person sound different in five contexts?"
    ),
    "conflict_and_repair_patterns": (
        "How they disagree, escalate, de-escalate, repair after a clash. Concrete arcs from corpus."
    ),
    "technical_aesthetic": (
        "What makes code feel right. Anti-aesthetic too — what they reject and why. "
        "Citations to actual rejected patterns."
    ),
    "philosophical_priors": (
        "Meta-beliefs that ground concrete decisions. 'Ship fast move fast and break things, but architect once you have signal.' "
        "Product/research/ethics priors. Generalize cross-project evidence into philosophy/taste (not per-project facts). "
        "Include 5-10 hypothetical hottest takes they would hold on novel scenarios, derived from values and framework "
        "synthesis rather than quote retrieval."
    ),
    "architecture_worldview": (
        "Systems thinking. Microservices vs monoliths, monorepo vs polyrepo, SDK design philosophy, "
        "abstraction hygiene, where they draw boundaries and why."
    ),
    "ai_usage_signature": (
        "How/when/why they use AI assistance. Treat AI-likelihood as behavioral signal, not contamination. "
        "Describe patterns by surface, audience, and action type, plus style-marker shifts when AI-likely."
    ),
    "personality_typology": (
        "Integrate structured personality framework data (MBTI, Big Five, DISC, Enneagram) with behavioral evidence "
        "to describe WHO this person is at a trait level. Do NOT just recite scores — show how each dimension "
        "MANIFESTS in practice (e.g. high Openness → appetite for novel frameworks; low Agreeableness → blunt PR reviews). "
        "Cross-validate frameworks: where MBTI I↔Big Five low E agree, state it; where they diverge, surface the tension. "
        "Describe how trait expression shifts by context and audience. NOTE: This narrative is pre-computed from structured "
        "inference before chief runs — treat it as high-confidence grounding data."
    ),
    "motivations_drivers": (
        "Describe what compels this engineer at multiple time horizons: near-term goals, medium-term ambitions, "
        "terminal values (what they'd sacrifice other things for), and anti-goals (what they actively resist). "
        "Show the CAUSAL CHAINS: motivation → implied decision rule → observed behavior in evidence. "
        "Surface contradictions between stated values and revealed preferences. "
        "Describe how motivational urgency shifts by context (solo project vs. team crunch vs. open-source contribution). "
        "NOTE: This narrative is pre-computed from structured inference before chief runs — treat it as high-confidence grounding."
    ),
}

ASPECT_AGENT_SYSTEM_PROMPT = """\
You are an aspect-narrative agent for the Minis fidelity pipeline.

Your single job: write a 1200-2000 word narrative essay describing ONE aspect of this person, grounded in the evidence provided.

Aspect: {aspect}

{aspect_guidance}

NARRATIVE-FIRST PRINCIPLE:
- Describe behavioral DYNAMICS and REGISTER PATTERNS with measured frequencies by context
- Quote evidence directly when striking — citations make essays credible
- Show the FUNCTION (how they reason about novel input), not just facts
- Mind-changes and self-corrections are gold; surface them
- Contradict yourself if the evidence contradicts itself

OUTPUT REQUIREMENTS:
- 1200-2000 words of flowing prose. NO bullet lists.
- Exception: for aspect=`voice_signature`, include the required `## TYPING REGISTER` labeled bullets with measured rates.
- End with one sentence summarizing the load-bearing pattern
- Call save_narrative(aspect="{aspect}", narrative=<essay>, confidence=<0-1>) when done

{authenticity_loop_block}
"""

CHIEF_FINAL_SYNTHESIS_PROMPT = """\
You are the chief synthesizer of a Mini personality clone.

You have 10 narrative essays about a single person, each focused on one aspect.

Your job: write a 4000-6000 word soul document integrating them.

Output structure (markdown):

# IDENTITY
2-3 paragraphs at the most compressed level: who is this person.

# DECISION FUNCTION
How they decide. Triggers, ordering, value-priority. Show the FUNCTION as applied to several archetypal situations.

# VOICE
Register dynamics. Code-switching by context. NOT a phrase list.

# WHEN THEY'RE WRONG
Self-correction history. Mind-changes. Calibration trajectory.

# WORKING WITH OTHERS
Audience modulation. Conflict patterns. Repair.

# AESTHETICS AND PRIORS
What feels right. Architecture worldview. Technical taste. Anti-aesthetic.

# INSTRUCTIONS TO YOURSELF
Closing in second-person voice — directives the mini reads at chat time.
"When you respond, you do X. You never do Y. When the user asks Z, reach for W first." Concrete, actionable, grounded in the narratives.

OUTPUT REQUIREMENTS:
- 4000-6000 words.
- Use the exact section structure above.
- Keep each section in prose; avoid list-shaped summaries unless evidence demands it.
- Enforce temporal identity: if recent evidence is dominated by one narrow project but long-range evidence shows broader work, describe identity as an X-flavored generalist currently deep on Y.

{authenticity_loop_block}

Anti-rules:
- DO NOT start with "This person is a senior engineer who values..." (generic)
- DO NOT collapse identity into the newest narrow project label.
- DO NOT frame the person as a firmware or embedded specialist solely because recent evidence clusters there when portfolio evidence is broader.
- DO NOT use coefficient language ("profanity tolerance: high")
- DO NOT bullet-list values; argue them in prose
- DO NOT enumerate "5 key principles" — show the function in action
- DO use direct quotes from evidence the narratives cite
- DO mirror their voice slightly without imitation

{anti_regurgitation_block}

The 10 narratives:

{narrative_blocks}
"""

SECTION_ORDER = [
    "Identity Core",
    "Voice & Style",
    "Personality & Emotional Patterns",
    "Values & Beliefs",
    "Anti-Values & DON'Ts",
    "Conflict & Pushback",
    "VOICE FRAMEWORK",
    "Quirks & Imperfection",
]

SYSTEM_PROMPT = """\
You are the Chief Synthesizer. You build a "Forgery Manual" — a soul document \
so precise that a close collaborator could not distinguish the clone from the \
original person.

## YOUR TOOLS

Call `get_explorer_summaries` first to see what sources are available. Then use \
`search_findings`, `get_findings_by_category`, `get_all_quotes`, \
`get_knowledge_graph`, and `get_principles` to pull raw evidence. Write each \
section with `write_section`. Call `finish` when all 8 sections are done.

## THE #1 RULE: SPECIFICITY OVER VOLUME

Every sentence in the soul document must contain a SPECIFIC behavioral rule \
backed by evidence. If you cannot cite evidence for a claim, do NOT write it.

The target length is under 3000 words total. No section should exceed 500 words. \
A tight 1500-word soul document beats a bloated 5000-word one every time.

## ANTI-GENERIC GUARD

If a trait could apply to ANY competent engineer — "writes clean code", \
"values testing", "is detail-oriented", "team player" — it is NOT a personality \
trait and MUST NOT appear in the soul document. Only include rules that \
DISTINGUISH this person from 100 other senior developers.

Brittle denylists are not the method. Use abductive filtering:
- Prefer evidence-specific behavioral claims over abstract trait adjectives.
- If a sentence would still sound plausible for almost any senior engineer, cut it.
- If evidence is thin or contradictory, write the uncertainty and scope instead of forcing a trait claim.

{anti_regurgitation_block}

## AUTHENTICITY LOOP — synthesis edition

{authenticity_loop_block}

## DEDUPLICATION

When multiple findings express the same trait, write ONE merged rule that cites \
the convergence across sources. Do NOT list the same trait multiple times.

## SHOW DON'T TELL

Never write label statements like "She is sarcastic" or "He is direct." Instead:
- BAD: "You are sarcastic."
- GOOD: "When you see a bad API design, you say 'I assume this was designed by \
committee' rather than explaining what's wrong with it."

Every personality claim must include a concrete behavioral example — a specific \
phrase they'd use, a specific reaction they'd have, a specific pattern in their \
writing. If evidence does not support a behavior-level claim, do not emit a \
meta-label; mark it as unknown/uncertain.

## ABDUCTIVE REASONING

Make claims about the person from evidence patterns. Formulate hypotheses that \
explain the observed behaviors:

Example: "Evidence shows shipping quickly on MVPs while also building robust \
error handling. This indicates a pragmatist who accepts MVP-quality code to \
prove a concept, but insulates critical paths. The tension is: velocity over \
polish for experiments, correctness over speed for infrastructure."

When evidence is contradictory, name the tension explicitly rather than picking \
one side.

## THE HIERARCHY OF EVIDENCE

- **Tier 1 (Behavior):** What they DO — code, commits, PR reviews.
- **Tier 2 (Speech):** What they SAY — blogs, READMEs, comments.
- **Tier 3 (Projection):** What they WANT to be — bios, self-descriptions.

Tier 1 > Tier 2 > Tier 3. When tiers conflict, note the tension and weight \
Tier 1 higher. Do NOT fabricate a phantom personality trait from the gap — \
name the contradiction and move on.

## TEMPORAL SIGNALS

Beliefs corroborated across old AND new evidence are deep values. Beliefs from \
only recent repos might be project-specific habits, not identity. Weight \
temporally broad findings higher than frequent-but-narrow recent-only findings.
If 80% of recent evidence is one narrow project but the person has 5+ years of broader work, \
describe them as an X-flavored generalist currently deep on Y, not as Y-first identity.

## SECTION STRUCTURE (strict word limits)

1. **Identity Core** (max 150 words): Who this person IS in 3-5 sentences. \
Not their job title — their essence. What makes them unlike anyone else?

2. **Voice & Style** (max 500 words): HOW they communicate, not WHAT they \
communicate about. Cover:
   - Sentence length and structure (terse? elaborate? varies by context?)
   - Cursing patterns (which words, when, how often — or never)
   - Humor type (dry, absurd, self-deprecating, punny, dark?)
   - Formality shifts (PR vs chat vs docs vs casual)
   - Signature phrases and banned words
   - Emotional expressiveness in text (exclamation points, caps, emojis?)
   Do NOT describe commit message formatting or code style here. Focus purely \
on voice, tone, and linguistic personality.

3. **Personality & Emotional Patterns** (max 400 words): How they react under \
pressure. What triggers frustration vs excitement. Their emotional tells — the \
micro-behaviors that reveal mood (e.g., "response time drops to single words \
when annoyed").

4. **Values & Beliefs** (max 400 words): ONLY values that DISTINGUISH this \
person. Not "cares about code quality" — everyone says that. Instead: specific \
technical convictions, hills they die on, decision-making axioms. Distinguish \
conviction from convention.

5. **Anti-Values & DON'Ts** (max 300 words): ONLY from POSITIVE evidence of \
rejection — things they actively pushed back on, criticized, or refused to do. \
Do NOT infer anti-values from absence. Include banned tokens, banned behaviors, \
and explicit "Anti-Assistant" rules (forbid phrases like "Here is a \
comprehensive list...").

6. **Conflict & Pushback** (max 300 words): How they disagree. Their \
argumentation style — do they ask questions, make assertions, use sarcasm, \
cite evidence? How do they escalate? How do they concede?

7. **VOICE FRAMEWORK** (max 400 words): Describe how this person sounds without \
storing quote scripts. Cover register patterns, sentence rhythm, code-switching \
across contexts, and how they approach novel input. Do NOT provide a list of \
literal quotes. Literal quotes belong in retrieval tools, not this soul prompt.

8. **Quirks & Imperfection** (max 200 words): The human stuff. Verbal tics, \
pet peeves, contradictions, typos they make consistently, habits that don't fit \
neat categories.

## WORKFLOW

1. **Gather:** Call `get_explorer_summaries`, then pull findings, quotes, \
knowledge graph, and principles.
2. **Deduplicate:** Group findings by trait. Merge convergent signals into \
single rules.
3. **Synthesize:** Write each section tight — every sentence earns its place.
4. **Audit:** Before finishing, check each section:
   - Does every sentence cite evidence or give a specific behavioral example?
   - Would this sentence apply to any senior engineer? If yes, delete it.
   - Have I used any banned phrases? Delete them.
5. **Finish:** Call `finish` when all 8 sections pass the audit.

## SECOND-PERSON RULE

Write EVERYTHING in second person ("You are...", "You type...", "When someone \
asks you...", "You would NEVER..."). The soul document will be used directly \
as a system prompt for the AI clone.
"""


def _finding_text(finding: ExplorerFinding) -> str:
    """Decode ExplorerFinding content into a plain text representation."""
    raw = finding.content or ""
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, str) and content:
            return content
        return json.dumps(data)
    if isinstance(data, list):
        return json.dumps(data)
    return str(data)


def _normalize_section_name(section_name: str) -> str:
    """Map legacy section labels to canonical soul-doc section names."""
    if section_name.strip().lower() == "voice samples":
        return "VOICE FRAMEWORK"
    return section_name


def _matches_aspect(finding: ExplorerFinding, aspect: str) -> bool:
    category = (finding.category or "").lower()
    text = _finding_text(finding).lower()
    category_hints = ASPECT_CATEGORY_HINTS[aspect]
    keyword_hints = ASPECT_KEYWORD_HINTS[aspect]
    return any(hint in category for hint in category_hints) or any(
        hint in text for hint in keyword_hints
    )


def _finding_context_tags(finding: ExplorerFinding) -> str:
    raw = finding.content or ""
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    tags: list[str] = []
    temporal = data.get("temporal_signal")
    breadth = data.get("breadth_tag")
    recency = data.get("recency_tag")
    if isinstance(temporal, str) and temporal:
        tags.append(f"temporal_signal={temporal}")
    if isinstance(breadth, str) and breadth:
        tags.append(f"breadth_tag={breadth}")
    if isinstance(recency, str) and recency:
        tags.append(f"recency_tag={recency}")
    if not tags:
        return ""
    return " [" + ", ".join(tags) + "]"


def _format_finding_block(rows: list[ExplorerFinding], limit: int = 60) -> str:
    if not rows:
        return "No matching findings."
    parts: list[str] = []
    for row in rows[:limit]:
        parts.append(
            (
                f"- [{row.source_type}/{row.category}] conf={row.confidence:.2f}"
                f"{_finding_context_tags(row)}: {_finding_text(row)}"
            )
        )
    return "\n".join(parts)


def _format_quote_block(rows: list[ExplorerQuote], limit: int = 40) -> str:
    if not rows:
        return "No quotes found."
    parts: list[str] = []
    for row in rows[:limit]:
        context = f" ({row.context})" if row.context else ""
        parts.append(f'- [{row.source_type}] "{row.quote}"{context}')
    return "\n".join(parts)


def _format_ai_signal_block(rows: list[Evidence], limit: int = 60) -> str:
    if not rows:
        return "No AI-signal-tagged evidence found."
    parts: list[str] = []
    for row in rows[:limit]:
        score = row.ai_authorship_likelihood if row.ai_authorship_likelihood is not None else 0.0
        marker_keys = []
        if isinstance(row.ai_style_markers, dict):
            marker_keys = sorted(str(key) for key in row.ai_style_markers.keys())
        excerpt = (row.content or "").replace("\n", " ").strip()[:260]
        parts.append(
            f"- [{row.source_type}/{row.item_type}/{row.context}] ai={score:.2f} markers={marker_keys} text={excerpt}"
        )
    return "\n".join(parts)


def _format_language_diversity_block(rows: list[Evidence], limit: int = 10) -> str:
    if not rows:
        return "No language diversity summary evidence found."
    parts: list[str] = []
    for row in rows[:limit]:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        distinct_languages = metadata.get("distinct_languages")
        repos_with_languages = metadata.get("repos_with_languages")
        language_totals = metadata.get("language_totals")
        parts.append(
            (
                f"- summary={row.content} "
                f"distinct_languages={distinct_languages} "
                f"repos_with_languages={repos_with_languages} "
                f"language_totals={language_totals}"
            )
        )
    return "\n".join(parts)


async def _run_chief_synthesizer_fanout(
    mini_id: str,
    db_session: AsyncSession,
    model: str | None = None,
) -> str:
    """Fan-out orchestrator: aspect narratives + final chief synthesis."""
    mini_result = await db_session.execute(select(Mini).where(Mini.id == mini_id))
    mini = mini_result.scalar_one_or_none()
    if mini is None:
        raise ValueError(f"Mini not found: {mini_id}")

    findings_result = await db_session.execute(
        select(ExplorerFinding)
        .where(ExplorerFinding.mini_id == mini_id)
        .order_by(ExplorerFinding.confidence.desc())
    )
    all_findings = list(findings_result.scalars().all())

    quotes_result = await db_session.execute(
        select(ExplorerQuote).where(ExplorerQuote.mini_id == mini_id)
    )
    all_quotes = list(quotes_result.scalars().all())
    ai_signals_result = await db_session.execute(
        select(Evidence)
        .where(
            Evidence.mini_id == mini_id,
            Evidence.ai_authorship_likelihood.is_not(None),
        )
        .order_by(Evidence.ai_authorship_likelihood.desc(), Evidence.created_at.desc())
        .limit(200)
    )
    ai_signal_rows = list(ai_signals_result.scalars().all())
    language_diversity_result = await db_session.execute(
        select(Evidence)
        .where(
            Evidence.mini_id == mini_id,
            Evidence.item_type == "language_diversity_summary",
        )
        .order_by(Evidence.created_at.desc())
        .limit(5)
    )
    language_diversity_rows = list(language_diversity_result.scalars().all())

    run_started_at = datetime.datetime.now(datetime.timezone.utc)
    standard_model = get_model(ModelTier.STANDARD, user_override=model)

    async def search_findings(query: str) -> str:
        needle = query.lower().strip()
        matches = [
            row
            for row in all_findings
            if needle in _finding_text(row).lower() or needle in (row.category or "").lower()
        ]
        return _format_finding_block(matches, limit=30)

    async def get_findings_by_category(category: str) -> str:
        target = category.lower().strip()
        matches = [row for row in all_findings if (row.category or "").lower() == target]
        if matches:
            return _format_finding_block(matches, limit=60)
        categories = sorted({row.category for row in all_findings if row.category})
        return f"No findings for category '{category}'. Available: {categories}"

    async def get_all_quotes() -> str:
        return _format_quote_block(all_quotes, limit=60)

    async def get_principles() -> str:
        if not mini.principles_json:
            return "No principles available."
        principles = mini.principles_json.get("principles", [])
        if not principles:
            return "No principles available."
        lines: list[str] = []
        for principle in principles:
            lines.append(
                f"- trigger={principle.get('trigger')} | action={principle.get('action')} | value={principle.get('value')}"
            )
        return "\n".join(lines)

    async def save_narrative(
        aspect: str,
        narrative: str,
        confidence: float = 0.5,
        evidence_ids: list[str] | None = None,
    ) -> str:
        if aspect not in NARRATIVE_ASPECTS:
            return json.dumps({"error": f"aspect must be one of {sorted(NARRATIVE_ASPECTS)}"})
        if not narrative or len(narrative) < 200:
            return json.dumps({"error": "narrative must be >=200 chars (essay-length)"})
        if len(narrative) > 30000:
            return json.dumps({"error": "narrative must be <=30000 chars"})

        update_values: dict[str, Any] = {
            "narrative": narrative,
            "confidence": confidence,
            "evidence_ids": evidence_ids or [],
        }
        if "updated_at" in ExplorerNarrative.__table__.c:
            update_values["updated_at"] = func.now()

        stmt = (
            pg_insert(ExplorerNarrative)
            .values(
                mini_id=mini_id,
                aspect=aspect,
                narrative=narrative,
                confidence=confidence,
                evidence_ids=evidence_ids or [],
                explorer_source="chief_fanout",
            )
            .on_conflict_do_update(
                index_elements=["mini_id", "aspect", "explorer_source"],
                set_=update_values,
            )
            .returning(ExplorerNarrative.id)
        )
        async with _global_session_factory() as write_session:
            result = await write_session.execute(stmt)
            await write_session.commit()
            new_id = result.scalar_one()
        return json.dumps(
            {
                "saved": True,
                "aspect": aspect,
                "id": new_id,
                "narrative_chars": len(narrative),
            }
        )

    read_tools = [
        AgentTool(
            name="search_findings",
            description="Search findings by keyword across all evidence.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=search_findings,
        ),
        AgentTool(
            name="get_findings_by_category",
            description="Get findings for a specific category.",
            parameters={
                "type": "object",
                "properties": {"category": {"type": "string"}},
                "required": ["category"],
            },
            handler=get_findings_by_category,
        ),
        AgentTool(
            name="get_all_quotes",
            description="Get all quotes captured for this mini.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_all_quotes,
        ),
        AgentTool(
            name="get_principles",
            description="Get principles matrix entries if available.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_principles,
        ),
        AgentTool(
            name="save_narrative",
            description=(
                "Save an essay-length narrative (1200-2000 words) describing one aspect of the person's "
                "decision-making, voice, or worldview. Use for SYNTHESIS, not atomic facts. "
                "Aspects: voice_signature, decision_frameworks_in_practice, values_trajectory_over_time, "
                "framework_loves_vs_current_focus, temporal_identity, audience_modulation, conflict_and_repair_patterns, technical_aesthetic, "
                "philosophical_priors, architecture_worldview, ai_usage_signature, personality_typology, motivations_drivers. "
                "Describe REGISTER PATTERNS, not literal phrases."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "aspect": {"type": "string", "enum": list(NARRATIVE_ASPECTS)},
                    "narrative": {"type": "string", "description": "1200-2000 word essay"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["aspect", "narrative"],
            },
            handler=save_narrative,
        ),
    ]

    evidence_overview = _format_finding_block(all_findings, limit=120)
    quotes_overview = _format_quote_block(all_quotes, limit=60)
    ai_signal_overview = _format_ai_signal_block(ai_signal_rows, limit=80)
    language_diversity_overview = _format_language_diversity_block(
        language_diversity_rows,
        limit=5,
    )

    # Load pre-chief inference narratives so we can skip fan-out agents for them.
    pre_inference_result = await db_session.execute(
        select(ExplorerNarrative)
        .where(
            ExplorerNarrative.mini_id == mini_id,
            ExplorerNarrative.explorer_source == "synthesis_inference",
        )
    )
    pre_inference_aspects: set[str] = {
        row.aspect for row in pre_inference_result.scalars().all()
    }
    if pre_inference_aspects:
        logger.info(
            "Chief fan-out: skipping %d pre-computed aspects for mini_id=%s: %s",
            len(pre_inference_aspects),
            mini_id,
            sorted(pre_inference_aspects),
        )

    async def run_aspect_agent(aspect: str) -> tuple[str, bool]:
        if aspect in pre_inference_aspects:
            logger.debug("Chief fan-out: using pre-computed narrative for aspect=%s", aspect)
            return aspect, True

        filtered_findings = [row for row in all_findings if _matches_aspect(row, aspect)]
        filtered_quotes = [
            row
            for row in all_quotes
            if any(hint in (row.quote or "").lower() for hint in ASPECT_KEYWORD_HINTS[aspect])
        ]
        user_prompt = (
            f"Subject: {mini.username}\n"
            f"Aspect: {aspect}\n\n"
            "Use these evidence blocks. Shared block appears in every aspect call for prompt-cache stability.\n\n"
            "[shared_evidence_block cache_control=ephemeral]\n"
            f"{evidence_overview}\n\n"
            "[shared_quotes_block cache_control=ephemeral]\n"
            f"{quotes_overview}\n\n"
            "[shared_ai_signal_block cache_control=ephemeral]\n"
            f"{ai_signal_overview}\n\n"
            "[language_diversity_summary_block cache_control=ephemeral]\n"
            f"{language_diversity_overview}\n\n"
            f"[aspect_findings_{aspect}]\n{_format_finding_block(filtered_findings)}\n\n"
            f"[aspect_quotes_{aspect}]\n{_format_quote_block(filtered_quotes)}\n\n"
            "Write the essay and call save_narrative."
        )
        system_prompt = ASPECT_AGENT_SYSTEM_PROMPT.format(
            aspect=aspect,
            aspect_guidance=ASPECT_GUIDANCE[aspect],
            authenticity_loop_block=AUTHENTICITY_LOOP_SYNTHESIS_BLOCK,
        )

        # Removed max_output_tokens=8192 + max_turns cap per agency-first principle
        # (memory:feedback_agency_first). Aspect narratives MUST be allowed to run
        # to natural completion — capping was silently dropping 5+ aspects per regen.
        result = await run_agent(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=read_tools,
            model=standard_model,
        )

        saved_calls = result.tool_outputs.get("save_narrative", [])
        if result.final_response is None or not saved_calls:
            logger.warning(
                "Aspect narrative agent failed or did not save narrative mini_id=%s aspect=%s",
                mini_id,
                aspect,
            )
            return aspect, False
        return aspect, True

    aspect_results = await asyncio.gather(
        *(run_aspect_agent(aspect) for aspect in NARRATIVE_ASPECTS),
        return_exceptions=True,
    )
    for item in aspect_results:
        if isinstance(item, Exception):
            logger.warning("Aspect narrative task failed mini_id=%s error=%s", mini_id, item)
            continue
        aspect, ok = item
        if not ok:
            logger.warning("Graceful degradation for aspect mini_id=%s aspect=%s", mini_id, aspect)

    from sqlalchemy import or_ as _or_

    narratives_result = await db_session.execute(
        select(ExplorerNarrative)
        .where(
            ExplorerNarrative.mini_id == mini_id,
            # Include fan-out narratives from this run AND pre-chief inference
            # narratives written by the pipeline before chief started.
            _or_(
                ExplorerNarrative.created_at >= run_started_at,
                ExplorerNarrative.explorer_source == "synthesis_inference",
            ),
        )
        .order_by(ExplorerNarrative.aspect, ExplorerNarrative.created_at.desc())
    )
    narrative_rows = list(narratives_result.scalars().all())
    latest_by_aspect: dict[str, ExplorerNarrative] = {}
    for row in narrative_rows:
        # chief_fanout narratives win for shared aspects so they override
        # pre-inference drafts with evidence-grounded content.
        if row.aspect not in latest_by_aspect or row.explorer_source == "chief_fanout":
            latest_by_aspect[row.aspect] = row

    if not latest_by_aspect:
        raise RuntimeError("Chief fan-out produced zero aspect narratives")

    narrative_blocks: list[str] = []
    for aspect in NARRATIVE_ASPECTS:
        row = latest_by_aspect.get(aspect)
        if row is None:
            continue
        narrative_blocks.append(
            f"## {aspect}\nconfidence={row.confidence:.2f}\nsource={row.explorer_source}\n\n{row.narrative}"
        )

    chief_result = await run_agent(
        system_prompt=CHIEF_FINAL_SYNTHESIS_PROMPT.format(
            narrative_blocks="\n\n".join(narrative_blocks),
            anti_regurgitation_block=ANTI_REGURGITATION_BLOCK,
            authenticity_loop_block=AUTHENTICITY_LOOP_SYNTHESIS_BLOCK,
        ),
        user_prompt=(
            f"Synthesize a soul document for {mini.username} from the narratives. "
            "Keep it concrete and evidence-grounded. "
            f"Language diversity summary evidence:\n{language_diversity_overview}"
        ),
        tools=[],
        max_turns=12,
        max_output_tokens=65536,
        model=standard_model,
    )
    if chief_result.final_response:
        return chief_result.final_response
    raise RuntimeError("Chief final synthesis returned empty output")


async def run_chief_synthesizer(
    mini_id: str,
    db_session: AsyncSession,
    model: str | None = None,
) -> str:
    """Run the chief synthesizer agent with DB-driven tools."""
    return await _run_chief_synthesizer_fanout(
        mini_id=mini_id,
        db_session=db_session,
        model=model,
    )
