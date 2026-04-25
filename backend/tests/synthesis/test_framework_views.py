"""Tests for framework_views shared formatter (ALLIE-519).

Covers:
- ``confidence_band()`` helper
- ``format_decision_frameworks()`` — filtering, sorting, retired exclusion
"""
from __future__ import annotations


from app.synthesis.framework_views import (
    CONFIDENCE_BAND_HIGH,
    CONFIDENCE_BAND_LOW,
    confidence_band,
    format_decision_frameworks,
)


# ---------------------------------------------------------------------------
# confidence_band
# ---------------------------------------------------------------------------


def test_confidence_band_low():
    assert confidence_band(0.0) == "LOW"
    assert confidence_band(0.15) == "LOW"
    assert confidence_band(CONFIDENCE_BAND_LOW - 0.01) == "LOW"


def test_confidence_band_medium():
    assert confidence_band(CONFIDENCE_BAND_LOW) == "MEDIUM"
    assert confidence_band(0.5) == "MEDIUM"
    assert confidence_band(CONFIDENCE_BAND_HIGH - 0.01) == "MEDIUM"


def test_confidence_band_high():
    assert confidence_band(CONFIDENCE_BAND_HIGH) == "HIGH"
    assert confidence_band(1.0) == "HIGH"


# ---------------------------------------------------------------------------
# format_decision_frameworks — basic behaviour
# ---------------------------------------------------------------------------


def _fw(
    framework_id: str = "framework:test",
    condition: str = "When tests are absent",
    confidence: float = 0.7,
    revision: int = 0,
    retired: bool = False,
) -> dict:
    return {
        "framework_id": framework_id,
        "condition": condition,
        "action": "Block the PR",
        "value_ids": ["value:quality"],
        "confidence": confidence,
        "revision": revision,
        "confidence_history": [],
        "priority": "high",
        "tradeoff": "Quality over speed",
        "temporal_span": {},
        "evidence_ids": [],
        "specificity_level": "scope_local",
        "retired": retired,
    }


def _p_json(frameworks: list[dict]) -> dict:
    return {
        "principles": [],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": frameworks,
            "source": "principles_motivations_normalizer",
        },
    }


def test_format_decision_frameworks_empty_input():
    assert format_decision_frameworks(None) == []
    assert format_decision_frameworks({}) == []
    assert format_decision_frameworks({"decision_frameworks": {}}) == []


def test_format_decision_frameworks_single_framework():
    result = format_decision_frameworks(_p_json([_fw()]))
    assert len(result) == 1
    fw = result[0]
    assert fw["framework_id"] == "framework:test"
    assert fw["condition"] == "When tests are absent"
    assert fw["confidence_band"] == "HIGH"
    assert fw["retired"] is False


def test_format_decision_frameworks_excludes_retired_by_default():
    fws = [
        _fw(framework_id="framework:active", confidence=0.8),
        _fw(framework_id="framework:retired", confidence=0.5, retired=True),
    ]
    result = format_decision_frameworks(_p_json(fws))
    ids = [f["framework_id"] for f in result]
    assert "framework:active" in ids
    assert "framework:retired" not in ids


def test_format_decision_frameworks_includes_retired_when_asked():
    fws = [
        _fw(framework_id="framework:active", confidence=0.8),
        _fw(framework_id="framework:retired", confidence=0.5, retired=True),
    ]
    result = format_decision_frameworks(_p_json(fws), include_retired=True)
    ids = [f["framework_id"] for f in result]
    assert "framework:active" in ids
    assert "framework:retired" in ids


def test_format_decision_frameworks_sorted_by_confidence_desc():
    fws = [
        _fw(framework_id="framework:low", confidence=0.2),
        _fw(framework_id="framework:high", confidence=0.9),
        _fw(framework_id="framework:mid", confidence=0.5),
    ]
    result = format_decision_frameworks(_p_json(fws))
    confidences = [f["confidence"] for f in result]
    assert confidences == sorted(confidences, reverse=True)


def test_format_decision_frameworks_tie_broken_by_revision_desc():
    fws = [
        _fw(framework_id="framework:a", confidence=0.7, revision=1),
        _fw(framework_id="framework:b", confidence=0.7, revision=5),
    ]
    result = format_decision_frameworks(_p_json(fws))
    assert result[0]["framework_id"] == "framework:b"
    assert result[1]["framework_id"] == "framework:a"


def test_format_decision_frameworks_confidence_band_low():
    fws = [_fw(confidence=0.2)]
    result = format_decision_frameworks(_p_json(fws))
    assert result[0]["confidence_band"] == "LOW"


def test_format_decision_frameworks_confidence_band_medium():
    fws = [_fw(confidence=0.5)]
    result = format_decision_frameworks(_p_json(fws))
    assert result[0]["confidence_band"] == "MEDIUM"


def test_format_decision_frameworks_value_derived_from_value_ids():
    fw = _fw()
    fw["value_ids"] = ["value:code_quality"]
    result = format_decision_frameworks(_p_json([fw]))
    assert result[0]["value"] == "code quality"


def test_format_decision_frameworks_malformed_frameworks_skipped():
    """Non-dict entries in the frameworks list are skipped gracefully."""
    p_json = {
        "decision_frameworks": {
            "frameworks": ["not-a-dict", None, 42, _fw(framework_id="framework:ok")],
        }
    }
    result = format_decision_frameworks(p_json)
    assert len(result) == 1
    assert result[0]["framework_id"] == "framework:ok"
