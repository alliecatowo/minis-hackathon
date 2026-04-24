"""Trusted-service client for durable review-cycle writeback."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
_REVIEW_COMMENT_PATTERN = re.compile(
    r"^-?\s*\*\*(?P<label>[^*]+)\*\*"
    r"(?:\s+`(?P<issue_key>[a-z0-9][a-z0-9_-]*)`)?"
    r"\s*:?\s*(?P<content>.+)$",
    re.IGNORECASE,
)
_LABEL_TO_COMMENT_TYPE = {
    "blocker": ("blocker", "request_changes"),
    "note": ("note", "comment"),
    "question": ("question", "comment"),
    "praise": ("praise", "approve"),
}


def normalize_review_verdict(value: str | None) -> str:
    """Normalize GitHub review states to the backend approval-state vocabulary."""
    if not value:
        return "uncertain"

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "approve": "approve",
        "approved": "approve",
        "comment": "comment",
        "commented": "comment",
        "request_changes": "request_changes",
        "changes_requested": "request_changes",
        "dismissed": "uncertain",
        "pending": "uncertain",
        "uncertain": "uncertain",
    }
    return mapping.get(normalized, "uncertain")


def _trusted_headers() -> dict[str, str] | None:
    if not settings.trusted_service_secret:
        logger.warning(
            "TRUSTED_SERVICE_SECRET is not configured; skipping review-cycle writeback"
        )
        return None
    return {"X-Trusted-Service-Secret": settings.trusted_service_secret}


def _review_cycle_external_id(owner: str, repo: str, pr_number: int, reviewer_login: str) -> str:
    return f"{owner}/{repo}#{pr_number}:{reviewer_login.lower()}"


def _default_private_assessment() -> dict[str, Any]:
    return {
        "blocking_issues": [],
        "non_blocking_issues": [],
        "open_questions": [],
        "positive_signals": [],
        "confidence": None,
    }


def _prediction_to_review_state(prediction: dict[str, Any]) -> dict[str, Any]:
    delivery_policy = prediction.get("delivery_policy")
    structured_delivery_policy = None
    if isinstance(delivery_policy, dict):
        structured_delivery_policy = {
            "author_model": delivery_policy.get("author_model"),
            "context": delivery_policy.get("context"),
            "strictness": delivery_policy.get("strictness"),
            "teaching_mode": delivery_policy.get("teaching_mode"),
            "shield_author_from_noise": delivery_policy.get("shield_author_from_noise"),
        }

    return {
        "private_assessment": prediction.get("private_assessment") or _default_private_assessment(),
        "delivery_policy": structured_delivery_policy,
        "expressed_feedback": prediction.get("expressed_feedback")
        or {
            "summary": "",
            "comments": [],
            "approval_state": "uncertain",
        },
    }


def _human_review_summary(review: dict[str, Any]) -> str:
    body = str(review.get("body") or "").strip()
    if body:
        return body

    verdict = normalize_review_verdict(review.get("state"))
    mapping = {
        "approve": "Approved without written feedback.",
        "comment": "Commented without written feedback.",
        "request_changes": "Requested changes without written feedback.",
        "uncertain": "Review outcome captured without written feedback.",
    }
    return mapping[verdict]


def _extract_structured_review_comments(review: dict[str, Any]) -> list[dict[str, Any]]:
    body = str(review.get("body") or "").strip()
    if not body:
        return []

    comments: list[dict[str, Any]] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _REVIEW_COMMENT_PATTERN.match(line)
        if not match:
            continue

        label = match.group("label").strip().lower()
        issue_key = match.group("issue_key")
        content = match.group("content").strip()
        comment_shape = _LABEL_TO_COMMENT_TYPE.get(label)
        if not issue_key or comment_shape is None:
            continue

        summary, separator, rationale = content.partition("Why:")
        comment_type, disposition = comment_shape
        comments.append(
            {
                "type": comment_type,
                "disposition": disposition,
                "issue_key": issue_key.lower(),
                "summary": summary.strip(),
                "rationale": rationale.strip() if separator else "",
            }
        )

    return comments


def _human_review_to_review_state(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "private_assessment": _default_private_assessment(),
        "delivery_policy": None,
        "expressed_feedback": {
            "summary": _human_review_summary(review),
            "comments": _extract_structured_review_comments(review),
            "approval_state": normalize_review_verdict(review.get("state")),
        },
    }


async def _write_review_cycle(method: str, mini_id: str, payload: dict[str, Any]) -> bool:
    headers = _trusted_headers()
    if headers is None:
        return False

    url = f"{settings.minis_api_url}/api/minis/trusted/{mini_id}/review-cycles"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Review-cycle %s failed with %s for mini %s: %s",
            method,
            exc.response.status_code,
            mini_id,
            exc,
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning("Review-cycle %s failed for mini %s: %s", method, mini_id, exc)
        return False

    return True


async def record_review_prediction(
    *,
    mini_id: str,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    pr_title: str,
    pr_html_url: str | None,
    reviewer_login: str,
    prediction: dict[str, Any],
    github_review_id: int | None,
    github_review_state: str | None,
    author_login: str | None = None,
    author_association: str | None = None,
) -> bool:
    """Persist the structured prediction for one PR/reviewer cycle."""
    metadata_json = {
        "installation_id": installation_id,
        "repo_full_name": f"{owner}/{repo}",
        "pr_number": pr_number,
        "pr_title": pr_title,
        "pr_html_url": pr_html_url,
        "reviewer_login": reviewer_login,
        "review_prediction_version": prediction.get("version"),
        "github_review_id": github_review_id,
        "github_review_state": github_review_state,
    }
    if author_login:
        metadata_json["author_login"] = author_login
    if author_association:
        metadata_json["author_association"] = author_association

    payload = {
        "external_id": _review_cycle_external_id(owner, repo, pr_number, reviewer_login),
        "source_type": "github",
        "predicted_state": _prediction_to_review_state(prediction),
        "metadata_json": metadata_json,
    }
    return await _write_review_cycle("PUT", mini_id, payload)


async def record_human_review_outcome(
    *,
    mini_id: str,
    owner: str,
    repo: str,
    pr_number: int,
    reviewer_login: str,
    action: str,
    review: dict[str, Any],
) -> bool:
    """Persist the human review outcome for an existing PR/reviewer cycle."""
    payload = {
        "external_id": _review_cycle_external_id(owner, repo, pr_number, reviewer_login),
        "source_type": "github",
        "human_review_outcome": _human_review_to_review_state(review),
        "delta_metrics": {
            "github_review_action": action,
            "github_review_id": review.get("id"),
            "github_review_state": review.get("state"),
        },
    }
    return await _write_review_cycle("PATCH", mini_id, payload)
