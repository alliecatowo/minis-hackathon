"""Tests for agreement scorecard binding in the fidelity eval harness.

Verifies that:
 - _fetch_agreement_scorecard resolves mini ID then fetches scorecard
 - 404/auth errors return None gracefully
 - run_eval populates summary.agreement_scorecard
 - report_to_json includes agreement_scorecard key
 - render_report surfaces scorecard fields in Markdown
 - _check_regression includes scorecard deltas when prior data has scorecards
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.judge import RubricScore, ScoreCard, SubjectSummary
from eval.report import _check_regression, render_report, report_to_json
from eval.runner import EvalReport, _fetch_agreement_scorecard, run_eval


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINI_RESPONSE = {"id": "mini-uuid-123", "username": "testuser", "status": "ready"}

_SCORECARD_RESPONSE = {
    "mini_id": "mini-uuid-123",
    "username": "testuser",
    "cycles_count": 5,
    "approval_accuracy": 0.8,
    "blocker_precision": 0.75,
    "comment_overlap": 0.6,
    "trend": {"direction": "up", "delta": 0.05},
}


def _make_mock_client(mini_resp_status: int = 200, sc_resp_status: int = 200):
    """Build a mock httpx.AsyncClient that serves the mini lookup and scorecard."""

    class MockResp:
        def __init__(self, status_code: int, body: dict):
            self.status_code = status_code
            self._body = body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"HTTP {self.status_code}")

        def json(self):
            return self._body

    client = MagicMock()
    call_count = 0

    async def mock_get(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        if "by-username" in url:
            return MockResp(mini_resp_status, _MINI_RESPONSE)
        else:
            return MockResp(sc_resp_status, _SCORECARD_RESPONSE)

    client.get = mock_get
    return client


# ---------------------------------------------------------------------------
# _fetch_agreement_scorecard unit tests
# ---------------------------------------------------------------------------


class TestFetchAgreementScorecard:
    @pytest.mark.asyncio
    async def test_returns_scorecard_on_success(self):
        client = _make_mock_client()
        result = await _fetch_agreement_scorecard(client, "http://test", "testuser")
        assert result is not None
        assert result["cycles_count"] == 5
        assert result["approval_accuracy"] == 0.8

    @pytest.mark.asyncio
    async def test_returns_none_when_mini_not_found(self):
        client = _make_mock_client(mini_resp_status=404)
        result = await _fetch_agreement_scorecard(client, "http://test", "unknownuser")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_scorecard_auth_fails(self):
        client = _make_mock_client(sc_resp_status=403)
        result = await _fetch_agreement_scorecard(client, "http://test", "testuser")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        client = MagicMock()

        async def fail_get(url, **kwargs):
            raise Exception("connection refused")

        client.get = fail_get
        result = await _fetch_agreement_scorecard(client, "http://test", "testuser")
        assert result is None

    @pytest.mark.asyncio
    async def test_sends_auth_header_when_token_provided(self):
        captured_headers: list[dict] = []

        class CapturingResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                if "by-username" in self._url:
                    return _MINI_RESPONSE
                return _SCORECARD_RESPONSE

        client = MagicMock()

        async def mock_get(url: str, headers=None, **kwargs):
            resp = CapturingResp()
            resp._url = url
            captured_headers.append(headers or {})
            return resp

        client.get = mock_get
        await _fetch_agreement_scorecard(client, "http://test", "testuser", token="my-token")
        assert all("Authorization" in h for h in captured_headers)
        assert all("Bearer my-token" in h["Authorization"] for h in captured_headers)


# ---------------------------------------------------------------------------
# run_eval integration: scorecard is attached to SubjectSummary
# ---------------------------------------------------------------------------


def _make_scorecard_obj(overall: int = 4) -> ScoreCard:
    return ScoreCard(
        overall_score=overall,
        voice_match=3,
        factual_accuracy=4,
        framework_consistency=4,
        recency_bias_penalty=0.0,
        overall_rationale="Good.",
        rubric_scores=[RubricScore(criterion="pos", score=4, rationale="ok")],
    )


def _write_subject_yaml(path: Path, username: str) -> Path:
    f = path / f"{username}.yaml"
    f.write_text(f"username: {username}\ndisplay_name: {username.title()}\n")
    return f


def _write_turns_yaml(path: Path, username: str) -> Path:
    content = (
        f"subject: {username}\n"
        "turns:\n"
        "  - id: t1\n"
        '    prompt: "Question?"\n'
        "    reference_answer: |\n"
        "      Answer.\n"
        "    rubric:\n"
        "      - crit: check it\n"
    )
    f = path / f"{username}.yaml"
    f.write_text(content)
    return f


class TestRunEvalScorecardBinding:
    @pytest.mark.asyncio
    async def test_scorecard_attached_to_summary(self, tmp_path: Path):
        (tmp_path / "s").mkdir(exist_ok=True)
        (tmp_path / "t").mkdir(exist_ok=True)
        sf = _write_subject_yaml(tmp_path / "s", "user1")
        tf = _write_turns_yaml(tmp_path / "t", "user1")

        with (
            patch(
                "eval.runner._resolve_mini_id",
                new=AsyncMock(return_value="mini-id-user1"),
            ),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="response")),
            patch(
                "eval.runner.score_response",
                new=AsyncMock(return_value=_make_scorecard_obj()),
            ),
            patch(
                "eval.runner._fetch_agreement_scorecard",
                new=AsyncMock(return_value=_SCORECARD_RESPONSE),
            ),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        assert len(report.summaries) == 1
        summary = report.summaries[0]
        assert summary.agreement_scorecard is not None
        assert summary.agreement_scorecard["cycles_count"] == 5
        assert summary.agreement_scorecard["approval_accuracy"] == 0.8

    @pytest.mark.asyncio
    async def test_scorecard_none_when_fetch_fails(self, tmp_path: Path):
        (tmp_path / "s").mkdir(exist_ok=True)
        (tmp_path / "t").mkdir(exist_ok=True)
        sf = _write_subject_yaml(tmp_path / "s", "user2")
        tf = _write_turns_yaml(tmp_path / "t", "user2")

        with (
            patch(
                "eval.runner._resolve_mini_id",
                new=AsyncMock(return_value="mini-id-user2"),
            ),
            patch("eval.runner._send_chat_turn", new=AsyncMock(return_value="response")),
            patch(
                "eval.runner.score_response",
                new=AsyncMock(return_value=_make_scorecard_obj()),
            ),
            patch(
                "eval.runner._fetch_agreement_scorecard",
                new=AsyncMock(return_value=None),
            ),
        ):
            report = await run_eval(
                subject_files=[sf],
                turn_files=[tf],
                base_url="http://test",
            )

        assert report.summaries[0].agreement_scorecard is None


# ---------------------------------------------------------------------------
# report_to_json: agreement_scorecard field present
# ---------------------------------------------------------------------------


class TestReportToJsonScorecard:
    def _make_summary(self, scorecard: dict | None) -> SubjectSummary:
        from eval.judge import TurnScore

        ts = TurnScore(
            subject="testuser",
            turn_id="t1",
            prompt="p",
            reference_answer="r",
            mini_response="m",
            scorecard=_make_scorecard_obj(),
        )
        s = SubjectSummary(subject="testuser", turn_scores=[ts])
        s.agreement_scorecard = scorecard
        return s

    def test_scorecard_present_in_json(self):
        summary = self._make_summary(_SCORECARD_RESPONSE)
        report = EvalReport(summaries=[summary])
        payload = report_to_json(report)
        subject = payload["subjects"][0]
        assert "agreement_scorecard" in subject
        assert subject["agreement_scorecard"]["cycles_count"] == 5

    def test_scorecard_null_when_none(self):
        summary = self._make_summary(None)
        report = EvalReport(summaries=[summary])
        payload = report_to_json(report)
        subject = payload["subjects"][0]
        assert subject["agreement_scorecard"] is None


# ---------------------------------------------------------------------------
# render_report: scorecard section in Markdown
# ---------------------------------------------------------------------------


class TestRenderReportScorecard:
    def _make_summary(self, scorecard: dict | None) -> SubjectSummary:
        from eval.judge import TurnScore

        ts = TurnScore(
            subject="testuser",
            turn_id="t1",
            prompt="p",
            reference_answer="r",
            mini_response="m",
            scorecard=_make_scorecard_obj(),
        )
        s = SubjectSummary(subject="testuser", turn_scores=[ts])
        s.agreement_scorecard = scorecard
        return s

    def test_renders_scorecard_metrics(self):
        summary = self._make_summary(_SCORECARD_RESPONSE)
        report = EvalReport(summaries=[summary])
        md = render_report(report)
        assert "Agreement Scorecard" in md
        assert "80.0%" in md  # approval_accuracy 0.8
        assert "75.0%" in md  # blocker_precision 0.75
        assert "60.0%" in md  # comment_overlap 0.6
        assert "up" in md

    def test_renders_unavailable_when_none(self):
        summary = self._make_summary(None)
        report = EvalReport(summaries=[summary])
        md = render_report(report)
        assert "not available" in md

    def test_renders_no_cycles_when_zero(self):
        sc = {**_SCORECARD_RESPONSE, "cycles_count": 0}
        summary = self._make_summary(sc)
        report = EvalReport(summaries=[summary])
        md = render_report(report)
        assert "no completed review cycles" in md


# ---------------------------------------------------------------------------
# _check_regression: scorecard delta lines
# ---------------------------------------------------------------------------


class TestRegressionScorecardDeltas:
    def _make_summary(self, scorecard: dict | None) -> SubjectSummary:
        from eval.judge import TurnScore

        ts = TurnScore(
            subject="alice",
            turn_id="t1",
            prompt="p",
            reference_answer="r",
            mini_response="m",
            scorecard=_make_scorecard_obj(overall=4),
        )
        s = SubjectSummary(subject="alice", turn_scores=[ts])
        s.agreement_scorecard = scorecard
        return s

    def _write_prior(self, tmp_path: Path, scorecard: dict | None, overall_avg: float = 4.0) -> Path:
        data = {
            "overall_avg": overall_avg,
            "subjects": [
                {
                    "subject": "alice",
                    "agreement_scorecard": scorecard,
                }
            ],
        }
        p = tmp_path / "prior.json"
        p.write_text(json.dumps(data))
        return p

    def test_delta_lines_when_scorecard_improves(self, tmp_path: Path):
        prior_sc = {**_SCORECARD_RESPONSE, "approval_accuracy": 0.6}
        current_sc = {**_SCORECARD_RESPONSE, "approval_accuracy": 0.8}
        prior_path = self._write_prior(tmp_path, prior_sc)

        summary = self._make_summary(current_sc)
        report = EvalReport(summaries=[summary])
        note = _check_regression(report, prior_path)
        assert note is not None
        assert "Scorecard delta" in note
        assert "Approval" in note
        assert "+0.20" in note

    def test_no_delta_lines_when_no_prior_scorecard(self, tmp_path: Path):
        prior_path = self._write_prior(tmp_path, None)
        summary = self._make_summary(_SCORECARD_RESPONSE)
        report = EvalReport(summaries=[summary])
        note = _check_regression(report, prior_path)
        # No scorecard delta lines expected (prior has no scorecard)
        if note:
            assert "Scorecard delta" not in note

    def test_returns_none_for_missing_prior_file(self, tmp_path: Path):
        summary = self._make_summary(_SCORECARD_RESPONSE)
        report = EvalReport(summaries=[summary])
        note = _check_regression(report, tmp_path / "nonexistent.json")
        assert note is None
