"""Unit tests for the ReviewPredictionV1 envelope (ALLIE-461).

Validates:
- ReviewPredictionV1 round-trips through model_validate + model_dump
- framework_id and revision on ReviewPredictionSignalV1 propagate end-to-end
- model_dump(mode="json") produces a stable, JSON-serialisable dict
- Backward-compat: omitting framework_id/revision still validates
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ReviewPredictionFrameworkSignalV1,
    ReviewPredictionSignalV1,
    ReviewPredictionV1,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(
    *,
    key: str = "test-key",
    summary: str = "summary",
    rationale: str = "rationale",
    confidence: float = 0.8,
    framework_id: str | None = None,
    revision: int | None = None,
) -> dict:
    d: dict = {
        "key": key,
        "summary": summary,
        "rationale": rationale,
        "confidence": confidence,
    }
    if framework_id is not None:
        d["framework_id"] = framework_id
    if revision is not None:
        d["revision"] = revision
    return d


def _framework_signal(
    *,
    framework_id: str = "fw-framework",
    name: str = "Rule of thumb",
    summary: str = "Prefer clear boundaries.",
    reason: str = "Decision framework condition matches observed review signal.",
    confidence: float = 0.81,
    revision: int | None = 3,
    revision_count: int = 1,
    evidence_ids: list[str] | None = None,
    evidence_provenance: list[dict] | None = None,
    provenance_ids: list[str] | None = None,
) -> dict:
    return {
        "framework_id": framework_id,
        "name": name,
        "summary": summary,
        "reason": reason,
        "confidence": confidence,
        "revision": revision,
        "revision_count": revision_count,
        "evidence_ids": evidence_ids or ["ev-1"],
        "evidence_provenance": evidence_provenance
        or [{"id": "ev-1", "source_type": "review", "item_type": "comment"}],
        "provenance_ids": provenance_ids or ["ev-1"],
    }


def _minimal_envelope(**overrides) -> dict:
    base = {
        "version": "review_prediction_v1",
        "reviewer_username": "allie",
        "repo_name": "acme/repo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.75,
        },
        "delivery_policy": {
            "author_model": "trusted_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": False,
            "rationale": "Trusted colleague; direct feedback is appropriate.",
        },
        "expressed_feedback": {
            "summary": "LGTM with minor nits.",
            "comments": [],
            "approval_state": "approve",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ReviewPredictionSignalV1 — field-level tests
# ---------------------------------------------------------------------------


def test_signal_defaults_framework_fields_to_none():
    sig = ReviewPredictionSignalV1.model_validate(_signal())
    assert sig.framework_id is None
    assert sig.revision is None


def test_signal_accepts_framework_id_and_revision():
    sig = ReviewPredictionSignalV1.model_validate(
        _signal(framework_id="fw-tests", revision=3)
    )
    assert sig.framework_id == "fw-tests"
    assert sig.revision == 3


def test_signal_framework_id_only():
    sig = ReviewPredictionSignalV1.model_validate(
        _signal(framework_id="fw-security")
    )
    assert sig.framework_id == "fw-security"
    assert sig.revision is None


def test_signal_revision_only():
    sig = ReviewPredictionSignalV1.model_validate(_signal(revision=0))
    assert sig.framework_id is None
    assert sig.revision == 0


def test_signal_model_dump_includes_framework_fields():
    sig = ReviewPredictionSignalV1.model_validate(
        _signal(framework_id="fw-x", revision=2)
    )
    d = sig.model_dump(mode="json")
    assert d["framework_id"] == "fw-x"
    assert d["revision"] == 2


def test_signal_model_dump_none_fields_present():
    """model_dump always includes framework_id/revision even when None."""
    sig = ReviewPredictionSignalV1.model_validate(_signal())
    d = sig.model_dump(mode="json")
    assert "framework_id" in d
    assert "revision" in d
    assert d["framework_id"] is None
    assert d["revision"] is None


def test_signal_confidence_bounds():
    with pytest.raises(ValidationError):
        ReviewPredictionSignalV1.model_validate(_signal(confidence=1.5))
    with pytest.raises(ValidationError):
        ReviewPredictionSignalV1.model_validate(_signal(confidence=-0.1))


# ---------------------------------------------------------------------------
# ReviewPredictionV1 envelope — round-trip tests
# ---------------------------------------------------------------------------


def test_envelope_round_trip_minimal():
    envelope = ReviewPredictionV1.model_validate(_minimal_envelope())
    dumped = envelope.model_dump(mode="json")
    assert dumped["version"] == "review_prediction_v1"
    assert dumped["reviewer_username"] == "allie"
    assert dumped["repo_name"] == "acme/repo"
    assert dumped["prediction_available"] is True
    assert dumped["mode"] == "llm"
    assert dumped["unavailable_reason"] is None


def test_envelope_accepts_gated_prediction_without_signals():
    envelope = ReviewPredictionV1.model_validate(
        _minimal_envelope(
            prediction_available=False,
            mode="gated",
            unavailable_reason="REVIEW_PREDICTOR_LLM_ENABLED is disabled",
        )
    )

    assert envelope.prediction_available is False
    assert envelope.mode == "gated"
    assert envelope.unavailable_reason == "REVIEW_PREDICTOR_LLM_ENABLED is disabled"


def test_envelope_default_framework_signals_is_empty_list():
    envelope = ReviewPredictionV1.model_validate(_minimal_envelope())
    assert envelope.framework_signals == []
    dumped = envelope.model_dump(mode="json")
    assert dumped["framework_signals"] == []
    assert "framework_temporal_balance" in dumped
    assert dumped["framework_temporal_balance"] is None


def test_envelope_round_trip_is_json_serialisable():
    envelope = ReviewPredictionV1.model_validate(_minimal_envelope())
    dumped = envelope.model_dump(mode="json")
    # Should not raise
    serialised = json.dumps(dumped)
    rehydrated = json.loads(serialised)
    assert rehydrated["version"] == "review_prediction_v1"


def test_envelope_version_literal():
    """version field is a discriminator literal; wrong value must fail."""
    bad = _minimal_envelope(version="wrong_version_v1")
    with pytest.raises(ValidationError):
        ReviewPredictionV1.model_validate(bad)


def test_envelope_with_signals_carrying_framework_attribution():
    """framework_id/revision on signals survive the full envelope round-trip."""
    envelope_dict = _minimal_envelope()
    envelope_dict["private_assessment"]["blocking_issues"] = [
        _signal(key="missing-tests", framework_id="fw-tdd", revision=2, confidence=0.9)
    ]
    envelope_dict["private_assessment"]["positive_signals"] = [
        _signal(key="has-rollback", confidence=0.7)  # no framework attribution
    ]

    envelope = ReviewPredictionV1.model_validate(envelope_dict)

    blocking = envelope.private_assessment.blocking_issues
    assert len(blocking) == 1
    assert blocking[0].framework_id == "fw-tdd"
    assert blocking[0].revision == 2

    positive = envelope.private_assessment.positive_signals
    assert len(positive) == 1
    assert positive[0].framework_id is None
    assert positive[0].revision is None


def test_envelope_model_dump_signals_include_framework_fields():
    envelope_dict = _minimal_envelope()
    envelope_dict["private_assessment"]["non_blocking_issues"] = [
        _signal(key="style-nit", framework_id="fw-style", revision=1, confidence=0.5)
    ]
    envelope = ReviewPredictionV1.model_validate(envelope_dict)
    dumped = envelope.model_dump(mode="json")

    nbi = dumped["private_assessment"]["non_blocking_issues"]
    assert len(nbi) == 1
    assert nbi[0]["framework_id"] == "fw-style"
    assert nbi[0]["revision"] == 1


def test_envelope_with_framework_signals_round_trips():
    framework_signals = [
        _framework_signal(
            framework_id="fw-tests",
            name="Test-coverage gate",
            summary="Require tests before merge.",
            reason="High-confidence rule tied to repeated test review outcomes.",
            confidence=0.9,
        ),
    ]
    envelope_dict = _minimal_envelope(framework_signals=framework_signals)
    envelope = ReviewPredictionV1.model_validate(envelope_dict)
    dumped = envelope.model_dump(mode="json")
    assert len(envelope.framework_signals) == 1
    signal = envelope.framework_signals[0]
    assert signal.framework_id == "fw-tests"
    assert signal.name == "Test-coverage gate"
    assert signal.confidence == 0.9
    assert signal.reason == "High-confidence rule tied to repeated test review outcomes."
    assert signal.evidence_ids == ["ev-1"]
    assert signal.provenance_ids == ["ev-1"]
    assert "evidence_provenance" in dumped["framework_signals"][0]
    assert dumped["framework_signals"][0]["name"] == "Test-coverage gate"


def test_envelope_framework_signals_preserve_extra_schema_fields():
    signal_payload = _framework_signal(
        framework_id="fw-security",
        name="Boundary checks",
        summary="Verify authorization boundaries.",
        reason="Auth change likely intersects existing boundary framework.",
        confidence=0.86,
        evidence_ids=["ev-auth-1", "ev-auth-2"],
        provenance_ids=["prov-auth-1"],
    )
    envelope_dict = _minimal_envelope(framework_signals=[signal_payload])
    envelope = ReviewPredictionV1.model_validate(envelope_dict)
    dumped = envelope.model_dump(mode="json")
    dumped_signal = dumped["framework_signals"][0]
    assert dumped_signal["framework_id"] == "fw-security"
    assert dumped_signal["evidence_ids"] == ["ev-auth-1", "ev-auth-2"]
    assert dumped_signal["provenance_ids"] == ["prov-auth-1"]
    parsed = ReviewPredictionFrameworkSignalV1.model_validate(signal_payload)
    assert parsed.revision == 3
    assert parsed.provenance_ids == ["prov-auth-1"]


def test_envelope_backward_compat_no_framework_fields():
    """Envelopes created before ALLIE-461 (no framework fields) still validate."""
    old_style_signal = {
        "key": "legacy-key",
        "summary": "Old signal",
        "rationale": "Came from before ALLIE-461",
        "confidence": 0.6,
        # no framework_id, no revision
    }
    envelope_dict = _minimal_envelope()
    envelope_dict["private_assessment"]["open_questions"] = [old_style_signal]
    envelope = ReviewPredictionV1.model_validate(envelope_dict)
    oq = envelope.private_assessment.open_questions
    assert oq[0].framework_id is None
    assert oq[0].revision is None


def test_envelope_all_signal_lists_carry_attribution():
    """All four signal lists in private_assessment accept framework attribution."""
    sig = _signal(framework_id="fw-sec", revision=5, confidence=0.85)
    envelope_dict = _minimal_envelope()
    assessment = envelope_dict["private_assessment"]
    assessment["blocking_issues"] = [sig]
    assessment["non_blocking_issues"] = [sig]
    assessment["open_questions"] = [sig]
    assessment["positive_signals"] = [sig]

    envelope = ReviewPredictionV1.model_validate(envelope_dict)
    for lst in [
        envelope.private_assessment.blocking_issues,
        envelope.private_assessment.non_blocking_issues,
        envelope.private_assessment.open_questions,
        envelope.private_assessment.positive_signals,
    ]:
        assert lst[0].framework_id == "fw-sec"
        assert lst[0].revision == 5


def test_envelope_repo_name_optional():
    envelope_dict = _minimal_envelope()
    envelope_dict.pop("repo_name")
    envelope = ReviewPredictionV1.model_validate(envelope_dict)
    assert envelope.repo_name is None


def test_envelope_full_expressed_feedback():
    """Expressed feedback with comments round-trips cleanly."""
    envelope_dict = _minimal_envelope()
    envelope_dict["expressed_feedback"] = {
        "summary": "Needs work before merge.",
        "comments": [
            {
                "type": "blocker",
                "disposition": "request_changes",
                "issue_key": "missing-tests",
                "summary": "No test coverage for the happy path.",
                "rationale": "We require tests for all new code paths.",
            }
        ],
        "approval_state": "request_changes",
    }
    envelope = ReviewPredictionV1.model_validate(envelope_dict)
    dumped = envelope.model_dump(mode="json")
    comments = dumped["expressed_feedback"]["comments"]
    assert len(comments) == 1
    assert comments[0]["type"] == "blocker"
    assert comments[0]["issue_key"] == "missing-tests"
