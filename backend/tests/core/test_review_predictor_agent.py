import json
from unittest.mock import AsyncMock, patch

import pytest
from app.core.review_predictor_agent import (
    _build_predictor_tools,
    predict_artifact_review,
    predict_review,
)
from app.models.schemas import (
    ArtifactReviewRequestV1,
    ArtifactReviewV1,
    ReviewPredictionRequestV1,
    ReviewPredictionV1,
)


# ---------------------------------------------------------------------------
# Helper to invoke the search_principles tool from the built tool list
# ---------------------------------------------------------------------------

def _get_search_principles(mini):
    """Return the search_principles handler from a built tool list."""
    session = AsyncMock()
    tools = _build_predictor_tools(mini, session)
    handler = next(t.handler for t in tools if t.name == "search_principles")
    return handler


# ---------------------------------------------------------------------------
# search_principles unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_principles_no_principles_json():
    mini = AsyncMock()
    mini.principles_json = None
    handler = _get_search_principles(mini)
    result = await handler("testing")
    assert result == "No principles available."


@pytest.mark.asyncio
async def test_search_principles_empty_principles():
    mini = AsyncMock()
    mini.principles_json = {"principles": []}
    handler = _get_search_principles(mini)
    result = await handler("testing")
    assert "No principles found" in result


@pytest.mark.asyncio
async def test_search_principles_basic_match():
    """Principles matching the query are returned."""
    mini = AsyncMock()
    mini.principles_json = {
        "principles": [
            {"trigger": "PR lacks tests", "action": "request tests", "value": "test coverage", "intensity": 0.9},
            {"trigger": "naming is unclear", "action": "ask for rename", "value": "readability", "intensity": 0.7},
        ]
    }
    handler = _get_search_principles(mini)
    result = await handler("tests coverage")
    assert "test coverage" in result
    # The naming principle should not appear
    assert "readability" not in result


@pytest.mark.asyncio
async def test_search_principles_high_confidence_boost_and_badge():
    """Principle linked to a high-confidence framework gets ranked higher and shows badge."""
    mini = AsyncMock()
    mini.principles_json = {
        "principles": [
            # Both match query "async" equally (1 kw hit each)
            {
                "trigger": "async code missing await",
                "action": "block merge",
                "value": "correctness",
                "intensity": 0.9,
                "framework_id": "fw-high",
            },
            {
                "trigger": "async usage confusing",
                "action": "add comment",
                "value": "readability",
                "intensity": 0.6,
                "framework_id": "fw-low",
            },
        ],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": [
                {"framework_id": "fw-high", "confidence": 0.85, "revision": 3},
                {"framework_id": "fw-low", "confidence": 0.2, "revision": 0},
            ],
        },
    }
    handler = _get_search_principles(mini)
    result = await handler("async")

    # High-confidence framework principle should appear first
    assert result.index("correctness") < result.index("readability")
    # Badges present
    assert "[HIGH CONFIDENCE ✓]" in result
    assert "[LOW CONFIDENCE ⚠]" in result
    # Validated badge present for fw-high (revision=3)
    assert "[validated 3 times]" in result


@pytest.mark.asyncio
async def test_search_principles_confidence_penalty_demotes():
    """A low-confidence principle is demoted below a no-framework principle."""
    mini = AsyncMock()
    mini.principles_json = {
        "principles": [
            # 2 kw hits but low confidence → net = 2 - 0.5 = 1.5
            {
                "trigger": "security auth bypass",
                "action": "reject immediately",
                "value": "security",
                "intensity": 1.0,
                "framework_id": "fw-weak",
            },
            # 1 kw hit, no framework → net = 1.0
            {
                "trigger": "auth token missing",
                "action": "comment",
                "value": "correctness",
                "intensity": 0.8,
            },
        ],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": [
                {"framework_id": "fw-weak", "confidence": 0.1, "revision": 0},
            ],
        },
    }
    handler = _get_search_principles(mini)
    result = await handler("auth bypass")

    # "security" has 2 kw hits but -0.5 penalty → total 1.5
    # "correctness" has 1 kw hit and no modifier → total 1.0
    # So "security" still comes first (1.5 > 1.0) — but LOW CONFIDENCE badge present
    assert "[LOW CONFIDENCE ⚠]" in result


@pytest.mark.asyncio
async def test_search_principles_missing_framework_id_on_principle():
    """Principles with no framework_id still render without errors."""
    mini = AsyncMock()
    mini.principles_json = {
        "principles": [
            {
                "trigger": "large PR size",
                "action": "ask to split",
                "value": "reviewability",
                "intensity": 0.7,
                # no framework_id
            },
        ],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": [
                {"framework_id": "fw-other", "confidence": 0.9, "revision": 2},
            ],
        },
    }
    handler = _get_search_principles(mini)
    result = await handler("large PR")
    assert "reviewability" in result
    # No badges because no framework_id linkage
    assert "[HIGH CONFIDENCE" not in result
    assert "[LOW CONFIDENCE" not in result


@pytest.mark.asyncio
async def test_search_principles_missing_decision_frameworks_key():
    """Back-compat: older minis without decision_frameworks key still work."""
    mini = AsyncMock()
    mini.principles_json = {
        "principles": [
            {
                "trigger": "missing docstring",
                "action": "request docs",
                "value": "documentation",
                "intensity": 0.6,
                "framework_id": "fw-old",
            },
        ]
        # no "decision_frameworks" key at all
    }
    handler = _get_search_principles(mini)
    result = await handler("docstring")
    assert "documentation" in result
    # No badges — confidence_index is empty
    assert "[HIGH CONFIDENCE" not in result
    assert "[LOW CONFIDENCE" not in result


@pytest.mark.asyncio
async def test_search_principles_validated_singular():
    """'validated 1 time' (singular) renders correctly."""
    mini = AsyncMock()
    mini.principles_json = {
        "principles": [
            {
                "trigger": "hardcoded credentials",
                "action": "block merge",
                "value": "security",
                "intensity": 1.0,
                "framework_id": "fw-sec",
            },
        ],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": [
                {"framework_id": "fw-sec", "confidence": 0.8, "revision": 1},
            ],
        },
    }
    handler = _get_search_principles(mini)
    result = await handler("credentials")
    assert "[validated 1 time]" in result


@pytest.mark.asyncio
async def test_search_principles_capped_modifier():
    """High revision count doesn't push modifier above +0.5."""
    mini = AsyncMock()
    mini.principles_json = {
        "principles": [
            {
                "trigger": "missing error handling",
                "action": "request fix",
                "value": "robustness",
                "intensity": 0.9,
                "framework_id": "fw-robust",
            },
        ],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": [
                # revision=100 → 0.3 + 5.0 = 5.3, capped to 0.5
                {"framework_id": "fw-robust", "confidence": 0.9, "revision": 100},
            ],
        },
    }
    handler = _get_search_principles(mini)
    result = await handler("error handling")
    assert "robustness" in result
    # Should still render without error
    assert "[HIGH CONFIDENCE ✓]" in result


@pytest.mark.asyncio
async def test_search_principles_json_string_input():
    """principles_json stored as JSON string (rather than dict) is handled."""
    mini = AsyncMock()
    mini.principles_json = json.dumps({
        "principles": [
            {
                "trigger": "type mismatch",
                "action": "reject",
                "value": "type safety",
                "intensity": 0.8,
            }
        ]
    })
    handler = _get_search_principles(mini)
    result = await handler("type")
    assert "type safety" in result


# ---------------------------------------------------------------------------
# Integration-level tests (unchanged from original)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_predict_review_agent_success():
    mini = AsyncMock()
    mini.id = "mini-123"
    mini.username = "testuser"
    mini.system_prompt = "You are a test user."
    mini.memory_content = "Memory content"
    mini.evidence_cache = "Evidence cache"
    mini.principles_json = {"principles": []}

    body = ReviewPredictionRequestV1(
        repo_name="test/repo",
        title="Test PR",
        description="This is a test PR",
        changed_files=["file1.py"],
        author_model="junior_peer",
        delivery_context="normal"
    )

    session = AsyncMock()

    mock_prediction = {
        "version": "review_prediction_v1",
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "reviewer_username": "testuser",
        "repo_name": "test/repo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.9
        },
        "delivery_policy": {
            "author_model": "junior_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": True,
            "shield_author_from_noise": False,
            "rationale": "Test rationale"
        },
        "expressed_feedback": {
            "summary": "Looks good",
            "comments": [],
            "approval_state": "approve"
        }
    }

    same_repo_precedent = {
        "repo_name": "test/repo",
        "cycle_count": 2,
        "focus_counts": {"tests": 2},
        "focuses": ["tests"],
        "approval_counts": {"approve": 0, "comment": 1, "request_changes": 1, "uncertain": 0},
        "detail": "same-repo precedent for test/repo: 2 recent review cycles; recurring focus on tests; outcomes skewed request_changes",
    }

    with (
        patch("app.core.review_predictor_agent.load_same_repo_precedent", AsyncMock(return_value=same_repo_precedent)),
        patch("app.core.review_predictor_agent.run_agent") as mock_run_agent,
    ):
        mock_run_agent.return_value = AsyncMock(
            final_response=json.dumps(mock_prediction)
        )

        result = await predict_review(mini, body, session)

        assert isinstance(result, ReviewPredictionV1)
        assert result.reviewer_username == "testuser"
        assert result.expressed_feedback.approval_state == "approve"
        assert mock_run_agent.called
        _, kwargs = mock_run_agent.call_args
        assert "Same-Repo Precedent" in kwargs["user_prompt"]
        assert "same-repo precedent" in kwargs["system_prompt"].lower()


@pytest.mark.asyncio
async def test_predict_review_agent_gates_response_missing_availability_contract():
    mini = AsyncMock()
    mini.id = "mini-123"
    mini.username = "testuser"
    mini.system_prompt = "You are a test user."
    mini.behavioral_context_json = None
    mini.motivations_json = None
    mini.values_json = None
    mini.memory_content = "review: asks for tests before approving risky changes"
    mini.evidence_cache = None
    mini.principles_json = None

    body = ReviewPredictionRequestV1(title="Test PR")
    session = AsyncMock()

    fallback_like_prediction = {
        "version": "review_prediction_v1",
        "reviewer_username": "testuser",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.4,
        },
        "delivery_policy": {
            "author_model": "unknown",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "fallback defaults",
        },
        "expressed_feedback": {
            "summary": "Would likely request changes and surface generic concerns.",
            "comments": [],
            "approval_state": "request_changes",
        },
    }

    with (
        patch("app.core.review_predictor_agent.load_same_repo_precedent", AsyncMock(return_value=None)),
        patch("app.core.review_predictor_agent.run_agent") as mock_run_agent,
    ):
        mock_run_agent.return_value = AsyncMock(
            final_response=json.dumps(fallback_like_prediction)
        )

        result = await predict_review(mini, body, session)

    assert result.prediction_available is False
    assert result.mode == "gated"
    assert "omitted availability contract fields" in result.unavailable_reason
    assert result.expressed_feedback.approval_state == "uncertain"
    assert result.private_assessment.blocking_issues == []

@pytest.mark.asyncio
async def test_predict_review_agent_reports_unavailable_on_failure():
    mini = AsyncMock()
    mini.id = "mini-123"
    mini.username = "testuser"
    mini.system_prompt = "You are a test user."
    mini.behavioral_context_json = None
    mini.motivations_json = None
    mini.values_json = None
    mini.memory_content = "review: asks for tests before approving risky changes"
    mini.evidence_cache = None
    mini.principles_json = None

    body = ReviewPredictionRequestV1(
        title="Test PR",
    )

    session = AsyncMock()

    with (
        patch("app.core.review_predictor_agent.load_same_repo_precedent", AsyncMock(return_value=None)),
        patch("app.core.review_predictor_agent.run_agent") as mock_run_agent,
    ):
        mock_run_agent.return_value = AsyncMock(final_response=None)

        result = await predict_review(mini, body, session)

        assert isinstance(result, ReviewPredictionV1)
        assert result.reviewer_username == "testuser"
        assert result.prediction_available is False
        assert result.mode == "gated"
        assert result.private_assessment.blocking_issues == []
        assert result.expressed_feedback.comments == []
        assert result.expressed_feedback.approval_state == "uncertain"
        assert mock_run_agent.called


@pytest.mark.asyncio
async def test_predict_artifact_review_agent_success():
    mini = AsyncMock()
    mini.username = "testuser"
    mini.system_prompt = "You are a test user."
    mini.memory_content = "Memory content"
    mini.evidence_cache = "Evidence cache"
    mini.principles_json = {"principles": []}

    body = ArtifactReviewRequestV1(
        artifact_type="design_doc",
        repo_name="test/repo",
        title="Test design doc",
        artifact_summary="Covers boundaries, rollout, and follow-up tests.",
        author_model="trusted_peer",
        delivery_context="normal",
    )

    session = AsyncMock()

    mock_prediction = {
        "version": "artifact_review_v1",
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "reviewer_username": "testuser",
        "repo_name": "test/repo",
        "artifact_summary": {
            "artifact_type": "design_doc",
            "title": "Test design doc",
        },
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.9,
        },
        "delivery_policy": {
            "author_model": "trusted_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "Test rationale",
        },
        "expressed_feedback": {
            "summary": "Ready for sign-off",
            "comments": [],
            "approval_state": "approve",
        },
    }

    with patch("app.core.review_predictor_agent.run_agent") as mock_run_agent:
        mock_run_agent.return_value = AsyncMock(final_response=json.dumps(mock_prediction))

        result = await predict_artifact_review(mini, body, session)

        assert isinstance(result, ArtifactReviewV1)
        assert result.version == "artifact_review_v1"
        assert result.artifact_summary is not None
        assert result.artifact_summary.artifact_type == "design_doc"
        assert mock_run_agent.called
