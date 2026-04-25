from __future__ import annotations

from typing import Any
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.review_prediction import (
    build_artifact_review_v1,
    build_review_prediction_v1,
    load_same_repo_precedent,
    _derive_delivery_policy,
    _build_expressed_feedback,
)
from app.models.schemas import (
    ArtifactReviewRequestV1,
    ReviewPredictionPrivateAssessmentV1,
    ReviewPredictionRequestV1,
    ReviewPredictionSignalV1,
    ReviewRelationshipContextV1,
)


def _signal(
    key: str,
    summary: str,
    rationale: str,
    confidence: float,
) -> ReviewPredictionSignalV1:
    return ReviewPredictionSignalV1(
        key=key,
        summary=summary,
        rationale=rationale,
        confidence=confidence,
    )


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


def _decision_framework_payload() -> dict[str, Any]:
    return {
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "source": "principles_motivations_normalizer",
            "frameworks": [
                {
                    "framework_id": "fw-tests",
                    "condition": "request changes lack tests",
                    "priority": "high",
                    "tradeoff": "coverage vs speed",
                    "escalation_threshold": "high",
                    "counterexamples": [],
                    "temporal_span": {
                        "first_seen_at": "2026-01-01T00:00:00Z",
                        "last_reinforced_at": "2026-04-01T00:00:00Z",
                        "source_dates": ["2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"],
                    },
                    "evidence_ids": ["ev-framework-tests-1"],
                    "evidence_provenance": [
                        {
                            "id": "prov-tests-1",
                            "source_type": "review",
                            "item_type": "comment",
                        }
                    ],
                    "counter_evidence_ids": [],
                    "confidence": 0.91,
                    "specificity_level": "global",
                    "value_ids": ["quality", "reliability"],
                    "motivation_ids": ["craftsmanship"],
                    "decision_order": ["if missing tests", "ask for explicit coverage"],
                    "approval_policy": "block",
                    "revision": 3,
                },
                {
                    "framework_id": "fw-rollout",
                    "name": "Rollback check",
                    "condition": "changes include migration or async workers",
                    "priority": "medium",
                    "tradeoff": "safety vs velocity",
                    "escalation_threshold": "medium",
                    "counterexamples": [],
                    "evidence_ids": ["ev-framework-rollout-1"],
                    "evidence_provenance": [],
                    "counter_evidence_ids": [],
                    "confidence": 0.88,
                    "specificity_level": "scope_local",
                    "value_ids": ["resilience"],
                    "motivation_ids": ["quality"],
                    "decision_order": ["if migration risk", "request rollback plan"],
                    "revision": 2,
                },
            ],
        }
    }


def _conflicting_framework_payload() -> dict[str, Any]:
    return {
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "source": "principles_motivations_normalizer",
            "frameworks": [
                {
                    "framework_id": "fw-architecture-correctness",
                    "name": "Architecture correctness",
                    "condition": "architectural API boundary changes need durable correctness",
                    "priority": "critical",
                    "tradeoff": "architecture correctness vs shipping speed",
                    "escalation_threshold": "high",
                    "counterexamples": [],
                    "evidence_ids": ["ev-arch-1"],
                    "evidence_provenance": [
                        {
                            "id": "prov-arch-1",
                            "source_type": "review",
                            "item_type": "comment",
                        }
                    ],
                    "counter_evidence_ids": [],
                    "confidence": 0.94,
                    "specificity_level": "contextual",
                    "value_ids": ["durable-value"],
                    "motivation_ids": ["craftsmanship"],
                    "decision_order": ["if architectural boundary shifts", "prioritize correctness"],
                    "revision": 4,
                },
                {
                    "framework_id": "fw-shipping-speed",
                    "name": "Shipping speed",
                    "condition": "hotfix patch incident restore service with shipping speed",
                    "priority": "high",
                    "tradeoff": "shipping speed vs architecture polish",
                    "escalation_threshold": "medium",
                    "counterexamples": [],
                    "evidence_ids": ["ev-ship-1"],
                    "evidence_provenance": [
                        {
                            "id": "prov-ship-1",
                            "source_type": "review",
                            "item_type": "comment",
                        }
                    ],
                    "counter_evidence_ids": [],
                    "confidence": 0.86,
                    "specificity_level": "case_pattern",
                    "value_ids": ["shipping"],
                    "motivation_ids": ["pragmatism"],
                    "decision_order": ["if hotfix pressure", "keep scope shippable"],
                    "revision": 2,
                },
            ],
        }
    }


def _decision_framework_temporal_balance_payload() -> dict[str, Any]:
    return {
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "source": "principles_motivations_normalizer",
            "frameworks": [
                {
                    "framework_id": "fw-legacy-core-review",
                    "name": "Global review posture",
                    "condition": "Keep pull requests small and require comprehensive tests for behavior changes.",
                    "priority": "critical",
                    "tradeoff": "depth vs velocity",
                    "escalation_threshold": "high",
                    "counterexamples": [],
                    "temporal_span": {
                        "first_seen_at": "2023-02-01T00:00:00Z",
                        "last_reinforced_at": "2026-01-01T00:00:00Z",
                        "source_dates": [
                            "2023-02-01T00:00:00Z",
                            "2026-01-01T00:00:00Z",
                        ],
                    },
                    "evidence_ids": ["ev-framework-legacy-1"],
                    "evidence_provenance": [
                        {
                            "id": "prov-legacy-1",
                            "source_type": "review",
                            "item_type": "comment",
                        }
                    ],
                    "counter_evidence_ids": [],
                    "confidence": 0.9,
                    "specificity_level": "global",
                    "value_ids": ["quality", "maintainability"],
                    "motivation_ids": ["quality"],
                    "decision_order": ["if scope is global", "prioritize long-term consistency"],
                    "approval_policy": "block",
                    "revision": 8,
                },
                {
                    "framework_id": "fw-local-payments-webhook",
                    "name": "Payments webhook trial-first updates",
                    "condition": "backend/services/payments/webhooks changes should optimize for short-term delivery",
                    "priority": "high",
                    "tradeoff": "speed vs procedural consistency",
                    "escalation_threshold": "medium",
                    "counterexamples": [],
                    "evidence_ids": ["ev-framework-payments-webhook-1"],
                    "evidence_provenance": [],
                    "counter_evidence_ids": [],
                    "confidence": 0.82,
                    "specificity_level": "scope_local",
                    "value_ids": ["velocity"],
                    "motivation_ids": ["pragmatism"],
                    "decision_order": [
                        "if in payments service",
                        "accept delivery cadence adjustments",
                    ],
                    "approval_policy": "note",
                    "revision": 1,
                },
                {
                    "framework_id": "fw-local-payments-worker",
                    "name": "Payments worker refactor posture",
                    "condition": "backend/services/payments should prefer fewer ceremony changes",
                    "priority": "medium",
                    "tradeoff": "simplicity vs formality",
                    "escalation_threshold": "medium",
                    "counterexamples": [],
                    "evidence_ids": ["ev-framework-payments-worker-1"],
                    "evidence_provenance": [],
                    "counter_evidence_ids": [],
                    "confidence": 0.77,
                    "specificity_level": "scope_local",
                    "value_ids": ["velocity"],
                    "motivation_ids": ["pragmatism"],
                    "decision_order": ["if worker touched", "avoid process-heavy change"],
                    "approval_policy": "note",
                    "revision": 1,
                },
                {
                    "framework_id": "fw-local-payments-batch",
                    "name": "Payments batch behavior",
                    "condition": "payments batch handler should focus on throughput in this repo",
                    "priority": "medium",
                    "tradeoff": "throughput vs strict consistency",
                    "escalation_threshold": "medium",
                    "counterexamples": [],
                    "evidence_ids": ["ev-framework-payments-batch-1"],
                    "evidence_provenance": [],
                    "counter_evidence_ids": [],
                    "confidence": 0.74,
                    "specificity_level": "scope_local",
                    "value_ids": ["throughput"],
                    "motivation_ids": ["pragmatism"],
                    "decision_order": ["if batch job touched", "lean to immediate delivery"],
                    "approval_policy": "note",
                    "revision": 1,
                },
                {
                    "framework_id": "fw-local-payments-latency",
                    "name": "Payments latency preference",
                    "condition": "when adjusting payments latency, prefer quick observability signals",
                    "priority": "low",
                    "tradeoff": "latency vs validation",
                    "escalation_threshold": "medium",
                    "counterexamples": [],
                    "evidence_ids": ["ev-framework-payments-latency-1"],
                    "evidence_provenance": [],
                    "counter_evidence_ids": [],
                    "confidence": 0.68,
                    "specificity_level": "scope_local",
                    "value_ids": ["throughput"],
                    "motivation_ids": ["pragmatism"],
                    "decision_order": ["if latency touched", "ship fast and iterate"],
                    "approval_policy": "note",
                    "revision": 1,
                },
                {
                    "framework_id": "fw-local-payments-docs",
                    "name": "Payments docs-first preference",
                    "condition": "payments work should avoid extra design docs and document in code comments",
                    "priority": "low",
                    "tradeoff": "docs vs direct shipping",
                    "escalation_threshold": "medium",
                    "counterexamples": [],
                    "evidence_ids": ["ev-framework-payments-docs-1"],
                    "evidence_provenance": [],
                    "counter_evidence_ids": [],
                    "confidence": 0.64,
                    "specificity_level": "scope_local",
                    "value_ids": ["velocity"],
                    "motivation_ids": ["pragmatism"],
                    "decision_order": ["if docs are skipped", "prioritize implementation speed"],
                    "approval_policy": "note",
                    "revision": 1,
                },
            ],
        }
    }


def test_review_prediction_request_requires_some_change_input():
    with pytest.raises(ValidationError):
        ReviewPredictionRequestV1()


def test_review_prediction_request_accepts_artifact_summary_without_diff():
    body = ArtifactReviewRequestV1(
        artifact_type="design_doc",
        title="Design doc for retry isolation",
        artifact_summary="Proposes splitting queue retry policy from delivery concerns.",
    )

    assert body.artifact_type == "design_doc"


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
    assert prediction.private_expressed_deltas
    assert any(
        delta.issue_key == "auth-boundary"
        and delta.private_bucket == "blocking"
        and delta.expressed_disposition == "expressed"
        for delta in prediction.private_expressed_deltas
    )


def test_build_review_prediction_includes_framework_signals_from_decision_frameworks():
    mini = _mini(principles_json=_decision_framework_payload())
    body = ReviewPredictionRequestV1(
        title="Add tests and rollback plan for auth retry migration",
        description="This change adds queue retry tests and explicit rollback coverage.",
        changed_files=["backend/app/retry.py", "backend/app/auth.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.framework_signals
    signal_ids = {signal.framework_id for signal in prediction.framework_signals}
    assert {"fw-tests", "fw-rollout"}.intersection(signal_ids)
    framework_by_id = {signal.framework_id: signal for signal in prediction.framework_signals}
    signal = framework_by_id["fw-tests"]
    assert signal.name
    assert "Decision framework" not in signal.name
    assert signal.summary
    assert signal.reason
    assert signal.confidence >= 0.9
    assert signal.revision_count == 3
    assert signal.revision == 3
    assert signal.evidence_ids == ["ev-framework-tests-1"]
    assert any(item.id == "prov-tests-1" for item in signal.evidence_provenance)


def test_framework_conflict_resolution_favors_shipping_speed_for_hotfix_context():
    mini = _mini(principles_json=_conflicting_framework_payload())
    body = ReviewPredictionRequestV1(
        title="Hotfix patch for architectural API boundary regression",
        description="Restore service quickly while noting the durable boundary cleanup follow-up.",
        changed_files=["backend/app/api/auth.py"],
        author_model="trusted_peer",
        delivery_context="hotfix",
    )

    prediction = build_review_prediction_v1(mini, body)

    resolution = prediction.framework_conflict_resolution
    assert resolution is not None
    assert resolution.winning_framework_ids == ["fw-shipping-speed"]
    assert resolution.deferred_framework_ids == ["fw-architecture-correctness"]
    assert resolution.suppressed_framework_ids == []
    assert "hotfix pressure" in resolution.tradeoff_rationale
    assert resolution.confidence > 0.6
    assert set(resolution.evidence_ids) == {"ev-ship-1", "ev-arch-1"}
    assert set(resolution.provenance_ids) == {"prov-ship-1", "prov-arch-1"}


def test_framework_conflict_resolution_favors_architecture_for_architectural_change():
    mini = _mini(principles_json=_conflicting_framework_payload())
    body = ReviewPredictionRequestV1(
        title="Architectural API boundary migration with shipping speed pressure",
        description="Refactors the durable auth contract and asks whether to cut scope for speed.",
        changed_files=["backend/app/api/contract.py", "backend/app/migrations/auth_boundary.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    resolution = prediction.framework_conflict_resolution
    assert resolution is not None
    assert resolution.winning_framework_ids == ["fw-architecture-correctness"]
    assert resolution.deferred_framework_ids == ["fw-shipping-speed"]
    assert resolution.suppressed_framework_ids == []
    assert "architectural-change context" in resolution.tradeoff_rationale
    decisions = {item.framework_id: item.disposition for item in resolution.decisions}
    assert decisions == {
        "fw-architecture-correctness": "win",
        "fw-shipping-speed": "defer",
    }


def test_temporal_balance_preserves_stable_framework_with_local_scoped_preference():
    mini = _mini(principles_json=_decision_framework_temporal_balance_payload())
    body = ReviewPredictionRequestV1(
        title="Update payments webhook retry handling in payments service",
        description="Touch a small webhook handler and tune retry timing for release speed.",
        changed_files=["backend/services/payments/webhooks.py"],
        repo_name="acme/payments-service",
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)
    assert prediction.framework_temporal_balance is not None
    assert prediction.framework_temporal_balance.stable_frameworks_preserved is True
    assert prediction.framework_temporal_balance.visible_stable_framework_ids == [
        "fw-legacy-core-review"
    ]
    assert "fw-local-payments-webhook" in prediction.framework_temporal_balance.visible_project_preference_ids
    assert prediction.framework_temporal_balance.visible_project_preference_ids
    assert len(prediction.framework_temporal_balance.visible_project_preference_ids) >= 1
    assert prediction.framework_temporal_balance.rationale.startswith(
        "Scoped signals lead"
    )
    assert len(prediction.framework_signals) == 5

    visible_ids = [signal.framework_id for signal in prediction.framework_signals]
    assert visible_ids[0] == "fw-local-payments-webhook"
    assert "fw-legacy-core-review" in visible_ids
    assert prediction.framework_signals[0].framework_id != "fw-legacy-core-review"


def test_design_doc_artifact_review_uses_generic_signoff_language():
    mini = _mini()
    body = ArtifactReviewRequestV1(
        artifact_type="design_doc",
        repo_name="acme/api",
        title="Design doc for auth token rotation",
        description="Outlines auth boundaries, queue retry handling, and rollout notes.",
        artifact_summary="Proposes rotation steps, rollback posture, and follow-up validation work.",
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_artifact_review_v1(mini, body)

    assert prediction.version == "artifact_review_v1"
    assert prediction.artifact_summary is not None
    assert prediction.artifact_summary.artifact_type == "design_doc"
    assert prediction.artifact_summary.title == "Design doc for auth token rotation"
    assert "merge" not in prediction.expressed_feedback.summary.lower()
    assert "sign-off" in prediction.expressed_feedback.summary.lower()


def test_issue_plan_artifact_review_supports_artifact_summary_input():
    mini = _mini()
    body = ArtifactReviewRequestV1(
        artifact_type="issue_plan",
        title="Issue plan for retry hardening",
        artifact_summary="Plan covers queue retries, logging, rollback, and test follow-through.",
        author_model="trusted_peer",
        delivery_context="normal",
    )

    prediction = build_artifact_review_v1(mini, body)

    assert prediction.version == "artifact_review_v1"
    assert prediction.artifact_summary is not None
    assert prediction.artifact_summary.artifact_type == "issue_plan"
    assert prediction.private_assessment.confidence >= 0.4
    assert prediction.expressed_feedback.summary


def test_artifact_review_request_rejects_pull_request_artifacts():
    with pytest.raises(ValidationError):
        ArtifactReviewRequestV1(
            artifact_type="pull_request",
            title="PR-shaped artifact on wrong endpoint",
        )


def test_review_prediction_request_rejects_non_pr_artifacts():
    with pytest.raises(ValidationError):
        ReviewPredictionRequestV1(
            artifact_type="design_doc",
            title="Design doc on PR endpoint",
        )


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
    assert "trusted-peer context narrows feedback" in prediction.delivery_policy.rationale
    assert "noisy churn" in prediction.delivery_policy.rationale


def test_relationship_context_from_trusted_peer_is_first_class_and_narrows_feedback():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        title="Refactor retry bookkeeping",
        description="Moves retry state handling into one helper with the same runtime behavior.",
        changed_files=["backend/app/core/rate_limit.py"],
        author_model="trusted_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    context = prediction.relationship_context
    assert prediction.delivery_policy.relationship_context == context
    assert context.reviewer_author_relationship == "trusted_peer"
    assert context.trust_level == "high"
    assert context.channel == "unknown"
    assert "channel" in context.unknown_fields
    assert "non_blocking" in prediction.delivery_policy.defer
    assert "trusted-peer context steers toward suppressing low-value nits" in (
        prediction.delivery_policy.rationale
    )


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
    assert "junior/mentorship" in prediction.delivery_policy.rationale


def test_relationship_context_supports_explicit_junior_mentorship_context():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor auth token handling",
        description="Touches JWT parsing, queue retries, and schema writes with no test plan.",
        diff_summary="Updates permission checks and async worker behavior.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        relationship_context=ReviewRelationshipContextV1(
            reviewer_author_relationship="junior_mentorship",
            mentorship_context="reviewer_mentors_author",
            channel="team_private",
            team_alignment="same_team",
            audience_sensitivity="high",
            data_confidence="explicit",
            rationale="Reviewer is acting as mentor for this same-team author.",
        ),
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.delivery_policy.author_model == "unknown"
    assert prediction.relationship_context.reviewer_author_relationship == "junior_mentorship"
    assert prediction.delivery_policy.teaching_mode is True
    assert prediction.delivery_policy.shield_author_from_noise is True
    assert "junior/mentorship relationship shifts toward coaching" in (
        prediction.delivery_policy.rationale
    )
    assert "coaching-oriented" in prediction.expressed_feedback.summary


def test_evidence_empty_mini_gates_instead_of_generic_keyword_prediction():
    mini = _mini(
        behavioral_context_json=None,
        motivations_json=None,
        values_json=None,
        memory_content=None,
        evidence_cache=None,
        principles_json=None,
    )
    body = ReviewPredictionRequestV1(
        title="Refactor auth token handling for async worker",
        description="Touches JWT parsing, queue retries, and database persistence.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.prediction_available is False
    assert prediction.mode == "gated"
    assert prediction.private_assessment.blocking_issues == []
    assert prediction.expressed_feedback.comments == []
    assert prediction.private_expressed_deltas == []
    assert "insufficient review-fidelity evidence" in prediction.unavailable_reason


def test_cross_team_public_context_routes_private_assessment_to_narrow_expression():
    mini = _mini()
    shared_assessment = ReviewPredictionPrivateAssessmentV1(
        blocking_issues=[],
        non_blocking_issues=[
            _signal(
                "clarity-pass",
                "Could tighten local naming or boundaries.",
                "Cleaner naming usually helps future changes.",
                0.9,
            )
        ],
        open_questions=[
            _signal(
                "rollout-safety",
                "Would likely ask about rollout safety.",
                "Cross-team changes need explicit rollout posture.",
                0.9,
            )
        ],
        positive_signals=[],
        confidence=0.86,
    )
    body = ReviewPredictionRequestV1(
        title="Platform retry update",
        description="Updates platform retry behavior and rollout sequencing.",
        changed_files=["backend/app/platform/retry.py"],
        relationship_context=ReviewRelationshipContextV1(
            reviewer_author_relationship="cross_team_partner",
            channel="public_review",
            team_alignment="cross_team",
            repo_ownership="author_owned",
            audience_sensitivity="high",
            data_confidence="explicit",
            rationale="Public review on an author-owned repo with cross-team audience.",
        ),
    )

    policy = _derive_delivery_policy(mini, body, evidence_pool=[], same_repo_precedent=None)
    expressed = _build_expressed_feedback(shared_assessment, policy, body)

    assert policy.relationship_context.reviewer_author_relationship == "cross_team_partner"
    assert policy.shield_author_from_noise is True
    assert "non_blocking" in policy.defer
    assert "public or cross-team audience sensitivity narrows expressed feedback" in policy.rationale
    assert "cross-team context keeps expressed feedback factual and question-oriented" in policy.rationale
    assert [comment.type for comment in expressed.comments] == ["question"]
    assert expressed.comments[0].issue_key == "rollout-safety"


def test_cross_team_public_prediction_records_suppressed_private_feedback_delta():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        title="Refactor local naming boundaries",
        description="Moves helper names and boundary wording in a cross-team package.",
        changed_files=["backend/app/platform/names.py"],
        relationship_context=ReviewRelationshipContextV1(
            reviewer_author_relationship="cross_team_partner",
            channel="public_review",
            team_alignment="cross_team",
            repo_ownership="author_owned",
            audience_sensitivity="high",
            data_confidence="explicit",
            rationale="Public review on an author-owned repo with cross-team audience.",
        ),
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.private_assessment.non_blocking_issues
    clarity_delta = next(
        delta for delta in prediction.private_expressed_deltas if delta.issue_key == "clarity-pass"
    )
    assert clarity_delta.private_bucket == "non_blocking"
    assert clarity_delta.expressed_disposition == "deferred"
    assert clarity_delta.specificity in {"framework_specific", "evidence_backed"}
    assert "deferred" in clarity_delta.rationale
    assert all(comment.issue_key != "clarity-pass" for comment in prediction.expressed_feedback.comments)


def test_unknown_relationship_context_is_explicit_and_neutral():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        title="Add docs for retry helper",
        description="Adds README notes for retry helper usage.",
        changed_files=["docs/retry.md"],
        author_model="unknown",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    context = prediction.relationship_context
    assert context.reviewer_author_relationship == "unknown"
    assert context.trust_level == "unknown"
    assert context.channel == "unknown"
    assert context.team_alignment == "unknown"
    assert context.repo_ownership == "unknown"
    assert context.audience_sensitivity == "unknown"
    assert set(context.unknown_fields) >= {
        "reviewer_author_relationship",
        "trust_level",
        "channel",
        "team_alignment",
        "repo_ownership",
        "audience_sensitivity",
    }
    assert prediction.delivery_policy.teaching_mode is False
    assert "relationship/team context unknown" in prediction.delivery_policy.rationale


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
    assert "center the review on the main merge-risk issues" in prediction.expressed_feedback.summary
    assert "pretty direct" in prediction.expressed_feedback.summary
    assert len(blocker_comments) == 2
    assert len(question_comments) == 1
    assert "state this pretty directly" in blocker_comments[0].rationale.lower()


def test_delivery_policy_makes_signal_routing_explicit():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        title="Hotfix: recover from auth cache fault",
        description="Emergency fix for token cache timeout handling during incident recovery.",
        changed_files=["backend/app/auth.py", "backend/app/cache.py"],
        author_model="trusted_peer",
        delivery_context="hotfix",
    )

    prediction = build_review_prediction_v1(mini, body)
    policy = prediction.delivery_policy

    assert set(policy.say) == {"blocking", "non_blocking", "questions", "positive"}
    assert "non_blocking" in policy.defer
    assert "positive" in policy.defer
    assert "questions" in policy.defer
    assert 0.7 <= policy.risk_threshold <= 1.0


def test_same_private_assessment_routed_differently_for_author_and_context():
    mini = _mini(
        values_json={
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 7.2},
                {"name": "Directness", "description": "", "intensity": 6.7},
                {"name": "Pragmatism", "description": "", "intensity": 5.9},
            ]
        }
    )
    shared_assessment = ReviewPredictionPrivateAssessmentV1(
        blocking_issues=[
            _signal(
                "auth-boundary",
                "Would likely scrutinize auth and permission boundaries.",
                "Security-sensitive surfaces require explicit boundary checks.",
                0.88,
            )
        ],
        non_blocking_issues=[
            _signal(
                "clarity-pass",
                "Could tighten naming or boundaries.",
                "Cleaner naming usually helps future changes.",
                0.72,
            )
        ],
        open_questions=[
            _signal(
                "rollout-safety",
                "Would likely ask about rollout safety.",
                "Even low-touch fixes should have a recovery path.",
                0.74,
            )
        ],
        positive_signals=[
            _signal(
                "docs-present",
                "Documentation already called out.",
                "Good docs context lowers ambiguity.",
                0.82,
            )
        ],
        confidence=0.88,
    )
    senior_body = ReviewPredictionRequestV1(
        title="Auth caching change",
        description="Adds auth cache handling updates with clearer path checks.",
        changed_files=["backend/app/auth.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )
    exploratory_body = ReviewPredictionRequestV1(
        title="Auth caching experiment",
        description="Draft auth caching experiment before hardening it.",
        changed_files=["backend/app/auth.py"],
        author_model="trusted_peer",
        delivery_context="exploratory",
    )

    senior_policy = _derive_delivery_policy(mini, senior_body, evidence_pool=[], same_repo_precedent=None)
    exploratory_policy = _derive_delivery_policy(
        mini,
        exploratory_body,
        evidence_pool=[],
        same_repo_precedent=None,
    )

    senior_expressed = _build_expressed_feedback(shared_assessment, senior_policy, senior_body)
    exploratory_expressed = _build_expressed_feedback(shared_assessment, exploratory_policy, exploratory_body)

    assert senior_expressed.approval_state == "request_changes"
    assert exploratory_expressed.approval_state == "request_changes"
    assert [comment.type for comment in senior_expressed.comments] != [
        comment.type for comment in exploratory_expressed.comments
    ]
    assert "non_blocking" in senior_policy.say
    assert "non_blocking" in exploratory_policy.say
    assert (senior_policy.defer != exploratory_policy.defer) or (senior_policy.suppress != exploratory_policy.suppress)


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
    assert auth_signal.specificity == "framework_specific"


def test_same_repo_precedent_escalates_test_gap_and_strictness():
    mini = _mini(
        behavioral_context_json=None,
        motivations_json=None,
        memory_content="review: asks about retry timeout behavior before risky worker changes",
        evidence_cache=None,
        values_json={
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 6.1},
                {"name": "Directness", "description": "", "intensity": 6.2},
                {"name": "Pragmatism", "description": "", "intensity": 4.2},
            ]
        }
    )
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor queue retry timeout handling",
        description="Touches async worker retries and timeout behavior with no explicit validation plan.",
        changed_files=["backend/app/workers/token_queue.py"],
        author_model="unknown",
        delivery_context="normal",
    )

    baseline = build_review_prediction_v1(mini, body)
    with_precedent = build_review_prediction_v1(
        mini,
        body,
        same_repo_precedent={
            "repo_name": "acme/api",
            "cycle_count": 3,
            "focus_counts": {"tests": 3, "rollout": 1},
            "focuses": ["tests", "rollout"],
            "approval_counts": {
                "approve": 0,
                "comment": 1,
                "request_changes": 2,
                "uncertain": 0,
            },
            "detail": "same-repo precedent for acme/api: 3 recent review cycles; recurring focus on tests, rollout; outcomes skewed request_changes",
        },
    )

    assert "test-coverage" in {item.key for item in baseline.private_assessment.open_questions}
    assert "test-coverage" not in {item.key for item in baseline.private_assessment.blocking_issues}
    assert with_precedent.delivery_policy.strictness == "medium"
    assert "same-repo review precedent reinforces focus on rollout, tests" in with_precedent.delivery_policy.rationale
    precedent_test_gap = next(
        item for item in with_precedent.private_assessment.blocking_issues if item.key == "test-coverage"
    )
    assert "same-repo review cycles repeatedly centered tests before merge" in precedent_test_gap.rationale


@pytest.mark.asyncio
async def test_load_same_repo_precedent_filters_to_matching_repo():
    session = AsyncMock()
    cycles = [
        SimpleNamespace(
            metadata_json={"repo_full_name": "acme/api"},
            predicted_state={
                "private_assessment": {"blocking_issues": [{"id": "missing-tests"}]},
                "expressed_feedback": {
                    "summary": "Please add tests before merge.",
                    "approval_state": "request_changes",
                    "comments": [{"body": "Need tests before merge."}],
                },
            },
            human_review_outcome=None,
        ),
        SimpleNamespace(
            metadata_json={"repo_full_name": "acme/api"},
            predicted_state={
                "private_assessment": {"blocking_issues": []},
                "expressed_feedback": {
                    "summary": "What is the rollback plan?",
                    "approval_state": "comment",
                    "comments": [{"body": "Please include rollback posture."}],
                },
            },
            human_review_outcome=None,
        ),
        SimpleNamespace(
            metadata_json={"repo_full_name": "other/repo"},
            predicted_state={
                "private_assessment": {"blocking_issues": []},
                "expressed_feedback": {
                    "summary": "Unrelated repo history",
                    "approval_state": "approve",
                    "comments": [],
                },
            },
            human_review_outcome=None,
        ),
    ]
    session.execute.return_value = SimpleNamespace(scalars=lambda: cycles)

    precedent = await load_same_repo_precedent(session, "mini-123", "acme/api")

    assert precedent is not None
    assert precedent["cycle_count"] == 2
    assert precedent["focus_counts"]["tests"] == 1
    assert precedent["focus_counts"]["rollout"] == 1
    assert "acme/api" in precedent["detail"]
