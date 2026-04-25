"""Personality typology inference agent — PsyCoT methodology.

Ported from my-minis PersonalityTypologistAgent (ALLIE-430).
Reads ExplorerFinding + ExplorerQuote + Evidence for a mini, then runs a
questionnaire-guided chain-of-thought (PsyCoT) to score MBTI, Big Five,
DISC, and Enneagram dimensions.

Cross-validation: MBTI I↔Big Five low E, T↔low A, J↔high C.
Each dimension carries evidence_ids for audit / retrieval use.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ModelTier, get_model
from app.models.evidence import Evidence, ExplorerFinding, ExplorerQuote
from app.models.schemas import (
    PersonalityTypology,
    PersonalityTypologyFramework,
    TypologyDimension,
)

logger = logging.getLogger(__name__)
_AI_LIKE_STATUS = "ai_like"


# ---------------------------------------------------------------------------
# Internal structured output for the LLM call
# ---------------------------------------------------------------------------


class _MBTIDimension(BaseModel):
    """Single MBTI dimension with PsyCoT scoring."""

    dimension: str = Field(description="E_I, S_N, T_F, or J_P")
    score: float = Field(ge=0.0, le=1.0, description="0=first pole, 1=second pole (E/S/T/J)")
    preference: str = Field(description="The preferred letter, e.g. 'I', 'N', 'T', 'J'")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="2-3 Evidence or ExplorerFinding IDs that supported this judgment",
    )
    reasoning: str = Field(description="Short chain-of-thought for this dimension")


class _BigFiveTrait(BaseModel):
    """Single Big Five trait score."""

    trait: str = Field(
        description="openness, conscientiousness, extraversion, agreeableness, or neuroticism"
    )
    score: float = Field(ge=0.0, le=1.0, description="0=low, 1=high")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="2-3 Evidence or ExplorerFinding IDs",
    )
    reasoning: str = Field(description="Short chain-of-thought")


class _DISCProfile(BaseModel):
    """DISC profile inference."""

    primary: str = Field(description="Primary DISC style: D, I, S, or C")
    secondary: str = Field(description="Secondary DISC style: D, I, S, or C")
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = Field(description="Short chain-of-thought")


class _EnneagramResult(BaseModel):
    """Enneagram type with wing."""

    type_number: str = Field(description="1-9")
    wing: str = Field(description="Adjacent number, e.g. '4' for 5w4")
    full_type: str = Field(description="e.g. '5w4'")
    core_motivation: str
    core_fear: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class _CrossValidationFlag(BaseModel):
    """A cross-validation consistency check result."""

    check: str = Field(description="e.g. 'MBTI I ↔ Big Five low E'")
    consistent: bool
    note: str = Field(description="Explanation if inconsistent")


class _TypologyInferenceResult(BaseModel):
    """Full structured output from the PsyCoT inference LLM call."""

    mbti_type: str = Field(description="4-letter type, e.g. 'INTJ'")
    mbti_confidence: float = Field(ge=0.0, le=1.0)
    mbti_dimensions: list[_MBTIDimension] = Field(min_length=4, max_length=4)

    big_five: list[_BigFiveTrait] = Field(min_length=5, max_length=5)
    big_five_confidence: float = Field(ge=0.0, le=1.0)

    disc: _DISCProfile

    enneagram: _EnneagramResult | None = None

    cross_validation: list[_CrossValidationFlag] = Field(default_factory=list)

    overall_confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(
        description="2-3 sentence plain-language summary of the personality profile"
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert personality psychologist using the PsyCoT (Psychometric
Chain-of-Thought) methodology. Your task is to infer a developer's personality
profile from behavioral evidence gathered from their code reviews, commits,
issues, blog posts, and other public activity.

## Methodology

For EACH dimension or trait:
1. Identify 3 relevant questionnaire items from the behavioral evidence.
2. Rate each item 1–5 based on the evidence.
3. Aggregate to a 0.0–1.0 score.
4. List 2–3 specific evidence IDs (from ExplorerFinding or Evidence rows) that
   directly supported your judgment.
5. Write a one-sentence chain-of-thought reasoning.

## Frameworks

### MBTI (4 dimensions)
- **E/I** (score: 0=strong I, 1=strong E): collaboration frequency, comment
  depth vs. breadth, async vs. sync communication preference.
- **S/N** (score: 0=strong S, 1=strong N): concrete vs. abstract focus in
  reviews, practical vs. exploratory problem-solving.
- **T/F** (score: 0=strong F, 1=strong T): logic/critique vs. empathy/support
  in feedback, conflict resolution style.
- **J/P** (score: 0=strong P, 1=strong J): structured commits/docs vs. ad-hoc,
  decisive vs. exploratory approach.

### Big Five (OCEAN, each 0=low, 1=high)
- **Openness**: tech curiosity, framework variety, experimentation.
- **Conscientiousness**: test coverage, commit discipline, documentation quality.
- **Extraversion**: communication volume, community involvement, leadership.
- **Agreeableness**: feedback warmth, conflict avoidance vs. directness.
- **Neuroticism**: stress/urgency signals, reaction to bugs, risk tolerance.

### DISC
- **D (Dominance)**: direct, results-focused, assertive in reviews.
- **I (Influence)**: enthusiastic, collaborative, expressive.
- **S (Steadiness)**: patient, supportive, consistent patterns.
- **C (Conscientiousness)**: detail-oriented, systematic, quality-focused.

### Enneagram (optional — only if confidence > 0.6)
- Types 1–9 based on core motivations and fears visible in behavior.
- Include wing (adjacent type with secondary influence).

## Cross-Validation Rules
Perform these consistency checks and report the result:
- MBTI I ↔ Big Five low Extraversion (E score < 0.5 → Big Five E < 0.5)
- MBTI T ↔ Big Five low Agreeableness (T score > 0.5 → Big Five A < 0.5)
- MBTI J ↔ Big Five high Conscientiousness (J score > 0.5 → Big Five C > 0.5)

Flag any inconsistency explicitly.

## Evidence Citation Rules
- ALWAYS cite 2–3 specific evidence_ids per dimension.
- Use the "id" field from the provided findings/quotes/evidence rows.
- Prefer high-confidence ExplorerFinding rows over raw Evidence.
- If you have fewer than 5 distinct evidence items total, report
  overall_confidence ≤ 0.3.

Return a single JSON object conforming to the _TypologyInferenceResult schema.
"""


def _build_user_prompt(
    username: str,
    findings: list[dict[str, Any]],
    quotes: list[dict[str, Any]],
    evidence_sample: list[dict[str, Any]],
) -> str:
    """Assemble evidence into a compact user prompt (stays under ~8k tokens)."""
    lines: list[str] = [f"## Developer: {username}", ""]

    if findings:
        lines.append(f"### ExplorerFindings ({len(findings)} rows)")
        for f in findings[:80]:  # cap to keep prompt manageable
            lines.append(
                f"id={f['id']} [{f['category']} / {f['source_type']}] "
                f"conf={f['confidence']:.2f}: {f['content'][:300]}"
            )
        lines.append("")

    if quotes:
        lines.append(f"### ExplorerQuotes ({len(quotes)} rows)")
        for q in quotes[:40]:
            ctx = f" ({q['context']})" if q.get("context") else ""
            sig = f" [{q['significance']}]" if q.get("significance") else ""
            lines.append(f'id={q["id"]}{sig}: "{q["quote"][:200]}"{ctx}')
        lines.append("")

    if evidence_sample:
        lines.append(f"### Evidence sample ({len(evidence_sample)} rows, high-signal only)")
        for e in evidence_sample[:30]:
            lines.append(
                f"id={e['id']} [{e['item_type']} / {e['source_type']}]: {e['content'][:200]}"
            )
        lines.append("")

    lines.append(
        "Analyze the above evidence using PsyCoT methodology and return the "
        "_TypologyInferenceResult JSON."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-validation helpers
# ---------------------------------------------------------------------------


def _run_cross_validation(result: _TypologyInferenceResult) -> list[_CrossValidationFlag]:
    """Recompute cross-validation flags from the inferred scores.

    The LLM may produce its own flags; we also enforce them programmatically
    so tests can assert on the output deterministically.
    """
    flags: list[_CrossValidationFlag] = []

    mbti_by_dim: dict[str, _MBTIDimension] = {d.dimension: d for d in result.mbti_dimensions}

    ei = mbti_by_dim.get("E_I")
    tf = mbti_by_dim.get("T_F")
    jp = mbti_by_dim.get("J_P")

    big_five_by_trait: dict[str, _BigFiveTrait] = {t.trait: t for t in result.big_five}
    b5_e = big_five_by_trait.get("extraversion")
    b5_a = big_five_by_trait.get("agreeableness")
    b5_c = big_five_by_trait.get("conscientiousness")

    # MBTI I ↔ Big Five low E
    if ei and b5_e:
        mbti_is_introvert = ei.score < 0.5  # low score = I
        b5_is_low_e = b5_e.score < 0.5
        consistent = (mbti_is_introvert == b5_is_low_e) or (
            not mbti_is_introvert and not b5_is_low_e
        )
        flags.append(
            _CrossValidationFlag(
                check="MBTI I ↔ Big Five low Extraversion",
                consistent=consistent,
                note=(
                    ""
                    if consistent
                    else (
                        f"MBTI E/I score={ei.score:.2f} ({'I' if mbti_is_introvert else 'E'}) "
                        f"contradicts Big Five Extraversion={b5_e.score:.2f}"
                    )
                ),
            )
        )

    # MBTI T ↔ Big Five low Agreeableness
    if tf and b5_a:
        mbti_is_thinking = tf.score > 0.5  # high score = T
        b5_is_low_a = b5_a.score < 0.5
        consistent = mbti_is_thinking == b5_is_low_a
        flags.append(
            _CrossValidationFlag(
                check="MBTI T ↔ Big Five low Agreeableness",
                consistent=consistent,
                note=(
                    ""
                    if consistent
                    else (
                        f"MBTI T/F score={tf.score:.2f} ({'T' if mbti_is_thinking else 'F'}) "
                        f"contradicts Big Five Agreeableness={b5_a.score:.2f}"
                    )
                ),
            )
        )

    # MBTI J ↔ Big Five high Conscientiousness
    if jp and b5_c:
        mbti_is_judging = jp.score > 0.5  # high score = J
        b5_is_high_c = b5_c.score > 0.5
        consistent = mbti_is_judging == b5_is_high_c
        flags.append(
            _CrossValidationFlag(
                check="MBTI J ↔ Big Five high Conscientiousness",
                consistent=consistent,
                note=(
                    ""
                    if consistent
                    else (
                        f"MBTI J/P score={jp.score:.2f} ({'J' if mbti_is_judging else 'P'}) "
                        f"contradicts Big Five Conscientiousness={b5_c.score:.2f}"
                    )
                ),
            )
        )

    return flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def infer_personality_typology(
    mini_id: str,
    db_session: AsyncSession,
    username: str = "",
) -> PersonalityTypology:
    """Infer personality typology from DB evidence for a mini.

    Reads ExplorerFinding + ExplorerQuote + Evidence rows, runs a PsyCoT
    inference call, and returns a validated PersonalityTypology instance
    matching the schema contract from ALLIE-439.

    Args:
        mini_id: DB ID of the Mini record.
        db_session: Active async SQLAlchemy session.
        username: Optional display name for the prompt header.

    Returns:
        PersonalityTypology instance with MBTI, Big Five, DISC, and optionally
        Enneagram frameworks, each with evidence IDs and confidence scores.
    """
    # ── Load evidence from DB ─────────────────────────────────────────────
    findings_stmt = (
        select(ExplorerFinding)
        .where(ExplorerFinding.mini_id == mini_id)
        .order_by(ExplorerFinding.confidence.desc())
    )
    findings_rows = (await db_session.execute(findings_stmt)).scalars().all()

    quotes_stmt = select(ExplorerQuote).where(ExplorerQuote.mini_id == mini_id)
    quotes_rows = (await db_session.execute(quotes_stmt)).scalars().all()

    # Only fetch high-signal evidence items (reviews, blog posts)
    evidence_stmt = (
        select(Evidence)
        .where(
            Evidence.mini_id == mini_id,
            Evidence.item_type.in_(
                [
                    "pr_review",
                    "review_comment",
                    "issue_comment",
                    "commit",
                    "blog_post",
                    "discussion_comment",
                    "stackoverflow_answer",
                ]
            ),
            or_(
                Evidence.ai_contamination_status.is_(None),
                Evidence.ai_contamination_status != _AI_LIKE_STATUS,
            ),
        )
        .order_by(Evidence.created_at.desc())
        .limit(50)
    )
    evidence_rows = (await db_session.execute(evidence_stmt)).scalars().all()

    findings = [
        {
            "id": f.id,
            "source_type": f.source_type,
            "category": f.category,
            "content": f.content,
            "confidence": f.confidence,
        }
        for f in findings_rows
    ]

    quotes = [
        {
            "id": q.id,
            "source_type": q.source_type,
            "quote": q.quote,
            "context": q.context,
            "significance": q.significance,
        }
        for q in quotes_rows
    ]

    evidence_sample = [
        {
            "id": e.id,
            "source_type": e.source_type,
            "item_type": e.item_type,
            "content": e.content,
        }
        for e in evidence_rows
    ]

    total_items = len(findings) + len(quotes) + len(evidence_sample)
    logger.info(
        "personality_typology mini_id=%s: %d findings, %d quotes, %d evidence items",
        mini_id,
        len(findings),
        len(quotes),
        len(evidence_sample),
    )

    if total_items == 0:
        logger.warning(
            "personality_typology mini_id=%s: no evidence found, returning empty typology",
            mini_id,
        )
        return PersonalityTypology(
            summary="Insufficient evidence to infer personality typology.",
            frameworks=[],
        )

    # ── Build prompt ──────────────────────────────────────────────────────
    user_prompt = _build_user_prompt(username, findings, quotes, evidence_sample)
    model_name = get_model(ModelTier.STANDARD)

    # ── Run PydanticAI structured inference ───────────────────────────────
    agent: Agent[None, _TypologyInferenceResult] = Agent(
        model=model_name,
        output_type=_TypologyInferenceResult,
        system_prompt=_SYSTEM_PROMPT,
    )

    agent_result = await agent.run(user_prompt)
    raw: _TypologyInferenceResult = agent_result.output

    # ── Recompute cross-validation programmatically ───────────────────────
    cross_flags = _run_cross_validation(raw)
    has_inconsistency = any(not f.consistent for f in cross_flags)
    if has_inconsistency:
        logger.warning(
            "personality_typology mini_id=%s: cross-validation inconsistencies detected: %s",
            mini_id,
            [f.note for f in cross_flags if not f.consistent],
        )

    # ── Map to schema contract ────────────────────────────────────────────
    frameworks: list[PersonalityTypologyFramework] = []

    # MBTI
    mbti_dims = [
        TypologyDimension(
            name=d.dimension,
            value=d.preference,
            confidence=round(abs(d.score - 0.5) * 2, 3),  # distance from midpoint → confidence
        )
        for d in raw.mbti_dimensions
    ]
    all_mbti_evidence = list({eid for d in raw.mbti_dimensions for eid in d.evidence_ids})
    frameworks.append(
        PersonalityTypologyFramework(
            framework="MBTI",
            profile=raw.mbti_type,
            confidence=raw.mbti_confidence,
            summary=f"Inferred {raw.mbti_type} from behavioral evidence",
            dimensions=mbti_dims,
            evidence=all_mbti_evidence,
        )
    )

    # Big Five
    b5_dims = [
        TypologyDimension(
            name=t.trait.title(),
            value=f"{t.score:.2f}",
            confidence=None,
        )
        for t in raw.big_five
    ]
    all_b5_evidence = list({eid for t in raw.big_five for eid in t.evidence_ids})
    frameworks.append(
        PersonalityTypologyFramework(
            framework="Big Five (OCEAN)",
            profile=" | ".join(f"{t.trait[0].upper()}={t.score:.2f}" for t in raw.big_five),
            confidence=raw.big_five_confidence,
            dimensions=b5_dims,
            evidence=all_b5_evidence,
        )
    )

    # DISC
    frameworks.append(
        PersonalityTypologyFramework(
            framework="DISC",
            profile=f"{raw.disc.primary}-primary, {raw.disc.secondary}-secondary",
            confidence=raw.overall_confidence,
            dimensions=[
                TypologyDimension(name="primary", value=raw.disc.primary),
                TypologyDimension(name="secondary", value=raw.disc.secondary),
            ],
            evidence=raw.disc.evidence_ids,
        )
    )

    # Enneagram (only when confident enough)
    if raw.enneagram and raw.enneagram.confidence >= 0.6:
        frameworks.append(
            PersonalityTypologyFramework(
                framework="Enneagram",
                profile=raw.enneagram.full_type,
                confidence=raw.enneagram.confidence,
                summary=(
                    f"Core motivation: {raw.enneagram.core_motivation}. "
                    f"Core fear: {raw.enneagram.core_fear}."
                ),
                dimensions=[
                    TypologyDimension(name="type", value=raw.enneagram.type_number),
                    TypologyDimension(name="wing", value=raw.enneagram.wing),
                ],
                evidence=raw.enneagram.evidence_ids,
            )
        )

    # Cross-validation metadata appended to summary
    cv_notes = [f.note for f in cross_flags if not f.consistent]
    summary_parts = [raw.summary]
    if cv_notes:
        summary_parts.append("Cross-validation flags: " + "; ".join(cv_notes))

    return PersonalityTypology(
        summary=" ".join(summary_parts),
        frameworks=frameworks,
    )
