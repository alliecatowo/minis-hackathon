from __future__ import annotations

from typing import Any

from app.models.evidence import ReviewCycle
from app.models.mini import Mini
from scripts.calculate_review_agreement import calculate_metrics

_TREND_EPSILON = 0.001


def _ordered_cycles(cycles: list[ReviewCycle]) -> list[ReviewCycle]:
    return sorted(cycles, key=lambda cycle: getattr(cycle, "predicted_at", "") or "")


def _build_trend(cycles: list[ReviewCycle]) -> dict[str, Any]:
    if len(cycles) < 2:
        return {"direction": "insufficient_data", "delta": None}

    ordered_cycles = _ordered_cycles(cycles)
    midpoint = len(ordered_cycles) // 2
    earlier_metrics = calculate_metrics(ordered_cycles[:midpoint])
    recent_metrics = calculate_metrics(ordered_cycles[midpoint:])
    if not earlier_metrics or not recent_metrics:
        return {"direction": "insufficient_data", "delta": None}

    earlier_score = (
        earlier_metrics["approval_accuracy"]
        + earlier_metrics["blocker_precision"]
        + earlier_metrics["comment_overlap"]
    ) / 3
    recent_score = (
        recent_metrics["approval_accuracy"]
        + recent_metrics["blocker_precision"]
        + recent_metrics["comment_overlap"]
    ) / 3
    delta = recent_score - earlier_score

    if abs(delta) < _TREND_EPSILON:
        direction = "flat"
    elif delta > 0:
        direction = "up"
    else:
        direction = "down"

    return {"direction": direction, "delta": delta}


def build_agreement_scorecard_summary(
    mini: Mini,
    cycles: list[ReviewCycle],
) -> dict[str, Any]:
    metrics = calculate_metrics(cycles)
    if metrics is None:
        return {
            "mini_id": mini.id,
            "username": mini.username,
            "cycles_count": 0,
            "approval_accuracy": None,
            "blocker_precision": None,
            "comment_overlap": None,
            "trend": {"direction": "insufficient_data", "delta": None},
        }

    return {
        "mini_id": mini.id,
        "username": mini.username,
        "cycles_count": metrics["count"],
        "approval_accuracy": metrics["approval_accuracy"],
        "blocker_precision": metrics["blocker_precision"],
        "blocker_recall": metrics["blocker_recall"],
        "comment_overlap": metrics["comment_overlap"],
        "trend": _build_trend(cycles),
    }
