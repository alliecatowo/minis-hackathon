"""Persistence helpers for review prediction/outcome cycles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ExplorerFinding, ExplorerQuote, ReviewCycle
from app.models.schemas import (
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
)

_REVIEW_WRITEBACK_SOURCE = "review_writeback"
_PRIVATE_ASSESSMENT_GROUP_DEFAULTS = {
    "blocking_issues": {"type": "blocker", "disposition": "request_changes"},
    "non_blocking_issues": {"type": "note", "disposition": "comment"},
    "open_questions": {"type": "question", "disposition": "comment"},
    "positive_signals": {"type": "praise", "disposition": "approve"},
}


def _extract_approval_state(review_state: dict | None) -> str | None:
    """Read the approval state from a structured review-state payload."""
    if not isinstance(review_state, dict):
        return None

    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return None

    approval_state = expressed_feedback.get("approval_state")
    return approval_state if isinstance(approval_state, str) else None


def _extract_feedback_summary(review_state: dict | None) -> str | None:
    """Read the human-facing summary from a structured review-state payload."""
    if not isinstance(review_state, dict):
        return None

    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return None

    summary = expressed_feedback.get("summary")
    if not isinstance(summary, str):
        return None

    summary = summary.strip()
    return summary or None


def _normalize_review_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _normalize_issue_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    return normalized or None


def _extract_issue_key(item: Any, *, allow_id_fallback: bool = False) -> str | None:
    if not isinstance(item, dict):
        return None

    field_names = ["issue_key", "key"]
    if allow_id_fallback:
        field_names.append("id")

    for field_name in field_names:
        issue_key = _normalize_issue_key(item.get(field_name))
        if issue_key:
            return issue_key
    return None


def _extract_issue_summary(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None

    for field_name in ("summary", "body", "detail", "value"):
        value = item.get(field_name)
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
    return None


def _extract_issue_rationale(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None

    rationale = item.get("rationale")
    if not isinstance(rationale, str):
        return None

    rationale = rationale.strip()
    return rationale or None


def _issue_severity(
    *,
    comment_type: str | None = None,
    disposition: str | None = None,
    approval_state: str | None = None,
) -> int:
    normalized_type = _normalize_review_value(comment_type)
    normalized_disposition = _normalize_review_value(disposition)
    normalized_approval_state = _normalize_review_value(approval_state)

    if normalized_disposition == "request_changes" or normalized_type == "blocker":
        return 3
    if normalized_disposition == "comment" or normalized_type in {"note", "question"}:
        return 2
    if normalized_disposition == "approve" or normalized_type == "praise":
        return 1

    if normalized_approval_state == "request_changes":
        return 3
    if normalized_approval_state == "comment":
        return 2
    if normalized_approval_state == "approve":
        return 1
    return 0


def _merge_issue_details(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for field_name, value in override.items():
        if value is None:
            continue
        if field_name == "severity":
            merged[field_name] = max(int(merged.get(field_name) or 0), int(value))
            continue
        merged[field_name] = value
    return merged


def _collect_reconciled_issues(review_state: dict | None) -> dict[str, dict[str, Any]]:
    issues: dict[str, dict[str, Any]] = {}
    if not isinstance(review_state, dict):
        return issues

    private_assessment = review_state.get("private_assessment")
    if isinstance(private_assessment, dict):
        for group_name, defaults in _PRIVATE_ASSESSMENT_GROUP_DEFAULTS.items():
            items = private_assessment.get(group_name)
            if not isinstance(items, list):
                continue

            for item in items:
                issue_key = _extract_issue_key(item, allow_id_fallback=True)
                if not issue_key:
                    continue

                issues[issue_key] = _merge_issue_details(
                    issues.get(issue_key, {"issue_key": issue_key}),
                    {
                        "type": defaults["type"],
                        "disposition": defaults["disposition"],
                        "summary": _extract_issue_summary(item),
                        "rationale": _extract_issue_rationale(item),
                        "source": group_name,
                        "severity": _issue_severity(
                            comment_type=defaults["type"],
                            disposition=defaults["disposition"],
                        ),
                    },
                )

    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return issues

    comments = expressed_feedback.get("comments")
    if not isinstance(comments, list):
        return issues

    overall_approval_state = _extract_approval_state(review_state)
    for comment in comments:
        issue_key = _extract_issue_key(comment)
        if not issue_key:
            continue

        comment_type = None
        disposition = None
        if isinstance(comment, dict):
            comment_type = _normalize_review_value(comment.get("type"))
            disposition = _normalize_review_value(comment.get("disposition"))

        issues[issue_key] = _merge_issue_details(
            issues.get(issue_key, {"issue_key": issue_key}),
            {
                "type": comment_type,
                "disposition": disposition,
                "summary": _extract_issue_summary(comment),
                "rationale": _extract_issue_rationale(comment),
                "source": "comment",
                "severity": _issue_severity(
                    comment_type=comment_type,
                    disposition=disposition,
                    approval_state=overall_approval_state,
                ),
            },
        )

    return issues


def _resolve_issue_outcome(
    predicted_issue: dict[str, Any],
    actual_issue: dict[str, Any] | None,
    *,
    actual_approval_state: str | None,
) -> str:
    predicted_severity = int(predicted_issue.get("severity") or 0)
    if actual_issue is None:
        return "resolved_before_submit" if actual_approval_state == "approve" else "not_raised"

    actual_severity = int(
        actual_issue.get("severity")
        or _issue_severity(approval_state=actual_approval_state)
    )

    if actual_severity > predicted_severity:
        return "escalated"
    if actual_severity == predicted_severity:
        return "confirmed"
    if actual_severity > 0:
        return "downgraded"
    return "resolved_before_submit" if actual_approval_state == "approve" else "not_raised"


def _terminal_resolution(issue_outcomes: list[dict[str, Any]]) -> str | None:
    predicted_issue_outcomes = [
        item["outcome"]
        for item in issue_outcomes
        if item.get("outcome") and item.get("predicted_type") is not None
    ]
    has_new_issue = any(item.get("outcome") == "new_issue" for item in issue_outcomes)

    if not predicted_issue_outcomes:
        if has_new_issue:
            return "new_issue"
        return None

    unique_outcomes = set(predicted_issue_outcomes)
    if len(unique_outcomes) == 1 and not has_new_issue:
        return predicted_issue_outcomes[0]
    return "mixed"


def _reconcile_issue_outcomes(
    predicted_state: dict | None,
    human_review_outcome: dict | None,
) -> dict[str, Any]:
    predicted_issues = _collect_reconciled_issues(predicted_state)
    actual_issues = _collect_reconciled_issues(human_review_outcome)
    actual_approval_state = _extract_approval_state(human_review_outcome)

    issue_outcomes: list[dict[str, Any]] = []
    matched_issue_count = 0

    for issue_key, predicted_issue in sorted(predicted_issues.items()):
        actual_issue = actual_issues.get(issue_key)
        if actual_issue is not None:
            matched_issue_count += 1

        issue_outcomes.append(
            {
                "issue_key": issue_key,
                "outcome": _resolve_issue_outcome(
                    predicted_issue,
                    actual_issue,
                    actual_approval_state=actual_approval_state,
                ),
                "predicted_type": predicted_issue.get("type"),
                "predicted_disposition": predicted_issue.get("disposition"),
                "predicted_summary": predicted_issue.get("summary"),
                "actual_type": actual_issue.get("type") if actual_issue else None,
                "actual_disposition": actual_issue.get("disposition") if actual_issue else None,
                "actual_summary": actual_issue.get("summary") if actual_issue else None,
            }
        )

    for issue_key, actual_issue in sorted(actual_issues.items()):
        if issue_key in predicted_issues:
            continue

        issue_outcomes.append(
            {
                "issue_key": issue_key,
                "outcome": "new_issue",
                "predicted_type": None,
                "predicted_disposition": None,
                "predicted_summary": None,
                "actual_type": actual_issue.get("type"),
                "actual_disposition": actual_issue.get("disposition"),
                "actual_summary": actual_issue.get("summary"),
            }
        )

    return {
        "terminal_resolution": _terminal_resolution(issue_outcomes),
        "issue_outcomes": issue_outcomes,
        "predicted_issue_count": len(predicted_issues),
        "matched_issue_count": matched_issue_count,
        "actual_issue_count": len(actual_issues),
    }


def _format_issue_outcome_summary(issue_outcomes: Any) -> str | None:
    if not isinstance(issue_outcomes, list):
        return None

    rendered: list[str] = []
    for item in issue_outcomes:
        if not isinstance(item, dict):
            continue
        issue_key = _normalize_issue_key(item.get("issue_key"))
        outcome = _normalize_review_value(item.get("outcome"))
        if issue_key and outcome:
            rendered.append(f"{issue_key}={outcome}")

    return ", ".join(rendered) or None


def _review_cycle_marker(cycle: ReviewCycle) -> str:
    """Return a stable marker used to replace prior writeback artifacts."""
    return f"[review_cycle:{cycle.id}]"


def _review_cycle_target(cycle: ReviewCycle) -> str:
    """Build a compact label for the reviewed artifact."""
    metadata_json = cycle.metadata_json if isinstance(cycle.metadata_json, dict) else {}
    repo_full_name = metadata_json.get("repo_full_name")
    pr_number = metadata_json.get("pr_number")

    if isinstance(repo_full_name, str) and repo_full_name.strip():
        if pr_number is not None:
            return f"{repo_full_name}#{pr_number}"
        return repo_full_name
    return cycle.external_id


async def _writeback_review_cycle_learning(
    session: AsyncSession,
    cycle: ReviewCycle,
) -> None:
    """Persist compact review-outcome artifacts for downstream synthesis."""
    marker = _review_cycle_marker(cycle)
    marker_prefix = f"{marker}%"

    await session.execute(
        delete(ExplorerFinding).where(
            ExplorerFinding.mini_id == cycle.mini_id,
            ExplorerFinding.source_type == _REVIEW_WRITEBACK_SOURCE,
            ExplorerFinding.content.like(marker_prefix),
        )
    )
    await session.execute(
        delete(ExplorerQuote).where(
            ExplorerQuote.mini_id == cycle.mini_id,
            ExplorerQuote.source_type == _REVIEW_WRITEBACK_SOURCE,
            ExplorerQuote.context.like(marker_prefix),
        )
    )

    predicted_approval_state = _extract_approval_state(cycle.predicted_state) or "unknown"
    actual_approval_state = _extract_approval_state(cycle.human_review_outcome) or "unknown"

    approval_state_changed = None
    if isinstance(cycle.delta_metrics, dict):
        changed_value = cycle.delta_metrics.get("approval_state_changed")
        if isinstance(changed_value, bool):
            approval_state_changed = changed_value
    if approval_state_changed is None:
        approval_state_changed = predicted_approval_state != actual_approval_state

    target = _review_cycle_target(cycle)
    feedback_summary = _extract_feedback_summary(cycle.human_review_outcome)
    finding_content = (
        f"{marker} Review outcome calibration for {target}: "
        f"predicted approval_state={predicted_approval_state}, "
        f"actual approval_state={actual_approval_state}, "
        f"approval_state_changed={'yes' if approval_state_changed else 'no'}."
    )
    if isinstance(cycle.delta_metrics, dict):
        terminal_resolution = _normalize_review_value(cycle.delta_metrics.get("terminal_resolution"))
        if terminal_resolution:
            finding_content += f" terminal_resolution={terminal_resolution}."

        issue_outcome_summary = _format_issue_outcome_summary(
            cycle.delta_metrics.get("issue_outcomes")
        )
        if issue_outcome_summary:
            finding_content += f" issue_outcomes={issue_outcome_summary}."

    if feedback_summary:
        finding_content += f" Human summary: {feedback_summary}"

    session.add(
        ExplorerFinding(
            mini_id=cycle.mini_id,
            source_type=_REVIEW_WRITEBACK_SOURCE,
            category="decision_patterns",
            content=finding_content,
            confidence=0.95,
        )
    )

    if feedback_summary:
        session.add(
            ExplorerQuote(
                mini_id=cycle.mini_id,
                source_type=_REVIEW_WRITEBACK_SOURCE,
                quote=feedback_summary,
                context=f"{marker} human_review_outcome for {target}",
                significance="review_outcome",
            )
        )


async def upsert_review_cycle_prediction(
    session: AsyncSession,
    mini_id: str,
    body: ReviewCyclePredictionUpsertRequest,
) -> ReviewCycle:
    """Create or refresh the predicted state for one review cycle."""
    result = await session.execute(
        select(ReviewCycle).where(
            ReviewCycle.mini_id == mini_id,
            ReviewCycle.source_type == body.source_type,
            ReviewCycle.external_id == body.external_id,
        )
    )
    cycle = result.scalar_one_or_none()
    predicted_at = datetime.now(UTC)
    predicted_state = body.predicted_state.model_dump(mode="json")

    if cycle is None:
        cycle = ReviewCycle(
            mini_id=mini_id,
            source_type=body.source_type,
            external_id=body.external_id,
            metadata_json=body.metadata_json,
            predicted_state=predicted_state,
            predicted_at=predicted_at,
        )
        session.add(cycle)
    else:
        cycle.source_type = body.source_type
        cycle.predicted_state = predicted_state
        cycle.predicted_at = predicted_at
        if body.metadata_json is not None:
            cycle.metadata_json = body.metadata_json

    await session.commit()
    await session.refresh(cycle)
    return cycle


async def finalize_review_cycle(
    session: AsyncSession,
    mini_id: str,
    body: ReviewCycleOutcomeUpdateRequest,
) -> ReviewCycle | None:
    """Persist the eventual human review outcome and compact delta metrics."""
    result = await session.execute(
        select(ReviewCycle).where(
            ReviewCycle.mini_id == mini_id,
            ReviewCycle.source_type == body.source_type,
            ReviewCycle.external_id == body.external_id,
        )
    )
    cycle = result.scalar_one_or_none()
    if cycle is None:
        return None

    human_review_outcome = body.human_review_outcome.model_dump(mode="json")
    predicted_approval_state = _extract_approval_state(cycle.predicted_state)
    actual_approval_state = _extract_approval_state(human_review_outcome)

    delta_metrics = dict(body.delta_metrics)
    if predicted_approval_state is not None:
        delta_metrics["predicted_approval_state"] = predicted_approval_state
    if actual_approval_state is not None:
        delta_metrics["actual_approval_state"] = actual_approval_state
    if predicted_approval_state is not None and actual_approval_state is not None:
        delta_metrics["approval_state_changed"] = (
            predicted_approval_state != actual_approval_state
        )

    reconciliation = _reconcile_issue_outcomes(cycle.predicted_state, human_review_outcome)
    if reconciliation["terminal_resolution"] is not None:
        delta_metrics["terminal_resolution"] = reconciliation["terminal_resolution"]
    delta_metrics["issue_outcomes"] = reconciliation["issue_outcomes"]
    delta_metrics["predicted_issue_count"] = reconciliation["predicted_issue_count"]
    delta_metrics["matched_issue_count"] = reconciliation["matched_issue_count"]
    delta_metrics["actual_issue_count"] = reconciliation["actual_issue_count"]

    cycle.human_review_outcome = human_review_outcome
    cycle.delta_metrics = delta_metrics
    cycle.human_reviewed_at = datetime.now(UTC)
    await _writeback_review_cycle_learning(session, cycle)

    await session.commit()
    await session.refresh(cycle)
    return cycle
