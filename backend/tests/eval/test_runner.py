"""Unit tests for eval/runner.py.

Both the HTTP calls (to mini chat endpoint) and the judge scoring are mocked —
no real network requests or LLM calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.judge import RubricScore, ScoreCard
from eval.review import ReviewSelection
from eval.runner import (
    EvalReport,
    GoldenTurn,
    GoldenTurnFile,
    SubjectConfig,
    _send_chat_turn,
    run_eval,
)


# ---------------------------------------------------------------------------
# SubjectConfig loading
# ---------------------------------------------------------------------------


class TestSubjectConfig:
    def test_from_yaml(self, tmp_path: Path):
        yaml_content = """\
username: testuser
display_name: Test User
why_selected: |
  Great test subject.
expected_voice_markers:
  - marker one
  - marker two
"""
        f = tmp_path / "testuser.yaml"
        f.write_text(yaml_content)
        cfg = SubjectConfig.from_yaml(f)
        assert cfg.username == "testuser"
        assert cfg.display_name == "Test User"
        assert len(cfg.expected_voice_markers) == 2

    def test_missing_optional_fields(self, tmp_path: Path):
        yaml_content = "username: minimal\ndisplay_name: Minimal\n"
        f = tmp_path / "minimal.yaml"
        f.write_text(yaml_content)
        cfg = SubjectConfig.from_yaml(f)
        assert cfg.username == "minimal"
        assert cfg.expected_voice_markers == []
        assert cfg.why_selected == ""


# ---------------------------------------------------------------------------
# GoldenTurnFile loading
# ---------------------------------------------------------------------------


class TestGoldenTurnFile:
    def test_from_yaml(self, tmp_path: Path):
        yaml_content = """\
subject: testuser
turns:
  - id: turn_one
    prompt: "What do you think about X?"
    reference_answer: |
      I think X is fine.
    rubric:
      - position: "Expresses a position on X"
  - id: turn_two
    prompt: "Tell me about Y."
    reference_answer: |
      Y is great.
    rubric:
      - enthusiasm: "Shows enthusiasm for Y"
"""
        f = tmp_path / "testuser.yaml"
        f.write_text(yaml_content)
        gtf = GoldenTurnFile.from_yaml(f)
        assert gtf.subject == "testuser"
        assert len(gtf.turns) == 2
        assert gtf.turns[0].id == "turn_one"
        assert gtf.turns[1].id == "turn_two"
        assert len(gtf.turns[0].rubric) == 1
        assert "position" in gtf.turns[0].rubric[0]

    def test_empty_turns(self, tmp_path: Path):
        yaml_content = "subject: empty\nturns: []\n"
        f = tmp_path / "empty.yaml"
        f.write_text(yaml_content)
        gtf = GoldenTurnFile.from_yaml(f)
        assert gtf.turns == []


# ---------------------------------------------------------------------------
# GoldenTurn.from_dict
# ---------------------------------------------------------------------------


class TestGoldenTurn:
    def test_from_dict(self):
        data = {
            "id": "test_id",
            "prompt": "test prompt",
            "reference_answer": "test answer",
            "rubric": [{"criterion": "check this"}],
            "case_type": "adversarial",
        }
        turn = GoldenTurn.from_dict(data)
        assert turn.id == "test_id"
        assert turn.case_type == "adversarial"
        assert turn.rubric == [{"criterion": "check this"}]

    def test_missing_rubric_defaults_empty(self):
        data = {"id": "no_rubric", "prompt": "p", "reference_answer": "r"}
        turn = GoldenTurn.from_dict(data)
        assert turn.rubric == []
        assert turn.case_type == "baseline"

    def test_parses_held_out_review(self):
        turn = GoldenTurn.from_dict(
            {
                "id": "review_turn",
                "prompt": "Review this PR",
                "reference_answer": "Request changes for missing tests.",
                "held_out_review": {
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
                },
            }
        )
        assert turn.held_out_review is not None
        assert turn.held_out_review.verdict == "request_changes"
        assert turn.held_out_review.expected_blocker_ids == ["missing_tests"]


# ---------------------------------------------------------------------------
# _send_chat_turn (HTTP mocking)
# ---------------------------------------------------------------------------


class TestSendChatTurn:
    @pytest.mark.asyncio
    async def test_collects_sse_chunks(self):
        """Should concatenate 'chunk' events from SSE stream."""
        sse_lines = [
            'data: {"type": "chunk", "data": "Hello "}',
            'data: {"type": "chunk", "data": "world"}',
            'data: {"type": "done", "data": ""}',
        ]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "text/event-stream"}
        mock_response.aiter_lines = AsyncMock(return_value=iter(sse_lines))

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = mock_aiter_lines

        mock_client = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _send_chat_turn(
            client=mock_client,
            base_url="http://test",
            mini_id="test-mini-id",
            prompt="Hello?",
        )
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_includes_auth_token(self):
        """Should set Authorization header when token is provided."""
        sse_lines = ['data: {"type": "done", "data": ""}']
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "text/event-stream"}

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = mock_aiter_lines

        captured_headers: list[dict] = []

        class MockStreamContext:
            async def __aenter__(self_inner):
                return mock_response

            async def __aexit__(self_inner, *args):
                return False

        mock_client = MagicMock()

        def mock_stream(method, url, **kwargs):
            captured_headers.append(kwargs.get("headers", {}))
            return MockStreamContext()

        mock_client.stream = mock_stream

        await _send_chat_turn(
            client=mock_client,
            base_url="http://test",
            mini_id="test-mini-id",
            prompt="Hello?",
            token="my-jwt-token",
        )
        assert any("Authorization" in h for h in captured_headers)
        assert any("Bearer my-jwt-token" in h.get("Authorization", "") for h in captured_headers)

    @pytest.mark.asyncio
    async def test_handles_plain_json_response(self):
        """Should handle non-SSE JSON response gracefully."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.aread = AsyncMock(
            return_value=json.dumps({"response": "plain json response"}).encode()
        )

        class MockStreamContext:
            async def __aenter__(self_inner):
                return mock_response

            async def __aexit__(self_inner, *args):
                return False

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=MockStreamContext())

        result = await _send_chat_turn(
            client=mock_client,
            base_url="http://test",
            mini_id="test-mini-id",
            prompt="Hello?",
        )
        assert result == "plain json response"


# ---------------------------------------------------------------------------
# run_eval (end-to-end with mocked HTTP + judge)
# ---------------------------------------------------------------------------


def _make_scorecard(overall: int = 4) -> ScoreCard:
    return ScoreCard(
        overall_score=overall,
        voice_match=3,
        factual_accuracy=4,
        framework_consistency=4,
        recency_bias_penalty=0.0,
        overall_rationale="Good fidelity.",
        rubric_scores=[
            RubricScore(criterion="position", score=4, rationale="Position clear."),
        ],
    )


def _write_subject_yaml(path: Path, username: str) -> Path:
    content = f"username: {username}\ndisplay_name: {username.title()}\n"
    f = path / f"{username}.yaml"
    f.write_text(content)
    return f


def _write_turns_yaml(path: Path, username: str, num_turns: int = 2) -> Path:
    turns = []
    for i in range(num_turns):
        turns.append(
            f"  - id: turn_{i}\n"
            f'    prompt: "Question {i}?"\n'
            f"    reference_answer: |\n"
            f"      Answer {i}.\n"
            f"    rubric:\n"
            f"      - criterion_{i}: check {i}\n"
        )
    content = f"subject: {username}\nturns:\n" + "".join(turns)
    f = path / f"{username}.yaml"
    f.write_text(content)
    return f


def _write_turns_with_case_types(
    path: Path,
    username: str,
    case_types: list[str],
) -> Path:
    turns = []
    for i, case_type in enumerate(case_types):
        turns.append(
            f"  - id: turn_{i}\n"
            f"    case_type: {case_type}\n"
            f'    prompt: "Question {i}?"\n'
            f"    reference_answer: |\n"
            f"      Answer {i}.\n"
            f"    rubric:\n"
            f"      - criterion_{i}: check {i}\n"
        )
    content = f"subject: {username}\nturns:\n" + "".join(turns)
    f = path / f"{username}.yaml"
    f.write_text(content)
    return f


def _write_review_turns_yaml(path: Path, username: str) -> Path:
    content = f"""\
subject: {username}
turns:
  - id: held_out_review
    prompt: "Review this change."
    reference_answer: |
      The real reviewer would request changes because regression coverage is missing.
    rubric:
      - review_policy: "Blocks on missing tests"
    held_out_review:
      verdict: request_changes
      blocker_candidates:
        - id: missing_tests
          summary: "Needs regression coverage for the new branch"
          expected: true
        - id: feature_flag
          summary: "Needs a rollout guard"
          expected: false
      comment_candidates:
        - id: rename_helper
          summary: "Rename helper for clarity"
          expected: true
        - id: line_wrap
          summary: "Wrap the long line"
          expected: false
"""
    f = path / f"{username}.yaml"
    f.write_text(content)
    return f


class TestRunEval:
    @pytest.mark.asyncio
    async def test_report_shape(self, tmp_path: Path):
        """run_eval should return an EvalReport with correct structure."""
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf = _write_subject_yaml(subjects_dir, "testuser")
        tf = _write_turns_yaml(turns_dir, "testuser", num_turns=2)

        mock_scorecard = _make_scorecard(overall=4)

        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch(
                "eval.runner._send_chat_turn", new=AsyncMock(return_value="The mini's answer here.")
            ),
            patch("eval.runner.score_response", new=AsyncMock(return_value=mock_scorecard)),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        assert isinstance(report, EvalReport)
        assert len(report.summaries) == 1
        summary = report.summaries[0]
        assert summary.subject == "testuser"
        assert len(summary.turn_scores) == 2

    @pytest.mark.asyncio
    async def test_adversarial_summary_metrics(self, tmp_path: Path):
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf = _write_subject_yaml(subjects_dir, "novel_user")
        tf = _write_turns_with_case_types(
            turns_dir,
            "novel_user",
            ["adversarial", "baseline", "adversarial"],
        )

        scorecards = iter([_make_scorecard(overall=3), _make_scorecard(overall=5), _make_scorecard(overall=5)])
        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="response")),
            patch(
                "eval.runner.score_response",
                new=AsyncMock(side_effect=lambda **_: next(scorecards)),
            ),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        summary = report.summaries[0]
        assert summary.adversarial_turn_count == 2
        assert summary.adversarial_pass_count == 1
        assert summary.adversarial_fail_count == 1
        assert summary.adversarial_pass_rate == 0.5
        assert summary.non_adversarial_turn_count == 1
        assert summary.non_adversarial_pass_rate == 1.0

    @pytest.mark.asyncio
    async def test_all_turns_scored(self, tmp_path: Path):
        """Each golden turn should produce one TurnScore."""
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf = _write_subject_yaml(subjects_dir, "alice")
        tf = _write_turns_yaml(turns_dir, "alice", num_turns=3)

        mock_scorecard = _make_scorecard()

        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="response")),
            patch("eval.runner.score_response", new=AsyncMock(return_value=mock_scorecard)),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        assert len(report.summaries[0].turn_scores) == 3
        assert all(not ts.failed for ts in report.summaries[0].turn_scores)

    @pytest.mark.asyncio
    async def test_http_failure_recorded_as_error(self, tmp_path: Path):
        """HTTP failure should produce a TurnScore with error set, not crash."""
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf = _write_subject_yaml(subjects_dir, "failuser")
        tf = _write_turns_yaml(turns_dir, "failuser", num_turns=1)

        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch(
                "eval.runner._send_chat_turn",
                new=AsyncMock(side_effect=Exception("connection refused")),
            ),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        assert len(report.summaries[0].turn_scores) == 1
        ts = report.summaries[0].turn_scores[0]
        assert ts.failed
        assert "connection refused" in ts.error

    @pytest.mark.asyncio
    async def test_judge_failure_recorded_as_error(self, tmp_path: Path):
        """Judge failure should produce a TurnScore with error set, not crash."""
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf = _write_subject_yaml(subjects_dir, "judgeuser")
        tf = _write_turns_yaml(turns_dir, "judgeuser", num_turns=1)

        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="some response")),
            patch(
                "eval.runner.score_response", new=AsyncMock(side_effect=Exception("judge failed"))
            ),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        ts = report.summaries[0].turn_scores[0]
        assert ts.failed
        assert "judge failed" in ts.error

    @pytest.mark.asyncio
    async def test_missing_turn_file_skips_subject(self, tmp_path: Path):
        """Subject with no matching turn file should be skipped gracefully."""
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        # Write subject YAML but NO matching turns YAML
        sf = _write_subject_yaml(subjects_dir, "noturns")

        report = await run_eval(
            subject_files=[sf],
            turn_files=[],
            base_url="http://test",
        )

        assert len(report.summaries) == 0

    @pytest.mark.asyncio
    async def test_multiple_subjects(self, tmp_path: Path):
        """Multiple subjects should each get their own SubjectSummary."""
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf1 = _write_subject_yaml(subjects_dir, "alice")
        sf2 = _write_subject_yaml(subjects_dir, "bob")
        tf1 = _write_turns_yaml(turns_dir, "alice", num_turns=2)
        tf2 = _write_turns_yaml(turns_dir, "bob", num_turns=1)

        mock_scorecard = _make_scorecard()

        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="response")),
            patch("eval.runner.score_response", new=AsyncMock(return_value=mock_scorecard)),
        ):
            report = await run_eval(
                subject_files=[sf1, sf2],
                turn_files=[tf1, tf2],
                base_url="http://test",
            )

        assert len(report.summaries) == 2
        subjects_found = {s.subject for s in report.summaries}
        assert subjects_found == {"alice", "bob"}

    @pytest.mark.asyncio
    async def test_overall_avg_computed(self, tmp_path: Path):
        """EvalReport.overall_avg() should average across all subjects and turns."""
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf = _write_subject_yaml(subjects_dir, "avg_test")
        tf = _write_turns_yaml(turns_dir, "avg_test", num_turns=2)

        sc1 = _make_scorecard(overall=3)
        sc2 = _make_scorecard(overall=5)
        scorecards = iter([sc1, sc2])

        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="resp")),
            patch(
                "eval.runner.score_response",
                new=AsyncMock(side_effect=lambda **kw: next(scorecards)),
            ),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        assert report.overall_avg() == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_review_turn_computes_review_agreement(self, tmp_path: Path):
        subjects_dir = tmp_path / "subjects"
        turns_dir = tmp_path / "turns"
        subjects_dir.mkdir()
        turns_dir.mkdir()

        sf = _write_subject_yaml(subjects_dir, "reviewer")
        tf = _write_review_turns_yaml(turns_dir, "reviewer")

        scorecard = ScoreCard(
            overall_score=4,
            voice_match=4,
            factual_accuracy=4,
            overall_rationale="Matches review policy reasonably well.",
            rubric_scores=[
                RubricScore(
                    criterion="review_policy",
                    score=4,
                    rationale="It blocks on the main missing test issue.",
                )
            ],
            review_selection=ReviewSelection(
                predicted_verdict="request_changes",
                selected_blocker_ids=["missing_tests"],
                selected_comment_ids=["rename_helper", "line_wrap"],
                rationale="Catches the real blocker and one extra nit.",
            ),
        )

        with (
            patch("eval.runner._resolve_mini_id", new=AsyncMock(return_value="test-mini-id")),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="request changes")),
            patch(
                "eval.runner.score_response", new=AsyncMock(return_value=scorecard)
            ) as mock_score,
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        ts = report.summaries[0].turn_scores[0]
        assert ts.review_agreement is not None
        assert ts.review_agreement.verdict_match is True
        assert ts.review_agreement.blocker_f1 == pytest.approx(1.0)
        assert ts.review_agreement.comment_precision == pytest.approx(0.5)
        assert ts.review_agreement.comment_recall == pytest.approx(1.0)
        assert ts.review_agreement.comment_f1 == pytest.approx(2 / 3)

        call_kwargs = mock_score.await_args.kwargs
        assert call_kwargs["held_out_review"] is not None
        assert call_kwargs["held_out_review"].expected_comment_ids == ["rename_helper"]

    def test_checked_in_alliecatowo_fixture_includes_held_out_review(self):
        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "eval"
            / "golden_turns"
            / "alliecatowo.yaml"
        )
        fixture = GoldenTurnFile.from_yaml(fixture_path)
        turn = next(t for t in fixture.turns if t.id == "code_review_style")

        assert turn.held_out_review is not None
        assert turn.held_out_review.verdict == "request_changes"
        assert turn.held_out_review.expected_blocker_ids == [
            "missing_tests",
            "oversized_pr",
        ]
        assert turn.held_out_review.expected_comment_ids == ["clarity-pass"]

    def test_checked_in_alliecatowo_fixture_includes_recency_framework_turn(self):
        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "eval"
            / "golden_turns"
            / "alliecatowo.yaml"
        )
        fixture = GoldenTurnFile.from_yaml(fixture_path)
        turn = next(t for t in fixture.turns if t.id == "recency_vs_framework_boundary")

        rubric_keys = {list(item.keys())[0] for item in turn.rubric}
        assert "long_horizon_default" in rubric_keys
        assert "recency_as_signal_not_policy" in rubric_keys
        assert "canonical_hottest_take_consistency" in rubric_keys

    def test_checked_in_alliecatowo_fixture_includes_adversarial_cases(self):
        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "eval"
            / "golden_turns"
            / "alliecatowo.yaml"
        )
        fixture = GoldenTurnFile.from_yaml(fixture_path)
        adversarial_turns = [t for t in fixture.turns if t.id.startswith("adversarial_")]
        adversarial_ids = {t.id for t in adversarial_turns}

        assert adversarial_ids == {
            "adversarial_unfamiliar_repo",
            "adversarial_competing_values",
            "adversarial_generic_advice_trap",
            "adversarial_audience_mismatch",
        }
        assert all(t.case_type == "adversarial" for t in adversarial_turns)
