from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.review_predictor_agent import predict_review
from app.models.schemas import ReviewPredictionRequestV1


def _live_llm_skip_reason() -> str | None:
    if os.environ.get("RUN_LIVE_LLM_CONTRACT_TESTS", "").lower() not in {"1", "true", "yes"}:
        return "set RUN_LIVE_LLM_CONTRACT_TESTS=true to run live LLM contract tests"

    provider = os.environ.get("DEFAULT_PROVIDER", "gemini").lower()
    if provider == "openai":
        required = ("OPENAI_API_KEY",)
    elif provider == "anthropic":
        required = ("ANTHROPIC_API_KEY",)
    else:
        required = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

    if not any(os.environ.get(name) for name in required):
        return f"missing live LLM secret for DEFAULT_PROVIDER={provider}: one of {', '.join(required)}"

    return None


def _mini() -> SimpleNamespace:
    return SimpleNamespace(
        id="live-contract-mini",
        username="contract-reviewer",
        system_prompt=(
            "You are contract-reviewer. In code review, you care most about test coverage, "
            "safe rollout plans, and explicit failure modes. You do not give generic LGTM "
            "feedback when a change touches authentication or background workers."
        ),
        memory_content=(
            "Review history: repeatedly blocked changes that touched auth or queue workers "
            "without focused tests, rollback notes, or migration safety checks."
        ),
        evidence_cache=(
            "PR review: Please add a regression test around token refresh retries before merge.\n"
            "PR review: This queue-worker change needs a rollback plan and metrics before rollout.\n"
            "PR review: I am fine with small refactors when the blast radius is explicit."
        ),
        principles_json={
            "principles": [
                {
                    "trigger": "auth or worker changes without tests",
                    "action": "request changes until regression tests exist",
                    "value": "prevent silent production regressions",
                    "intensity": 0.95,
                    "framework_id": "fw-test-safety",
                },
                {
                    "trigger": "rollout risk is unclear",
                    "action": "ask for rollback notes and metrics",
                    "value": "make operational risk reversible",
                    "intensity": 0.9,
                    "framework_id": "fw-rollout-safety",
                },
            ],
            "decision_frameworks": {
                "version": "decision_frameworks_v1",
                "frameworks": [
                    {"framework_id": "fw-test-safety", "confidence": 0.9, "revision": 2},
                    {"framework_id": "fw-rollout-safety", "confidence": 0.86, "revision": 1},
                ],
            },
        },
        behavioral_context_json={
            "summary": "Direct and safety-oriented in code review.",
            "contexts": [
                {
                    "context": "code_review",
                    "summary": "Blocks risky auth and worker changes until tests and rollout safety are clear.",
                    "behaviors": ["requests tests", "asks for rollback plans"],
                }
            ],
        },
        motivations_json={
            "motivations": [],
            "motivation_chains": [],
            "summary": "Values production safety and review precision.",
        },
        values_json=None,
    )


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_review_predictor_contract_returns_artifact_or_gated(monkeypatch):
    """Live-gated contract: real LLM predictor must not return the local smoke fallback."""
    if reason := _live_llm_skip_reason():
        pytest.skip(reason)

    monkeypatch.setenv("REVIEW_PREDICTOR_LLM_MAX_TURNS", "2")
    monkeypatch.setenv("REVIEW_PREDICTOR_LLM_REQUEST_TOKEN_LIMIT", "12000")
    monkeypatch.setenv("REVIEW_PREDICTOR_LLM_RESPONSE_TOKEN_LIMIT", "2048")
    monkeypatch.setenv("REVIEW_PREDICTOR_LLM_TOTAL_TOKEN_LIMIT", "14000")

    body = ReviewPredictionRequestV1(
        repo_name="acme/auth-service",
        title="Move token refresh retries into worker",
        description=(
            "Refactors token refresh retry handling into a background worker. "
            "The patch changes auth/session.py and worker/retry_queue.py but does not add tests yet."
        ),
        changed_files=["backend/auth/session.py", "backend/workers/retry_queue.py"],
        diff_summary="Auth retry path now enqueues failed refresh attempts for async worker processing.",
        author_model="junior_peer",
        delivery_context="normal",
    )

    with patch("app.core.review_predictor_agent.load_same_repo_precedent", AsyncMock(return_value=None)):
        result = await predict_review(_mini(), body, AsyncMock())

    assert result.version == "review_prediction_v1"
    assert result.reviewer_username == "contract-reviewer"
    assert result.repo_name == "acme/auth-service"
    assert result.artifact_summary is not None
    assert result.artifact_summary.artifact_type == "pull_request"
    assert result.artifact_summary.title == "Move token refresh retries into worker"
    assert result.mode in {"llm", "gated"}
    assert result.mode != "local_smoke"

    if result.prediction_available:
        assert result.mode == "llm"
        assert result.unavailable_reason is None
        assert result.expressed_feedback.summary.strip()
        assert result.private_assessment.confidence >= 0
    else:
        assert result.mode == "gated"
        assert result.unavailable_reason
        assert result.unavailable_reason.startswith("LLM review predictor returned")
        assert result.expressed_feedback.approval_state == "uncertain"
        assert result.expressed_feedback.comments == []
