"""Unit tests for eval/judge.py.

All LLM calls are mocked — no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.judge import (
    RubricScore,
    ScoreCard,
    SubjectSummary,
    TurnScore,
    _build_judge_prompt,
    score_response,
)
from eval.review import HeldOutReviewExpectation, ReviewSelection, compute_review_agreement


# ---------------------------------------------------------------------------
# ScoreCard model validation
# ---------------------------------------------------------------------------


class TestScoreCard:
    def test_valid_scorecard(self):
        sc = ScoreCard(
            overall_score=4,
            voice_match=3,
            factual_accuracy=5,
            framework_consistency=4,
            recency_bias_penalty=0.1,
            overall_rationale="Good fidelity overall.",
            rubric_scores=[
                RubricScore(criterion="nuance", score=4, rationale="Mostly nuanced."),
                RubricScore(criterion="specificity", score=3, rationale="Somewhat specific."),
            ],
        )
        assert sc.overall_score == 4
        assert sc.voice_match == 3
        assert sc.factual_accuracy == 5
        assert sc.framework_consistency == 4
        assert sc.recency_bias_penalty == pytest.approx(0.1)
        assert len(sc.rubric_scores) == 2

    def test_recency_bias_penalty_bounds_enforced(self):
        with pytest.raises(Exception):
            ScoreCard(
                overall_score=4,
                voice_match=4,
                factual_accuracy=4,
                recency_bias_penalty=1.2,
                overall_rationale="test",
            )

        with pytest.raises(Exception):
            ScoreCard(
                overall_score=4,
                voice_match=4,
                factual_accuracy=4,
                recency_bias_penalty=-0.1,
                overall_rationale="test",
            )

    def test_score_bounds_enforced(self):
        with pytest.raises(Exception):
            ScoreCard(
                overall_score=6,  # out of range
                voice_match=3,
                factual_accuracy=3,
                overall_rationale="test",
            )

    def test_score_zero_rejected(self):
        with pytest.raises(Exception):
            ScoreCard(
                overall_score=0,  # below minimum
                voice_match=3,
                factual_accuracy=3,
                overall_rationale="test",
            )

    def test_rubric_dict_property(self):
        sc = ScoreCard(
            overall_score=3,
            voice_match=3,
            factual_accuracy=3,
            overall_rationale="ok",
            rubric_scores=[
                RubricScore(criterion="alpha", score=2, rationale="weak"),
                RubricScore(criterion="beta", score=5, rationale="strong"),
            ],
        )
        d = sc.rubric_dict
        assert d == {"alpha": 2, "beta": 5}

    def test_average_rubric_score(self):
        sc = ScoreCard(
            overall_score=3,
            voice_match=3,
            factual_accuracy=3,
            overall_rationale="ok",
            rubric_scores=[
                RubricScore(criterion="a", score=2, rationale="x"),
                RubricScore(criterion="b", score=4, rationale="y"),
            ],
        )
        assert sc.average_rubric_score == pytest.approx(3.0)

    def test_empty_rubric_score_returns_zero(self):
        sc = ScoreCard(
            overall_score=3,
            voice_match=3,
            factual_accuracy=3,
            overall_rationale="ok",
            rubric_scores=[],
        )
        assert sc.average_rubric_score == 0.0

    def test_review_selection_supported(self):
        sc = ScoreCard(
            overall_score=4,
            voice_match=4,
            factual_accuracy=4,
            overall_rationale="good",
            review_selection=ReviewSelection(
                predicted_verdict="request_changes",
                selected_blocker_ids=["missing_tests"],
                selected_comment_ids=["rename_helper"],
                rationale="The response blocks on tests and mentions a rename.",
            ),
        )
        assert sc.review_selection is not None
        assert sc.review_selection.predicted_verdict == "request_changes"


# ---------------------------------------------------------------------------
# _build_judge_prompt
# ---------------------------------------------------------------------------


class TestBuildJudgePrompt:
    def test_includes_reference_and_response(self):
        prompt = _build_judge_prompt(
            reference_answer="The reference text here.",
            rubric=[{"nuance": "Avoids dogmatism"}],
            mini_response="The mini said this.",
            turn_id="test_turn",
        )
        assert "The reference text here." in prompt
        assert "The mini said this." in prompt
        assert "nuance" in prompt
        assert "Avoids dogmatism" in prompt

    def test_includes_turn_id_when_given(self):
        prompt = _build_judge_prompt(
            reference_answer="ref",
            rubric=[],
            mini_response="resp",
            turn_id="my_turn_id",
        )
        assert "my_turn_id" in prompt

    def test_no_turn_id_does_not_crash(self):
        prompt = _build_judge_prompt(
            reference_answer="ref",
            rubric=[],
            mini_response="resp",
        )
        assert "Reference Answer" in prompt
        assert "Mini's Response" in prompt

    def test_multiple_rubric_items(self):
        prompt = _build_judge_prompt(
            reference_answer="ref",
            rubric=[
                {"position": "Acknowledges both sides"},
                {"nuance": "Avoids absolutes"},
                {"specificity": "Names concrete examples"},
            ],
            mini_response="resp",
        )
        assert "position" in prompt
        assert "nuance" in prompt
        assert "specificity" in prompt

    def test_includes_held_out_review_candidates(self):
        prompt = _build_judge_prompt(
            reference_answer="ref",
            rubric=[],
            mini_response="resp",
            held_out_review=HeldOutReviewExpectation.from_dict(
                {
                    "verdict": "request_changes",
                    "blocker_candidates": [
                        {
                            "id": "missing_tests",
                            "summary": "Needs regression coverage",
                            "expected": True,
                        }
                    ],
                    "comment_candidates": [
                        {
                            "id": "rename_helper",
                            "summary": "Rename helper for clarity",
                            "expected": False,
                        }
                    ],
                }
            ),
        )
        assert "Held-Out Review Candidates" in prompt
        assert "Expected verdict: request_changes" in prompt
        assert "missing_tests" in prompt
        assert "rename_helper" in prompt


# ---------------------------------------------------------------------------
# score_response (mocked PydanticAI)
# ---------------------------------------------------------------------------


class TestScoreResponse:
    @pytest.fixture
    def mock_scorecard(self) -> ScoreCard:
        return ScoreCard(
            overall_score=4,
            voice_match=3,
            factual_accuracy=4,
            overall_rationale="Good match with reference voice.",
            rubric_scores=[
                RubricScore(
                    criterion="position_nuanced",
                    score=4,
                    rationale="Position well-articulated.",
                ),
                RubricScore(
                    criterion="no_dogmatism",
                    score=3,
                    rationale="Some hedging present.",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_returns_scorecard(self, mock_scorecard):
        mock_result = MagicMock()
        mock_result.output = mock_scorecard

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        with patch("eval.judge.Agent", return_value=mock_agent_instance):
            result = await score_response(
                reference_answer="The developer's known position.",
                rubric=[{"position_nuanced": "Says something nuanced"}],
                mini_response="The mini's response here.",
                turn_id="test_turn",
            )

        assert isinstance(result, ScoreCard)
        assert result.overall_score == 4
        assert result.voice_match == 3

    @pytest.mark.asyncio
    async def test_rationale_is_present(self, mock_scorecard):
        mock_result = MagicMock()
        mock_result.output = mock_scorecard

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        with patch("eval.judge.Agent", return_value=mock_agent_instance):
            result = await score_response(
                reference_answer="ref",
                rubric=[],
                mini_response="response",
            )

        assert result.overall_rationale
        assert len(result.overall_rationale) > 0

    @pytest.mark.asyncio
    async def test_rubric_scores_included(self, mock_scorecard):
        mock_result = MagicMock()
        mock_result.output = mock_scorecard

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        with patch("eval.judge.Agent", return_value=mock_agent_instance):
            result = await score_response(
                reference_answer="ref",
                rubric=[
                    {"position_nuanced": "Check position"},
                    {"no_dogmatism": "Check dogmatism"},
                ],
                mini_response="response",
            )

        assert len(result.rubric_scores) == 2
        criteria = [rs.criterion for rs in result.rubric_scores]
        assert "position_nuanced" in criteria
        assert "no_dogmatism" in criteria

    @pytest.mark.asyncio
    async def test_uses_standard_model_by_default(self, mock_scorecard):
        mock_result = MagicMock()
        mock_result.output = mock_scorecard

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        captured_model: list[str] = []

        def capture_agent(model, **kwargs):
            captured_model.append(model)
            return mock_agent_instance

        with patch("eval.judge.Agent", side_effect=capture_agent):
            await score_response(
                reference_answer="ref",
                rubric=[],
                mini_response="response",
            )

        assert captured_model, "Agent should have been instantiated"
        # Should be a valid PydanticAI model string (provider:model-name)
        assert ":" in captured_model[0], (
            f"Expected provider:model format, got {captured_model[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_model_override_respected(self, mock_scorecard):
        mock_result = MagicMock()
        mock_result.output = mock_scorecard

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        captured_model: list[str] = []

        def capture_agent(model, **kwargs):
            captured_model.append(model)
            return mock_agent_instance

        with patch("eval.judge.Agent", side_effect=capture_agent):
            await score_response(
                reference_answer="ref",
                rubric=[],
                mini_response="response",
                model="anthropic:claude-haiku-4-5",
            )

        assert captured_model[0] == "anthropic:claude-haiku-4-5"

    @pytest.mark.asyncio
    async def test_passes_held_out_review_into_prompt(self, mock_scorecard):
        mock_result = MagicMock()
        mock_result.output = mock_scorecard

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = AsyncMock(return_value=mock_result)

        captured_prompts: list[str] = []

        async def capture_run(prompt: str):
            captured_prompts.append(prompt)
            return mock_result

        mock_agent_instance.run = capture_run

        with patch("eval.judge.Agent", return_value=mock_agent_instance):
            await score_response(
                reference_answer="ref",
                rubric=[],
                mini_response="response",
                held_out_review=HeldOutReviewExpectation.from_dict(
                    {
                        "verdict": "approve",
                        "comment_candidates": [
                            {
                                "id": "rename_helper",
                                "summary": "Rename helper for clarity",
                                "expected": True,
                            }
                        ],
                    }
                ),
            )

        assert captured_prompts
        assert "Held-Out Review Candidates" in captured_prompts[0]
        assert "rename_helper" in captured_prompts[0]


class TestReviewAgreement:
    def test_compute_review_agreement_partial_match(self):
        expectation = HeldOutReviewExpectation.from_dict(
            {
                "verdict": "request_changes",
                "blocker_candidates": [
                    {
                        "id": "missing_tests",
                        "summary": "Needs regression coverage",
                        "expected": True,
                    },
                    {
                        "id": "feature_flag",
                        "summary": "Needs a rollout guard",
                        "expected": False,
                    },
                ],
                "comment_candidates": [
                    {
                        "id": "rename_helper",
                        "summary": "Rename helper for clarity",
                        "expected": True,
                    }
                ],
            }
        )

        agreement = compute_review_agreement(
            expectation,
            ReviewSelection(
                predicted_verdict="request_changes",
                selected_blocker_ids=["missing_tests", "feature_flag"],
                selected_comment_ids=[],
                rationale="Over-selected blockers and missed the comment.",
            ),
        )

        assert agreement.verdict_match is True
        assert agreement.blocker_precision == pytest.approx(0.5)
        assert agreement.blocker_recall == pytest.approx(1.0)
        assert agreement.blocker_f1 == pytest.approx(2 / 3)
        assert agreement.comment_f1 == 0.0
        assert agreement.overall_agreement == pytest.approx((1 + (2 / 3) + 0) / 3)

    def test_compute_review_agreement_empty_sets_match_cleanly(self):
        expectation = HeldOutReviewExpectation.from_dict(
            {
                "verdict": "approve",
                "blocker_candidates": [],
                "comment_candidates": [],
            }
        )

        agreement = compute_review_agreement(
            expectation, ReviewSelection(predicted_verdict="approve")
        )

        assert agreement.verdict_match is True
        assert agreement.blocker_f1 == pytest.approx(1.0)
        assert agreement.comment_f1 == pytest.approx(1.0)
        assert agreement.overall_agreement == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# SubjectSummary aggregation
# ---------------------------------------------------------------------------


class TestSubjectSummary:
    def _make_turn_score(
        self,
        overall: int,
        voice: int,
        factual: int,
        framework: int = 3,
        recency_penalty: float = 0.0,
        rubric: dict | None = None,
    ) -> TurnScore:
        rubric_scores = []
        if rubric:
            rubric_scores = [
                RubricScore(criterion=k, score=v, rationale="test") for k, v in rubric.items()
            ]
        sc = ScoreCard(
            overall_score=overall,
            voice_match=voice,
            factual_accuracy=factual,
            framework_consistency=framework,
            recency_bias_penalty=recency_penalty,
            overall_rationale="test rationale",
            rubric_scores=rubric_scores,
        )
        return TurnScore(
            subject="testuser",
            turn_id="t1",
            prompt="test?",
            reference_answer="ref",
            mini_response="resp",
            scorecard=sc,
        )

    def test_averages(self):
        summary = SubjectSummary(subject="testuser")
        summary.turn_scores = [
            self._make_turn_score(4, 3, 5, framework=4, recency_penalty=0.1),
            self._make_turn_score(2, 2, 3, framework=2, recency_penalty=0.5),
        ]
        assert summary.avg_overall == pytest.approx(3.0)
        assert summary.avg_voice == pytest.approx(2.5)
        assert summary.avg_factual == pytest.approx(4.0)
        assert summary.avg_framework_consistency == pytest.approx(3.0)
        assert summary.avg_recency_bias_penalty == pytest.approx(0.3)

    def test_empty_averages_are_zero(self):
        summary = SubjectSummary(subject="testuser")
        assert summary.avg_overall == 0.0
        assert summary.avg_voice == 0.0
        assert summary.avg_factual == 0.0
        assert summary.avg_framework_consistency == 0.0
        assert summary.avg_recency_bias_penalty == 0.0

    def test_weak_rubric_items_detected(self):
        summary = SubjectSummary(subject="testuser")
        summary.turn_scores = [
            self._make_turn_score(3, 3, 3, rubric={"strong_item": 4, "weak_item": 2}),
            self._make_turn_score(3, 3, 3, rubric={"strong_item": 5, "weak_item": 1}),
        ]
        weak = summary.weak_rubric_items(threshold=2)
        assert "weak_item" in weak
        assert "strong_item" not in weak

    def test_failed_turns_excluded_from_averages(self):
        summary = SubjectSummary(subject="testuser")
        good = self._make_turn_score(4, 4, 4)
        failed = TurnScore(
            subject="testuser",
            turn_id="failed",
            prompt="?",
            reference_answer="ref",
            mini_response="",
            scorecard=ScoreCard(
                overall_score=1,
                voice_match=1,
                factual_accuracy=1,
                framework_consistency=1,
                recency_bias_penalty=1.0,
                overall_rationale="failed",
            ),
            error="connection refused",
        )
        summary.turn_scores = [good, failed]
        # Only the good turn should count
        assert summary.avg_overall == pytest.approx(4.0)

    def test_adversarial_turn_metrics(self):
        summary = SubjectSummary(subject="testuser")
        summary.turn_scores = [
            self._make_turn_score(2, 3, 3, framework=3, rubric={"weakness": 3}),
            self._make_turn_score(4, 4, 4, framework=4),
            self._make_turn_score(5, 5, 5, framework=5),
        ]
        summary.turn_scores[0].case_type = "adversarial"
        summary.turn_scores[1].case_type = "baseline"
        summary.turn_scores[2].case_type = "adversarial"

        assert summary.adversarial_turn_count == 2
        assert summary.adversarial_pass_count == 1
        assert summary.adversarial_fail_count == 1
        assert summary.adversarial_pass_rate == 0.5
        assert summary.non_adversarial_turn_count == 1
        assert summary.non_adversarial_pass_rate == 1.0
