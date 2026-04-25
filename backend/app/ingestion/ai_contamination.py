"""Author-grounded LLM AI-contamination classifier.

Detects whether a piece of evidence text is consistent with how a specific
author writes (authentic) or reads as AI-generated surrogate voice.

The key insight: we're NOT running a generic AI detector.  We're asking
"does this text sound like *this person*?" — which requires an author
baseline for comparison.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal
import logging

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.compaction import create_compaction_processor
from app.core.models import ModelTier, get_model
from app.models.evidence import Evidence

logger = logging.getLogger(__name__)

AIVerdict = Literal["human", "ai_like", "uncertain", "insufficient_baseline", "error"]
ClassifierFn = Callable[[str, "AuthorBaseline"], Awaitable["AIDetectionResult"]]

MIN_BASELINE_SAMPLES = 2
MAX_BASELINE_SAMPLES = 3
MIN_BASELINE_CHARS = 80
MAX_SAMPLE_CHARS = 1200
MAX_CANDIDATE_CHARS = 4000
AI_LIKE_THRESHOLD = 0.75
HUMAN_THRESHOLD = 0.35
MIN_CONFIDENT_CLASSIFICATION = 0.6
UNCERTAIN_LOW = 0.4
UNCERTAIN_HIGH = 0.65


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class AIDetectionResult(BaseModel):
    """Structured result from the author-grounded AI-contamination classifier."""

    verdict: Literal["human", "ai_like", "uncertain"] = Field(
        default="uncertain",
        description="Explicit classification; use uncertain when baseline fit is ambiguous",
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="0.0 = authentic author voice, 1.0 = AI-generated surrogate voice",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Classifier confidence in the score (0.0 = very uncertain, 1.0 = certain)",
    )
    reasoning: str = Field(
        description="One-sentence explanation of the key signal that drove the score",
    )


class AuthorBaseline(BaseModel):
    """Known-authentic text samples from the author, used as a reference baseline."""

    username: str = Field(description="GitHub username / author identifier")
    samples: list[str] = Field(
        description="Known-authentic text samples from the same author",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence row IDs used as the baseline samples",
    )
    source_hint: str | None = Field(
        default=None,
        description="Where the samples come from, e.g. 'github commit messages', 'blog posts'",
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You evaluate whether a piece of developer text is consistent with how a specific
author writes, or whether it is AI-generated surrogate voice.

You are given 2-3 authentic samples from the author as a baseline.
Your job is NOT to detect AI in the abstract — it is to detect voice mismatch
against this specific author's established writing style.

Consider:
- Sentence-length burstiness (humans vary; AI is uniform)
- Vocabulary fit (author's usual register and word choices)
- Technical register and specificity
- Structural patterns (AI often uses numbered lists, polished openers, closing boilerplate)
- Personal tics, typos, informal grammar present in baseline but absent in candidate

Return verdict "human" if the candidate matches the author's voice well.
Return verdict "ai_like" if the candidate reads as clearly AI-generated surrogate voice.
Return verdict "uncertain" when evidence is ambiguous, too generic, or baseline fit is weak.
Return score 0.0 if the candidate matches the author's voice well.
Return score 1.0 if the candidate reads as clearly AI-generated surrogate voice.
Return confidence 0.0–1.0 for how certain you are.
Keep reasoning to one sentence focusing on the most decisive signal.
"""


def _build_user_prompt(text: str, baseline: AuthorBaseline) -> str:
    """Build the user-facing prompt for the classifier."""
    source_label = baseline.source_hint or "author samples"
    samples_block = "\n\n".join(
        f"[Sample {i + 1}]\n{s}" for i, s in enumerate(baseline.samples)
    )
    return (
        f"Author: {baseline.username}\n"
        f"Baseline ({source_label}):\n\n"
        f"{samples_block}\n\n"
        f"---\n\n"
        f"Candidate text:\n{text}\n\n"
        f"Compare: is the candidate consistent with this author's voice, "
        f"AI-generated, or uncertain? Output verdict, score (0=authentic, 1=AI), "
        f"confidence, and one-sentence reasoning."
    )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


async def score_ai_contamination(
    text: str,
    baseline: AuthorBaseline,
    model: str | None = None,
) -> AIDetectionResult:
    """Author-grounded LLM-based AI-contamination classifier.

    Compares candidate text against known-authentic baseline samples from the
    same author. Returns a structured result with score, confidence, and
    reasoning.

    ALLIE-405 cost caps apply: uses STANDARD tier (Gemini Flash / Claude Sonnet
    / GPT-4.1 depending on DEFAULT_PROVIDER). One LLM call per evaluation.
    No streaming, no tools.

    Args:
        text: The candidate text to evaluate.
        baseline: Author baseline with 2-3 authentic samples.
        model: Optional model override (PydanticAI model string). Defaults to
               STANDARD tier for the active provider.

    Returns:
        AIDetectionResult with score, confidence, and reasoning.

    Raises:
        Exception propagated from PydanticAI on hard failures. Callers that
        want failure-safe behaviour should wrap in try/except.
    """
    resolved_model = model or get_model(ModelTier.STANDARD)
    user_prompt = _build_user_prompt(text, baseline)

    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent: Agent[None, AIDetectionResult] = Agent(
        resolved_model,
        instructions=_SYSTEM_PROMPT,
        output_type=AIDetectionResult,
        history_processors=history_processors,
    )

    result = await agent.run(user_prompt)
    return _normalize_detection_result(result.output)


def _normalize_detection_result(result: AIDetectionResult) -> AIDetectionResult:
    """Force ambiguous score/confidence combinations into explicit uncertain state."""
    verdict: Literal["human", "ai_like", "uncertain"]
    if result.confidence < MIN_CONFIDENT_CLASSIFICATION:
        verdict = "uncertain"
    elif result.score >= AI_LIKE_THRESHOLD:
        verdict = "ai_like"
    elif result.score <= HUMAN_THRESHOLD:
        verdict = "human"
    elif UNCERTAIN_LOW <= result.score <= UNCERTAIN_HIGH:
        verdict = "uncertain"
    else:
        verdict = result.verdict
    return result.model_copy(update={"verdict": verdict})


def _clean_sample(text: str) -> str:
    return " ".join((text or "").split())[:MAX_SAMPLE_CHARS]


def _known_authentic_reason(row: Evidence, username: str) -> str | None:
    """Return why a row is safe enough for an author baseline, else None.

    This deliberately avoids stock phrase or regex heuristics. A baseline sample
    must have explicit provenance or a first-party author identity.
    """
    if row.ai_contamination_status == "human":
        return "previously_classified_human"
    if row.ai_contamination_status in {"ai_like", "uncertain", "error"}:
        return None

    normalized_username = username.casefold()
    author_id = (row.author_id or "").casefold()
    if normalized_username and author_id == normalized_username:
        return "author_id_matches_subject"

    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    metadata_author = str(
        metadata.get("author")
        or metadata.get("username")
        or metadata.get("user")
        or metadata.get("login")
        or ""
    ).casefold()
    if normalized_username and metadata_author == normalized_username:
        return "metadata_author_matches_subject"

    provenance = row.provenance_json if isinstance(row.provenance_json, dict) else {}
    if provenance.get("authored_by_subject") is True:
        return "provenance_authored_by_subject"
    if provenance.get("known_authentic") is True:
        return "provenance_known_authentic"

    # These are first-party source surfaces where the source account or local
    # private corpus is the collection boundary. They are weaker than explicit
    # author IDs, so they are only used when no prior classifier verdict exists.
    if row.source_type in {
        "github",
        "blog",
        "hackernews",
        "stackoverflow",
        "devto",
        "website",
        "claude_code",
    } and row.item_type in {
        "commit",
        "review",
        "review_comment",
        "issue_comment",
        "post",
        "answer",
        "comment",
        "session",
    }:
        return "first_party_source_surface"

    return None


async def sample_author_baseline(
    mini_id: str,
    db_session: AsyncSession,
    *,
    username: str,
    exclude_evidence_id: str | None = None,
    min_samples: int = MIN_BASELINE_SAMPLES,
    max_samples: int = MAX_BASELINE_SAMPLES,
) -> AuthorBaseline | None:
    """Sample known-authentic evidence rows for an author-grounded baseline."""
    stmt = (
        select(Evidence)
        .where(Evidence.mini_id == mini_id)
        .order_by(Evidence.evidence_date.desc().nullslast(), Evidence.created_at.desc())
        .limit(100)
    )
    rows = list((await db_session.execute(stmt)).scalars().all())

    samples: list[str] = []
    evidence_ids: list[str] = []
    source_reasons: list[str] = []
    for row in rows:
        if row.id == exclude_evidence_id:
            continue
        reason = _known_authentic_reason(row, username)
        if reason is None:
            continue
        sample = _clean_sample(row.raw_body or row.content)
        if len(sample) < MIN_BASELINE_CHARS:
            continue
        samples.append(sample)
        evidence_ids.append(row.id)
        source_reasons.append(f"{row.source_type}:{row.item_type}:{reason}")
        if len(samples) >= max_samples:
            break

    if len(samples) < min_samples:
        return None

    return AuthorBaseline(
        username=username,
        samples=samples,
        evidence_ids=evidence_ids,
        source_hint=", ".join(source_reasons),
    )


def classify_verdict(result: AIDetectionResult) -> Literal["human", "ai_like", "uncertain"]:
    """Classify a normalized detector result into the persisted verdict."""
    return _normalize_detection_result(result).verdict


async def classify_and_persist_evidence(
    mini_id: str,
    evidence_id: str,
    db_session: AsyncSession,
    *,
    username: str,
    classifier: ClassifierFn = score_ai_contamination,
) -> AIVerdict:
    """Classify one evidence row and persist score, verdict, and provenance."""
    row = (
        await db_session.execute(
            select(Evidence).where(Evidence.mini_id == mini_id, Evidence.id == evidence_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"Evidence row not found: {evidence_id}")

    now = datetime.now(timezone.utc)
    baseline = await sample_author_baseline(
        mini_id,
        db_session,
        username=username,
        exclude_evidence_id=evidence_id,
    )
    if baseline is None:
        row.ai_contamination_status = "insufficient_baseline"
        row.ai_contamination_score = None
        row.ai_contamination_confidence = None
        row.ai_contamination_reasoning = (
            f"Need at least {MIN_BASELINE_SAMPLES} known-authentic samples."
        )
        row.ai_contamination_checked_at = now
        row.ai_contamination_provenance_json = {
            "classifier": "author_grounded_llm",
            "baseline_evidence_ids": [],
            "baseline_sample_count": 0,
            "state": "insufficient_baseline",
        }
        await db_session.flush()
        return "insufficient_baseline"

    try:
        result = _normalize_detection_result(
            await classifier((row.raw_body or row.content)[:MAX_CANDIDATE_CHARS], baseline)
        )
    except Exception as exc:
        logger.warning(
            "ai_contamination classification failed mini_id=%s evidence_id=%s",
            mini_id,
            evidence_id,
            exc_info=True,
        )
        row.ai_contamination_status = "error"
        row.ai_contamination_reasoning = str(exc)[:500]
        row.ai_contamination_checked_at = now
        row.ai_contamination_provenance_json = {
            "classifier": "author_grounded_llm",
            "baseline_evidence_ids": baseline.evidence_ids,
            "baseline_sample_count": len(baseline.samples),
            "state": "error",
        }
        await db_session.flush()
        return "error"

    row.ai_contamination_status = result.verdict
    row.ai_contamination_score = result.score
    row.ai_contamination_confidence = result.confidence
    row.ai_contamination_reasoning = result.reasoning
    row.ai_contamination_checked_at = now
    row.ai_contamination_provenance_json = {
        "classifier": "author_grounded_llm",
        "baseline_evidence_ids": baseline.evidence_ids,
        "baseline_sample_count": len(baseline.samples),
        "baseline_source_hint": baseline.source_hint,
        "thresholds": {
            "ai_like": AI_LIKE_THRESHOLD,
            "human": HUMAN_THRESHOLD,
            "min_confidence": MIN_CONFIDENT_CLASSIFICATION,
        },
        "state": result.verdict,
    }
    await db_session.flush()
    return result.verdict


async def score_evidence_batch(
    mini_id: str,
    evidence_ids: list[str],
    session_factory: Any,
    *,
    username: str,
    classifier: ClassifierFn = score_ai_contamination,
) -> dict[str, int]:
    """Classify a batch of evidence rows, returning verdict counts.

    After classification, any rows verdict as ``ai_like`` are automatically
    marked ``explored=True`` so that explorer agents skip them without needing
    to read or process contaminated items.
    """
    from sqlalchemy import update as sa_update

    counts: dict[str, int] = {
        "human": 0,
        "ai_like": 0,
        "uncertain": 0,
        "insufficient_baseline": 0,
        "error": 0,
    }
    ai_like_ids: list[str] = []
    for evidence_id in dict.fromkeys(evidence_ids):
        async with session_factory() as session:
            async with session.begin():
                verdict = await classify_and_persist_evidence(
                    mini_id,
                    evidence_id,
                    session,
                    username=username,
                    classifier=classifier,
                )
                counts[verdict] = counts.get(verdict, 0) + 1
                if verdict == "ai_like":
                    ai_like_ids.append(evidence_id)

    if ai_like_ids:
        # Mark confirmed AI-generated items as explored so explorer agents skip them.
        # We set explored=True and record a note in ai_contamination_reasoning if empty.
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    sa_update(Evidence)
                    .where(
                        Evidence.mini_id == mini_id,
                        Evidence.id.in_(ai_like_ids),
                    )
                    .values(explored=True)
                )
        logger.info(
            "ai_contamination: marked %d ai_like items as explored=True for mini_id=%s",
            len(ai_like_ids),
            mini_id,
        )

    return counts
