"""LLM-as-judge scoring for fidelity evaluation.

Takes a reference answer, rubric, and mini response, and returns a ScoreCard
with 1-5 scores and rationale. Uses a STANDARD-tier model (~2k tokens per call).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.core.models import ModelTier, get_model
from eval.review import HeldOutReviewExpectation, ReviewAgreement, ReviewSelection

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """\
You are an expert evaluator assessing how well an AI personality clone's response
matches a human developer's known writing style and positions.

You will be given:
1. A reference answer that captures the developer's known position (from their blog,
   talks, or documented opinions).
2. A rubric with specific criteria to check.
3. The mini's actual response to evaluate.

Score each rubric criterion from 1 to 5:
  1 = Criterion completely absent or contradicted
  2 = Criterion only weakly present, significantly misses the mark
  3 = Criterion partially met; some elements present but incomplete
  4 = Criterion mostly met with minor gaps
  5 = Criterion fully and clearly met

Also score:
- voice_match (1-5): How well does the tone, style, and personality match the
  reference? 1 = sounds nothing like them, 5 = indistinguishable
- factual_accuracy (1-5): Are any factual claims (projects, dates, positions)
  accurate relative to the reference? 1 = significant factual errors,
  5 = fully accurate
- framework_consistency (1-5): Does the response preserve the subject's stable,
  long-horizon decision framework instead of drifting into ad-hoc takes?
- recency_bias_penalty (0.0-1.0): Penalty for over-weighting recent/local signal
  when it conflicts with the subject's canonical long-horizon framework.
  0.0 = no recency bias, 1.0 = severe recency bias

If the prompt includes held-out review candidates, also populate
review_selection with:
- predicted_verdict: one of approve, request_changes, comment, unclear
- selected_blocker_ids: blocker candidate IDs the mini clearly raises
- selected_comment_ids: non-blocker candidate IDs the mini clearly raises

Be conservative. Only select a candidate ID when the issue is actually present
in the mini's response.

Be strict. A 3 is average. Reserve 5 for genuinely impressive fidelity.
For each criterion, provide exactly one sentence of rationale.
"""


class RubricScore(BaseModel):
    """Score and rationale for a single rubric criterion."""

    criterion: str = Field(description="Rubric criterion identifier")
    score: int = Field(ge=1, le=5, description="Score 1-5")
    rationale: str = Field(description="One-sentence explanation of score")


class ScoreCard(BaseModel):
    """Complete evaluation result for one (turn, mini_response) pair."""

    overall_score: int = Field(ge=1, le=5, description="Overall fidelity score 1-5")
    voice_match: int = Field(ge=1, le=5, description="Tone/style match 1-5")
    factual_accuracy: int = Field(ge=1, le=5, description="Factual accuracy 1-5")
    framework_consistency: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Consistency with stable long-horizon framework 1-5",
    )
    recency_bias_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Penalty for overweighting recent/local signal over canonical framework"
        ),
    )
    rubric_scores: list[RubricScore] = Field(
        default_factory=list,
        description="Per-criterion rubric scores",
    )
    overall_rationale: str = Field(
        description="One-sentence overall assessment",
    )
    review_selection: ReviewSelection | None = Field(
        default=None,
        description="Optional structured review prediction extracted from the response.",
    )

    @property
    def rubric_dict(self) -> dict[str, int]:
        """Rubric scores as a plain dict for easy access."""
        return {rs.criterion: rs.score for rs in self.rubric_scores}

    @property
    def average_rubric_score(self) -> float:
        """Average across all rubric criterion scores."""
        if not self.rubric_scores:
            return 0.0
        return sum(rs.score for rs in self.rubric_scores) / len(self.rubric_scores)


def _build_judge_prompt(
    reference_answer: str,
    rubric: list[dict[str, Any]],
    mini_response: str,
    turn_id: str = "",
    held_out_review: HeldOutReviewExpectation | None = None,
) -> str:
    """Build the user-turn prompt for the judge model."""
    rubric_lines = "\n".join(
        f"  - {list(item.keys())[0]}: {list(item.values())[0]}" for item in rubric
    )

    parts = []
    if turn_id:
        parts.append(f"## Turn: {turn_id}\n")

    parts.append(f"## Reference Answer\n{reference_answer.strip()}\n")
    parts.append(f"## Rubric Criteria\n{rubric_lines}\n")
    parts.append(f"## Mini's Response\n{mini_response.strip()}\n")
    if held_out_review:
        blocker_lines = "\n".join(
            f"  - {candidate.id}: {candidate.summary} (expected={str(candidate.expected).lower()})"
            for candidate in held_out_review.blocker_candidates
        )
        comment_lines = "\n".join(
            f"  - {candidate.id}: {candidate.summary} (expected={str(candidate.expected).lower()})"
            for candidate in held_out_review.comment_candidates
        )
        parts.append(
            "## Held-Out Review Candidates\n"
            f"Expected verdict: {held_out_review.verdict}\n"
            "Blocker candidates:\n"
            f"{blocker_lines or '  - none'}\n"
            "Comment candidates:\n"
            f"{comment_lines or '  - none'}\n"
        )
    parts.append(
        "## Your Task\n"
        "Score the mini's response against each rubric criterion, then give overall "
        "scores for voice_match, factual_accuracy, framework_consistency, and an overall_score. "
        "Also provide recency_bias_penalty from 0.0 to 1.0. "
        "Return a JSON object matching the ScoreCard schema. "
        "If held-out review candidates are present, populate review_selection by "
        "choosing only from those candidate IDs."
    )

    return "\n".join(parts)


async def score_response(
    reference_answer: str,
    rubric: list[dict[str, Any]],
    mini_response: str,
    turn_id: str = "",
    model: str | None = None,
    held_out_review: HeldOutReviewExpectation | None = None,
) -> ScoreCard:
    """Score a mini's response against a reference answer + rubric.

    Args:
        reference_answer: The developer's known position / reference text.
        rubric: List of dicts, each with one key (criterion name) and one value
                (description of what to check).
        mini_response: The mini's actual chat response.
        turn_id: Optional turn ID for logging context.
        model: Optional model override; defaults to STANDARD tier.

    Returns:
        ScoreCard with scores and rationale.
    """
    resolved_model = model or get_model(ModelTier.STANDARD)

    agent: Agent[None, ScoreCard] = Agent(
        resolved_model,
        instructions=JUDGE_SYSTEM_PROMPT,
        output_type=ScoreCard,
    )

    prompt = _build_judge_prompt(
        reference_answer=reference_answer,
        rubric=rubric,
        mini_response=mini_response,
        turn_id=turn_id,
        held_out_review=held_out_review,
    )

    logger.debug("Scoring turn %r with model %s", turn_id, resolved_model)
    result = await agent.run(prompt)
    return result.output


@dataclass
class TurnScore:
    """A scored evaluation turn — input + output bundled together."""

    subject: str
    turn_id: str
    prompt: str
    reference_answer: str
    mini_response: str
    scorecard: ScoreCard
    case_type: str = "baseline"
    review_agreement: ReviewAgreement | None = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def is_adversarial(self) -> bool:
        return self.case_type.lower().strip() == "adversarial"

    @property
    def pass_threshold(self) -> bool:
        return (not self.failed) and self.scorecard.overall_score >= 4


def compute_framework_summary(frameworks: list[dict]) -> dict:
    """Compute summary metrics from a list of decision-framework objects.

    Each framework dict is expected to carry at least:
      - ``confidence``  (float 0.0–1.0)
      - ``revision``    (int, number of times the framework has been updated)

    Returns a dict with keys:
      total, mean_confidence, max_revision, high_band_count, low_band_count

    Where:
      - high_band  = confidence >= 0.7
      - low_band   = confidence < 0.4
    """
    if not frameworks:
        return {
            "total": 0,
            "mean_confidence": 0.0,
            "max_revision": 0,
            "high_band_count": 0,
            "low_band_count": 0,
        }

    total = len(frameworks)
    confidences = [float(f.get("confidence", 0.0)) for f in frameworks]
    revisions = [int(f.get("revision", 0)) for f in frameworks]

    mean_confidence = sum(confidences) / total
    max_revision = max(revisions) if revisions else 0
    high_band_count = sum(1 for c in confidences if c >= 0.7)
    low_band_count = sum(1 for c in confidences if c < 0.4)

    return {
        "total": total,
        "mean_confidence": mean_confidence,
        "max_revision": max_revision,
        "high_band_count": high_band_count,
        "low_band_count": low_band_count,
    }


@dataclass
class SubjectSummary:
    """Aggregate statistics for all turns of one subject."""

    subject: str
    turn_scores: list[TurnScore] = field(default_factory=list)
    # Agreement scorecard fetched from the API after golden turns are scored.
    # None if the API call failed or returned no data.
    agreement_scorecard: dict | None = None
    # Decision-framework profile summary fetched from the API.
    # None if the endpoint returned 404 or the request failed.
    decision_frameworks_summary: dict | None = None

    def _case_turn_scores(self, case_type: str) -> list[TurnScore]:
        return [
            ts
            for ts in self.turn_scores
            if ts.case_type.lower().strip() == case_type.lower().strip()
        ]

    @property
    def adversarial_turns(self) -> list[TurnScore]:
        return self._case_turn_scores("adversarial")

    @property
    def non_adversarial_turns(self) -> list[TurnScore]:
        return [ts for ts in self.turn_scores if not ts.is_adversarial]

    def _case_pass_rate(self, turns: list[TurnScore]) -> float:
        if not turns:
            return 0.0
        return sum(1 for ts in turns if ts.pass_threshold) / len(turns)

    @property
    def adversarial_turn_count(self) -> int:
        return len(self.adversarial_turns)

    @property
    def non_adversarial_turn_count(self) -> int:
        return len(self.non_adversarial_turns)

    @property
    def adversarial_pass_count(self) -> int:
        return sum(1 for ts in self.adversarial_turns if ts.pass_threshold)

    @property
    def adversarial_fail_count(self) -> int:
        return len(self.adversarial_turns) - self.adversarial_pass_count

    @property
    def adversarial_pass_rate(self) -> float:
        return self._case_pass_rate(self.adversarial_turns)

    @property
    def non_adversarial_pass_rate(self) -> float:
        return self._case_pass_rate(self.non_adversarial_turns)

    @property
    def avg_overall(self) -> float:
        scored = [t for t in self.turn_scores if not t.failed]
        if not scored:
            return 0.0
        return sum(t.scorecard.overall_score for t in scored) / len(scored)

    @property
    def avg_voice(self) -> float:
        scored = [t for t in self.turn_scores if not t.failed]
        if not scored:
            return 0.0
        return sum(t.scorecard.voice_match for t in scored) / len(scored)

    @property
    def avg_factual(self) -> float:
        scored = [t for t in self.turn_scores if not t.failed]
        if not scored:
            return 0.0
        return sum(t.scorecard.factual_accuracy for t in scored) / len(scored)

    @property
    def avg_framework_consistency(self) -> float:
        scored = [t for t in self.turn_scores if not t.failed]
        if not scored:
            return 0.0
        return sum(t.scorecard.framework_consistency for t in scored) / len(scored)

    @property
    def avg_recency_bias_penalty(self) -> float:
        scored = [t for t in self.turn_scores if not t.failed]
        if not scored:
            return 0.0
        return sum(t.scorecard.recency_bias_penalty for t in scored) / len(scored)

    @property
    def avg_review_agreement(self) -> float:
        scored = [t.review_agreement for t in self.turn_scores if t.review_agreement is not None]
        if not scored:
            return 0.0
        return sum(item.overall_agreement for item in scored) / len(scored)

    @property
    def avg_blocker_f1(self) -> float:
        scored = [t.review_agreement for t in self.turn_scores if t.review_agreement is not None]
        if not scored:
            return 0.0
        return sum(item.blocker_f1 for item in scored) / len(scored)

    @property
    def avg_comment_f1(self) -> float:
        scored = [t.review_agreement for t in self.turn_scores if t.review_agreement is not None]
        if not scored:
            return 0.0
        return sum(item.comment_f1 for item in scored) / len(scored)

    def weak_rubric_items(self, threshold: int = 2) -> list[str]:
        """Return rubric criteria that consistently score at or below threshold."""
        criterion_scores: dict[str, list[int]] = {}
        for ts in self.turn_scores:
            if ts.failed:
                continue
            for rs in ts.scorecard.rubric_scores:
                criterion_scores.setdefault(rs.criterion, []).append(rs.score)
        return [
            criterion
            for criterion, scores in criterion_scores.items()
            if scores and sum(scores) / len(scores) <= threshold
        ]
