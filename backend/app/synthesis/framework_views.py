"""Shared formatter for decision-framework views.

This module keeps a single normalization path for framework payloads so the
chat tool, public routes, and owner-only review surfaces all agree on shape
and filtering rules.
"""

from __future__ import annotations

from typing import Any

CONFIDENCE_BAND_LOW: float = 0.3
CONFIDENCE_BAND_HIGH: float = 0.7


def confidence_band(confidence: float) -> str:
    """Return confidence band label: LOW, MEDIUM, or HIGH."""
    if confidence < CONFIDENCE_BAND_LOW:
        return "LOW"
    if confidence >= CONFIDENCE_BAND_HIGH:
        return "HIGH"
    return "MEDIUM"


def _coerce_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_str(value: Any) -> str:
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0].strip()
    return ""


def _get_frameworks(principles_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(principles_json, dict):
        return []
    df_payload = principles_json.get("decision_frameworks")
    if not isinstance(df_payload, dict):
        return []
    raw = df_payload.get("frameworks")
    if not isinstance(raw, list):
        return []
    return [fw for fw in raw if isinstance(fw, dict)]


def _format_decision_framework(fw: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw framework dict to the canonical chat/API wire shape.

    Args:
        fw: A dict representing a single entry from
            ``principles_json["decision_frameworks"]["frameworks"]``.
            Unknown or missing keys are handled gracefully.

    Returns:
        A dict with keys: framework_id, trigger, action, value, confidence,
        revision, badge.
    """
    try:
        confidence = float(fw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    try:
        revision = int(fw.get("revision", 0))
    except (TypeError, ValueError):
        revision = 0

    # Normalise trigger (condition field)
    trigger = ""
    if isinstance(fw.get("condition"), str):
        trigger = fw["condition"].strip()

    # Normalise action — first decision_order entry, else tradeoff
    action = ""
    decision_order = fw.get("decision_order")
    if isinstance(decision_order, list) and decision_order:
        first = decision_order[0]
        if isinstance(first, str):
            action = first.strip()
    if not action and isinstance(fw.get("tradeoff"), str):
        action = fw["tradeoff"].strip()

    # Normalise value — first value_id stripped of "value:" prefix
    value = ""
    value_ids = fw.get("value_ids")
    if isinstance(value_ids, list) and value_ids:
        raw_vid = value_ids[0]
        if isinstance(raw_vid, str):
            value = raw_vid.removeprefix("value:").replace("_", " ").strip()

    # Badge string
    if confidence >= CONFIDENCE_BAND_HIGH:
        badge = "HIGH CONFIDENCE"
    elif confidence < CONFIDENCE_BAND_LOW:
        badge = "LOW CONFIDENCE"
    else:
        badge = ""

    return {
        "framework_id": fw.get("framework_id") or "",
        "trigger": trigger,
        "condition": trigger,
        "action": action,
        "value": value,
        "tradeoff": _coerce_str(fw.get("tradeoff")),
        "confidence": round(confidence, 4),
        "confidence_band": confidence_band(confidence),
        "revision": revision,
        "badge": badge,
        "confidence_history": fw.get("confidence_history") or [],
        "priority": _coerce_str(fw.get("priority")) or "medium",
        "temporal_span": fw.get("temporal_span") or {},
        "evidence_ids": fw.get("evidence_ids") or [],
        "specificity_level": _coerce_str(fw.get("specificity_level")) or "case_pattern",
        "retired": bool(fw.get("retired", False)),
    }


def format_decision_frameworks(
    principles_json: dict[str, Any] | None,
    *,
    min_confidence: float = 0.0,
    limit: int = 10,
    include_retired: bool = False,
) -> list[dict[str, Any]]:
    """Return normalized frameworks sorted by confidence and revision.

    The returned entries include both legacy wire keys (trigger/badge) and the
    richer fields needed by frameworks-at-risk and owner review surfaces.
    """
    result = [_format_decision_framework(raw) for raw in _get_frameworks(principles_json)]

    if not include_retired:
        result = [fw for fw in result if not fw.get("retired", False)]

    if min_confidence > 0.0:
        result = [fw for fw in result if fw["confidence"] >= min_confidence]

    result.sort(key=lambda fw: (-fw["confidence"], -fw["revision"]))
    return result[:limit]
