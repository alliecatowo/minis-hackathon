from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.review_prediction import build_review_prediction_v1
from app.models.schemas import ReviewPredictionRequestV1


def _mini(**overrides) -> SimpleNamespace:
    data = {
        "username": "alliecatowo",
        "behavioral_context_json": {
            "summary": "Most direct in code review.",
            "contexts": [
                {
                    "context": "code_review",
                    "summary": "Pushes for precision, tests, and explicit boundaries.",
                    "behaviors": [
                        "flags missing coverage",
                        "asks for narrower interfaces",
                        "prefers concrete rollout plans",
                    ],
                    "communication_style": "direct but specific",
                    "decision_style": "looks for breakage before style",
                    "motivators": ["clarity", "quality"],
                    "stressors": ["hand-wavy changes"],
                    "evidence": ["Consistently asks for tests in review threads."],
                }
            ],
        },
        "motivations_json": {
            "motivations": [
                {
                    "value": "craftsmanship",
                    "category": "terminal_value",
                    "evidence_ids": ["ev-1"],
                    "confidence": 0.87,
                }
            ],
            "motivation_chains": [],
            "summary": "Values craftsmanship and clear system boundaries.",
        },
        "values_json": {
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 8.8},
                {"name": "Directness", "description": "", "intensity": 8.1},
                {"name": "Pragmatism", "description": "", "intensity": 4.2},
            ]
        },
        "memory_content": (
            "In reviews they push hard on tests, rollout safety, and explicit ownership seams.\n"
            "They prefer concrete migration plans over hand-wavy compatibility claims."
        ),
        "evidence_cache": (
            "review: please add tests before merge\n"
            "review: what is the rollback plan if this migration misbehaves?\n"
            "review: auth boundary feels too implicit here"
        ),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_review_prediction_request_requires_some_change_input():
    with pytest.raises(ValidationError):
        ReviewPredictionRequestV1()


def test_review_prediction_request_accepts_artifact_summary_without_diff():
    body = ReviewPredictionRequestV1(
        artifact_type="design_doc",
        title="Design doc for retry isolation",
        artifact_summary="Proposes splitting queue retry policy from delivery concerns.",
    )

    assert body.artifact_type == "design_doc"
    assert body.artifact_summary == "Proposes splitting queue retry policy from delivery concerns."


def test_build_review_prediction_returns_structured_request_changes():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor auth token handling for async worker",
        description="Touches JWT parsing, queue retries, and database persistence.",
        diff_summary="Updates permission checks and schema writes with no validation notes.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.version == "review_prediction_v1"
    assert prediction.repo_name == "acme/api"
    assert prediction.delivery_policy.strictness == "high"
    assert prediction.delivery_policy.teaching_mode is False
    assert prediction.expressed_feedback.approval_state == "request_changes"
    blocker_keys = {item.key for item in prediction.private_assessment.blocking_issues}
    assert "auth-boundary" in blocker_keys
    assert "runtime-behavior" in blocker_keys
    assert "test-coverage" in blocker_keys
    assert prediction.private_assessment.confidence >= 0.5
    assert prediction.expressed_feedback.comments


def test_design_doc_artifact_review_uses_generic_signoff_language():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        artifact_type="design_doc",
        repo_name="acme/api",
        title="Design doc for auth token rotation",
        description="Covers auth boundaries, rollout sequencing, and compatibility expectations.",
        artifact_summary="Proposes rotation steps, rollback posture, and follow-up validation work.",
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.artifact_summary is not None
    assert prediction.artifact_summary.artifact_type == "design_doc"
    assert prediction.artifact_summary.title == "Design doc for auth token rotation"
    assert "merge" not in prediction.expressed_feedback.summary.lower()
    assert "sign-off" in prediction.expressed_feedback.summary.lower()


def test_issue_plan_artifact_review_supports_artifact_summary_input():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        artifact_type="issue_plan",
        title="Issue plan for retry hardening",
        artifact_summary="Plan covers queue retries, logging, rollback, and test follow-through.",
        author_model="trusted_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.artifact_summary is not None
    assert prediction.artifact_summary.artifact_type == "issue_plan"
    assert prediction.private_assessment.confidence >= 0.4
    assert prediction.expressed_feedback.summary


def test_hotfix_policy_shields_noise_for_trusted_peer():
    mini = _mini(
        values_json={
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 7.4},
                {"name": "Directness", "description": "", "intensity": 6.5},
                {"name": "Pragmatism", "description": "", "intensity": 8.4},
            ]
        }
    )
    body = ReviewPredictionRequestV1(
        title="Hotfix cache timeout handling",
        description="Adjusts queue retry timing and logging for incident recovery.",
        changed_files=["backend/app/cache.py"],
        author_model="trusted_peer",
        delivery_context="incident",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.delivery_policy.shield_author_from_noise is True
    assert prediction.delivery_policy.strictness == "low"
    assert prediction.expressed_feedback.approval_state == "request_changes"
    comment_types = [comment.type for comment in prediction.expressed_feedback.comments]
    assert "note" not in comment_types


def test_positive_only_change_can_resolve_to_approve():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        title="Add tests and docs for migration safety",
        description="Adds pytest coverage, rollback notes, and README docs for the migration path.",
        changed_files=["backend/tests/test_migration_flow.py", "backend/README.md"],
        author_model="unknown",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.private_assessment.blocking_issues == []
    assert prediction.private_assessment.positive_signals
    assert prediction.expressed_feedback.approval_state == "approve"


def test_delivery_policy_infers_exploratory_context_and_teaching_mode():
    mini = _mini(
        behavioral_context_json={
            "summary": "Teaches through review when the work is early or still moving.",
            "contexts": [
                {
                    "context": "code_review",
                    "summary": "Uses review to coach on structure before polishing details.",
                    "behaviors": ["explains tradeoffs", "guides toward the next safe step"],
                    "communication_style": "direct but specific",
                    "decision_style": "teaching-first when the work is still exploratory",
                    "motivators": ["clarity", "shared understanding"],
                    "stressors": ["premature polish"],
                    "evidence": ["Often reframes draft work as a learning loop."],
                }
            ],
        }
    )
    body = ReviewPredictionRequestV1(
        title="WIP prototype for a new ingestion flow",
        description="Draft experiment to explore a possible queue shape before hardening it.",
        changed_files=["backend/app/ingestion/github.py"],
        author_model="unknown",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.delivery_policy.context == "exploratory"
    assert prediction.delivery_policy.teaching_mode is True
    assert prediction.delivery_policy.shield_author_from_noise is True
    assert "exploratory" in prediction.delivery_policy.rationale


def test_delivery_policy_uses_relationship_and_noise_signals_for_trusted_peer():
    mini = _mini(
        behavioral_context_json={
            "summary": "Narrows comments aggressively when the author is already moving fast.",
            "contexts": [
                {
                    "context": "code_review",
                    "summary": "Leaves only high-signal review comments and avoids noisy churn.",
                    "behaviors": ["skips nits in favor of risk", "cuts back on review noise"],
                    "communication_style": "direct",
                    "decision_style": "focuses on merge risk over polish",
                    "motivators": ["throughput", "clarity"],
                    "stressors": ["noise", "bike-shedding"],
                    "evidence": ["Prefers to suppress low-value review churn for trusted collaborators."],
                }
            ],
        }
    )
    body = ReviewPredictionRequestV1(
        title="Refactor retry bookkeeping",
        description="Moves retry state handling into one helper with the same runtime behavior.",
        changed_files=["backend/app/core/rate_limit.py"],
        author_model="trusted_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.delivery_policy.context == "normal"
    assert prediction.delivery_policy.shield_author_from_noise is True
    assert prediction.delivery_policy.strictness == "medium"
    assert "trusted-peer relationship narrows feedback" in prediction.delivery_policy.rationale
    assert "noisy churn" in prediction.delivery_policy.rationale


def test_delivery_policy_caps_strictness_for_junior_peer():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor auth token handling",
        description="Touches JWT parsing, queue retries, and schema writes with no test plan.",
        diff_summary="Updates permission checks and async worker behavior.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        author_model="junior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.delivery_policy.strictness == "medium"
    assert prediction.delivery_policy.teaching_mode is True
    assert prediction.delivery_policy.shield_author_from_noise is True
    assert "junior-peer" in prediction.delivery_policy.rationale


def test_expressed_feedback_uses_teaching_mode_for_junior_peer_request_changes():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor auth token handling",
        description="Touches JWT parsing, queue retries, and schema writes with no test plan.",
        diff_summary="Updates permission checks and async worker behavior.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        author_model="junior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.expressed_feedback.approval_state == "request_changes"
    assert "coaching-oriented" in prediction.expressed_feedback.summary
    assert "Lower-value nits would likely stay unsaid." in prediction.expressed_feedback.summary
    assert [comment.type for comment in prediction.expressed_feedback.comments] == ["blocker", "question"]
    assert prediction.expressed_feedback.comments[1].disposition == "request_changes"
    assert (
        "guide the next revision step"
        in prediction.expressed_feedback.comments[1].rationale.lower()
    )


def test_expressed_feedback_gets_more_direct_for_high_strictness_senior_peer():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor auth token handling for async worker",
        description="Touches JWT parsing, queue retries, and database persistence.",
        diff_summary="Updates permission checks and schema writes with no validation notes.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    blocker_comments = [
        comment for comment in prediction.expressed_feedback.comments if comment.type == "blocker"
    ]
    question_comments = [
        comment for comment in prediction.expressed_feedback.comments if comment.type == "question"
    ]

    assert prediction.delivery_policy.strictness == "high"
    assert "center the review on the main sign-off risks" in prediction.expressed_feedback.summary
    assert "pretty direct" in prediction.expressed_feedback.summary
    assert len(blocker_comments) == 2
    assert len(question_comments) == 1
    assert "state this pretty directly" in blocker_comments[0].rationale.lower()


def test_recent_contradictory_snippet_does_not_dominate_stable_principles_evidence():
    mini = _mini(
        principles_json={
            "principles": [
                {
                    "trigger": "auth or permission boundaries change",
                    "action": "block until explicit boundary checks and tests are present",
                    "value": "security and correctness",
                    "intensity": 9.6,
                    "evidence": [
                        "PR #100 asks for explicit permission boundaries",
                        "PR #131 requests test coverage for auth checks",
                        "PR #188 blocks implicit token handling",
                    ],
                }
            ]
        },
        evidence_cache=(
            "latest hotfix note this week: skipped strict auth boundaries to move fast\n"
            "review: minor naming note"
        ),
    )
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor auth token handling for async worker",
        description="Touches JWT parsing, permission checks, and queue retries.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    auth_signal = next(
        issue for issue in prediction.private_assessment.blocking_issues if issue.key == "auth-boundary"
    )
    assert auth_signal.evidence
    assert auth_signal.evidence[0].source == "principles"
