"""Webhook event handlers for GitHub App events."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings
from app.github_api import (
    get_pr_changed_files,
    get_pr_details,
    get_pr_diff,
    get_pr_requested_reviewers,
    get_repo_collaborator_permission,
    post_issue_comment,
    post_pr_review,
)
from app.review import (
    format_review_comment,
    generate_mention_response,
    get_mini,
    get_review_prediction,
    infer_author_model_from_github_context,
    infer_delivery_context,
    render_review_prediction,
)
from app.outcome_capture import build_disposition_map
from app.outcome_capture import extract_issue_keys_from_text
from app.outcome_capture import map_signal_issue_key
from app.review_cycles import (
    record_comment_outcome,
    record_human_review_outcome,
    record_review_prediction,
)

logger = logging.getLogger(__name__)

# Pattern to match @mentions of minis: @username-mini
MENTION_PATTERN = re.compile(r"@(\w[\w-]*)" + re.escape(settings.mini_mention_suffix))
REVIEW_REQUEST_PATTERN = re.compile(
    r"\b(?:pre-?review|review|reviewer\s+mode)\b",
    re.IGNORECASE,
)


def _pr_author_context(pr: dict) -> tuple[str | None, str | None]:
    author = pr.get("user") or {}
    author_login = author.get("login")
    author_association = pr.get("author_association")
    return author_login, author_association


def _is_explicit_review_request(body: str) -> bool:
    """Return true only when the user asked the mini to act as a reviewer."""
    return bool(REVIEW_REQUEST_PATTERN.search(body or ""))


async def _get_permission_hint(
    installation_id: int,
    owner: str,
    repo_name: str,
    login: str | None,
) -> str | None:
    if not login:
        return None

    try:
        return await get_repo_collaborator_permission(installation_id, owner, repo_name, login)
    except Exception:
        logger.warning(
            "Failed to fetch collaborator permission for %s in %s/%s",
            login,
            owner,
            repo_name,
        )
        return None


async def _infer_author_model_for_reviewer(
    *,
    installation_id: int,
    owner: str,
    repo_name: str,
    author_login: str | None,
    author_association: str | None,
    reviewer_login: str,
    author_permission: str | None = None,
) -> str:
    reviewer_permission = None
    normalized_author = (author_login or "").strip().lower()
    normalized_reviewer = reviewer_login.strip().lower()

    if normalized_reviewer and normalized_reviewer != normalized_author:
        reviewer_permission = await _get_permission_hint(
            installation_id,
            owner,
            repo_name,
            reviewer_login,
        )

    return infer_author_model_from_github_context(
        author_association=author_association,
        author_login=author_login,
        repo_owner_login=owner,
        reviewer_login=reviewer_login,
        author_permission=author_permission,
        reviewer_permission=reviewer_permission,
    )


async def _resolve_requested_reviewers(
    payload: dict,
    *,
    installation_id: int,
    owner: str,
    repo_name: str,
    pr_number: int,
) -> list[dict[str, str | bool | None]]:
    requested_reviewer = payload.get("requested_reviewer") or {}
    requested_login = requested_reviewer.get("login")
    requested_type = requested_reviewer.get("type")
    if (
        payload.get("action") == "review_requested"
        and requested_login
        and (requested_type is None or requested_type == "User")
    ):
        return [
            {
                "login": requested_login,
                "type": requested_type,
                "site_admin": bool(requested_reviewer.get("site_admin", False)),
            }
        ]

    return await get_pr_requested_reviewers(installation_id, owner, repo_name, pr_number)


async def handle_pull_request_opened(payload: dict) -> None:
    """Handle pull_request.opened — auto-review if requested reviewers have minis."""
    pr = payload["pull_request"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    pr_title = pr["title"]
    pr_body = pr.get("body") or ""
    pr_html_url = pr.get("html_url")
    repo_full_name = f"{owner}/{repo_name}"
    delivery_context = infer_delivery_context(pr_title, pr_body)
    author_login, author_association = _pr_author_context(pr)

    logger.info("PR #%d opened in %s/%s: %s", pr_number, owner, repo_name, pr_title)

    reviewers = await _resolve_requested_reviewers(
        payload,
        installation_id=installation_id,
        owner=owner,
        repo_name=repo_name,
        pr_number=pr_number,
    )
    if not reviewers:
        logger.info("No requested reviewers for PR #%d, skipping", pr_number)
        return

    reviewer_minis: list[tuple[str, dict[str, Any]]] = []
    for reviewer in reviewers:
        reviewer_login = reviewer["login"]
        if not reviewer_login:
            continue

        mini = await get_mini(reviewer_login)
        if not mini:
            logger.info("No mini found for reviewer %s", reviewer_login)
            continue
        reviewer_minis.append((str(reviewer_login), mini))

    if not reviewer_minis:
        logger.info("No minis found for requested reviewers on PR #%d, skipping", pr_number)
        return

    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)
    changed_files = await get_pr_changed_files(installation_id, owner, repo_name, pr_number)
    author_permission = await _get_permission_hint(installation_id, owner, repo_name, author_login)

    for reviewer_login, mini in reviewer_minis:
        author_model = await _infer_author_model_for_reviewer(
            installation_id=installation_id,
            owner=owner,
            repo_name=repo_name,
            author_login=author_login,
            author_association=author_association,
            reviewer_login=reviewer_login,
            author_permission=author_permission,
        )
        prediction = await get_review_prediction(
            mini["id"],
            repo_name=repo_full_name,
            pr_title=pr_title,
            pr_body=pr_body,
            diff=diff,
            changed_files=changed_files,
            author_model=author_model,
            delivery_context=delivery_context,
        )
        review_text = render_review_prediction(
            prediction,
            requested_via_review_request=True,
        )

        logger.info("Generating review for PR #%d as %s's mini", pr_number, reviewer_login)

        formatted = format_review_comment(reviewer_login, review_text)
        posted_review = await post_pr_review(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            body=formatted,
            event="COMMENT",
        )
        persisted = await record_review_prediction(
            mini_id=mini["id"],
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_html_url=pr_html_url,
            reviewer_login=reviewer_login,
            prediction=prediction,
            github_review_id=posted_review.get("id"),
            github_review_state=posted_review.get("state"),
            author_login=author_login,
            author_association=author_association,
        )

        if persisted:
            logger.info("Posted review for PR #%d as %s's mini", pr_number, reviewer_login)
        else:
            logger.warning(
                "Posted review for PR #%d as %s's mini, but review-cycle writeback failed",
                pr_number,
                reviewer_login,
            )


async def handle_issue_comment(payload: dict) -> None:
    """Handle issue_comment.created — check for @mentions of minis."""
    comment = payload["comment"]
    issue = payload["issue"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]

    if "pull_request" not in issue:
        return

    body = comment.get("body") or ""
    mentions = MENTION_PATTERN.findall(body)
    if not mentions:
        return

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = issue["number"]
    repo_full_name = f"{owner}/{repo_name}"

    logger.info("Comment on PR #%d mentions minis: %s", pr_number, ", ".join(mentions))

    pr_details = await get_pr_details(installation_id, owner, repo_name, pr_number)
    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)
    changed_files = await get_pr_changed_files(installation_id, owner, repo_name, pr_number)
    delivery_context = infer_delivery_context(pr_details["title"], pr_details.get("body") or "")
    author_login, author_association = _pr_author_context(pr_details)
    author_permission = await _get_permission_hint(installation_id, owner, repo_name, author_login)
    requested_reviewer_mode = _is_explicit_review_request(body)

    for username in mentions:
        mini = await get_mini(username)
        if not mini:
            logger.info("No mini found for mentioned user %s", username)
            continue

        author_model = await _infer_author_model_for_reviewer(
            installation_id=installation_id,
            owner=owner,
            repo_name=repo_name,
            author_login=author_login,
            author_association=author_association,
            reviewer_login=username,
            author_permission=author_permission,
        )
        logger.info("Generating response for %s's mini on PR #%d", username, pr_number)

        if requested_reviewer_mode:
            prediction = await get_review_prediction(
                mini["id"],
                repo_name=repo_full_name,
                pr_title=pr_details["title"],
                pr_body=pr_details.get("body") or "",
                diff=diff,
                changed_files=changed_files,
                author_model=author_model,
                delivery_context=delivery_context,
            )
            review_text = render_review_prediction(
                prediction,
                requested_via_review_request=True,
            )
            formatted = format_review_comment(username, review_text)
            posted_review = await post_pr_review(
                installation_id=installation_id,
                owner=owner,
                repo=repo_name,
                pr_number=pr_number,
                body=formatted,
                event="COMMENT",
            )
            await record_review_prediction(
                mini_id=mini["id"],
                installation_id=installation_id,
                owner=owner,
                repo=repo_name,
                pr_number=pr_number,
                pr_title=pr_details["title"],
                pr_html_url=pr_details.get("html_url") or issue.get("html_url"),
                reviewer_login=username,
                prediction=prediction,
                github_review_id=posted_review.get("id"),
                github_review_state=posted_review.get("state"),
                author_login=author_login,
                author_association=author_association,
            )
            logger.info(
                "Posted reviewer-mode mention response for %s's mini on PR #%d",
                username,
                pr_number,
            )
            continue

        response_text = await generate_mention_response(
            mini=mini,
            user_message=body,
            pr_title=pr_details["title"],
            pr_body=pr_details.get("body") or "",
            diff=diff,
            repo_name=repo_full_name,
            changed_files=changed_files,
            author_model=author_model,
            delivery_context=delivery_context,
        )

        formatted = format_review_comment(username, response_text)
        await post_issue_comment(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            issue_number=pr_number,
            body=formatted,
        )

        logger.info("Posted mention response for %s's mini on PR #%d", username, pr_number)


async def handle_pr_review_comment(payload: dict) -> None:
    """Handle pull_request_review_comment.created — respond to review threads mentioning minis."""
    comment = payload["comment"]
    pr = payload["pull_request"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]

    body = comment.get("body") or ""
    mentions = MENTION_PATTERN.findall(body)
    if not mentions:
        return

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    repo_full_name = f"{owner}/{repo_name}"

    logger.info("Review comment on PR #%d mentions minis: %s", pr_number, ", ".join(mentions))

    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)
    changed_files = await get_pr_changed_files(installation_id, owner, repo_name, pr_number)
    delivery_context = infer_delivery_context(pr["title"], pr.get("body") or "")
    author_login, author_association = _pr_author_context(pr)
    author_permission = await _get_permission_hint(installation_id, owner, repo_name, author_login)

    for username in mentions:
        mini = await get_mini(username)
        if not mini:
            continue

        author_model = await _infer_author_model_for_reviewer(
            installation_id=installation_id,
            owner=owner,
            repo_name=repo_name,
            author_login=author_login,
            author_association=author_association,
            reviewer_login=username,
            author_permission=author_permission,
        )
        response_text = await generate_mention_response(
            mini=mini,
            user_message=body,
            pr_title=pr["title"],
            pr_body=pr.get("body") or "",
            diff=diff,
            repo_name=repo_full_name,
            changed_files=changed_files,
            author_model=author_model,
            delivery_context=delivery_context,
        )

        formatted = format_review_comment(username, response_text)

        await post_issue_comment(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            issue_number=pr_number,
            body=formatted,
        )

        logger.info("Posted review thread response for %s's mini on PR #%d", username, pr_number)


async def handle_pull_request_review(payload: dict) -> None:
    """Handle pull_request_review webhooks to persist human review outcomes."""
    review = payload["review"]
    pr = payload["pull_request"]
    repo = payload["repository"]
    action = payload.get("action", "")

    reviewer = review.get("user") or payload.get("sender") or {}
    reviewer_login = reviewer.get("login")
    reviewer_type = reviewer.get("type")

    if not reviewer_login:
        logger.info("Skipping pull_request_review without reviewer login")
        return

    if reviewer_type and reviewer_type != "User":
        logger.info(
            "Skipping non-human pull_request_review on PR #%d from %s (%s)",
            pr["number"],
            reviewer_login,
            reviewer_type,
        )
        return

    mini = await get_mini(reviewer_login)
    if not mini:
        logger.info("No mini found for reviewer %s; skipping review-cycle writeback", reviewer_login)
        return

    persisted = await record_human_review_outcome(
        mini_id=mini["id"],
        owner=repo["owner"]["login"],
        repo=repo["name"],
        pr_number=pr["number"],
        reviewer_login=reviewer_login,
        action=action,
        review=review,
    )

    if persisted:
        logger.info(
            "Recorded human review event %s for PR #%d from %s",
            action,
            pr["number"],
            reviewer_login,
        )
    else:
        logger.warning(
            "Failed to persist human review event %s for PR #%d from %s",
            action,
            pr["number"],
            reviewer_login,
        )


async def handle_pr_review_comment_reaction(payload: dict) -> None:
    """Handle pull_request_review_comment reaction events for outcome capture.

    Fires when a human posts a reaction (e.g. thumbs-up/down) on a review comment.
    If the comment was posted by the GH App (bot) on behalf of a mini, we capture
    the reaction as a suggestion-level outcome signal and patch the review cycle.

    The feature flag ``GH_APP_OUTCOME_CAPTURE`` gates this handler.
    """
    # Feature flag: GH_APP_OUTCOME_CAPTURE is checked in the backend, but we also
    # guard here via env var so the github-app process can be independently gated.
    import os

    if os.environ.get("GH_APP_OUTCOME_CAPTURE", "").strip().lower() not in {"true", "1", "yes"}:
        logger.debug("GH_APP_OUTCOME_CAPTURE disabled; skipping reaction outcome capture")
        return

    comment = payload.get("comment") or {}
    reaction = payload.get("reaction") or {}
    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    sender = payload.get("sender") or {}

    # Only handle reactions created by a real user (not bots)
    sender_type = sender.get("type")
    if sender_type and sender_type != "User":
        return

    reaction_content = reaction.get("content", "")

    # The mini comment is identified by its body matching our signature header.
    # We extract the reviewer username from the comment body if present.
    comment_body = comment.get("body") or ""
    reviewer_login = _extract_mini_reviewer_from_comment(comment_body)
    if not reviewer_login:
        logger.debug("Reaction on non-mini comment; skipping outcome capture")
        return

    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    pr_number = pr.get("number")
    if not (owner and repo_name and pr_number):
        return

    mini = await get_mini(reviewer_login)
    if not mini:
        logger.debug("No mini found for %s; skipping reaction outcome capture", reviewer_login)
        return

    # Use issue-key-aware mapping and preserve all available issue keys for context.
    issue_keys = extract_issue_keys_from_text(comment_body)
    mapped_issue_key = map_signal_issue_key(parent_comment_body=comment_body)
    issue_key = mapped_issue_key or "unknown"

    disposition = build_disposition_map(
        comment_reactions=[reaction_content],
    )

    if disposition == "deferred":
        logger.debug(
            "Reaction '%s' on PR #%d mini comment yields no outcome signal; skipping",
            reaction_content,
            pr_number,
        )
        return

    trigger = f"reaction:{reaction_content}"

    context = _build_outcome_capture_context(
        event_type="reaction",
        actor_login=sender.get("login"),
        mini_reviewer_login=reviewer_login,
        target_comment_id=comment.get("id"),
        target_comment_url=comment.get("html_url") or comment.get("url"),
        thread_comment_id=comment.get("id"),
        thread_comment_url=comment.get("html_url") or comment.get("url"),
        issue_keys=issue_keys,
        mapped_issue_key=issue_key if issue_key != "unknown" else None,
        maps_to_predicted_suggestion=issue_key != "unknown",
        location={
            "path": comment.get("path"),
            "line": comment.get("line"),
            "position": comment.get("position"),
            "diff_hunk": comment.get("diff_hunk"),
        },
    )

    persisted = await record_comment_outcome(
        mini_id=mini["id"],
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        reviewer_login=reviewer_login,
        issue_key=issue_key,
        disposition=disposition,
        trigger=trigger,
        outcome_capture_context=context,
    )
    if persisted:
        logger.info(
            "Captured reaction outcome %s for PR #%d mini=%s key=%s",
            disposition,
            pr_number,
            reviewer_login,
            issue_key,
        )
    else:
        logger.warning(
            "Failed to persist reaction outcome for PR #%d mini=%s",
            pr_number,
            reviewer_login,
        )


async def handle_pr_review_thread_reply(payload: dict) -> None:
    """Handle pull_request_review_comment.created for outcome capture.

    When a human replies in a review thread started by a mini comment, classify
    the reply body and patch the review cycle with the inferred disposition.

    The feature flag ``GH_APP_OUTCOME_CAPTURE`` gates this handler.
    """
    import os

    if os.environ.get("GH_APP_OUTCOME_CAPTURE", "").strip().lower() not in {"true", "1", "yes"}:
        logger.debug("GH_APP_OUTCOME_CAPTURE disabled; skipping reply outcome capture")
        return

    comment = payload.get("comment") or {}
    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    sender = payload.get("sender") or {}

    # Only capture replies from real humans
    sender_type = sender.get("type")
    sender_login = sender.get("login", "")
    if sender_type and sender_type != "User":
        return

    reply_body = comment.get("body") or ""
    in_reply_to_id = comment.get("in_reply_to_id")
    if not in_reply_to_id:
        # Top-level review comment — not a reply; skip
        return

    # The parent comment id hints whether this is a reply to a mini comment.
    # We rely on the review thread context: the PR diff comment has a
    # ``pull_request_review_id`` we can use to cross-reference, but that
    # requires an extra API call. Instead, we check if the ``MENTION_PATTERN``
    # appears in the reply body referencing a mini, OR if the PR already has
    # a recorded cycle for any reviewer that is a mini.
    #
    # Conservative approach: if we can identify the mini reviewer via the
    # ``original_comment_body`` embedded in the payload (GitHub includes it for
    # review threads), use it. Otherwise skip.
    original_body = comment.get("original_body") or ""
    reviewer_login = _extract_mini_reviewer_from_comment(original_body)
    if not reviewer_login:
        logger.debug("Reply not in a mini-comment thread; skipping outcome capture")
        return

    # Guard: don't record the mini's own replies as outcomes
    if sender_login.lower() == reviewer_login.lower():
        return

    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    pr_number = pr.get("number")
    if not (owner and repo_name and pr_number):
        return

    mini = await get_mini(reviewer_login)
    if not mini:
        return

    issue_keys = extract_issue_keys_from_text(original_body)
    mapped_issue_key = map_signal_issue_key(
        parent_comment_body=original_body,
        signal_body=reply_body,
    )
    issue_key = mapped_issue_key or "unknown"
    disposition = build_disposition_map(reply_bodies=[reply_body])

    if disposition == "deferred":
        logger.debug(
            "Reply on PR #%d mini comment yields no outcome signal; skipping",
            pr_number,
        )
        return

    trigger = f"reply_body:{disposition}"
    context = _build_outcome_capture_context(
        event_type="reply",
        actor_login=sender.get("login"),
        mini_reviewer_login=reviewer_login,
        target_comment_id=in_reply_to_id,
        target_comment_url=comment.get("in_reply_to_url"),
        thread_comment_id=comment.get("id"),
        thread_comment_url=comment.get("html_url") or comment.get("url"),
        issue_keys=issue_keys,
        mapped_issue_key=issue_key if issue_key != "unknown" else None,
        maps_to_predicted_suggestion=issue_key != "unknown",
        location={
            "path": comment.get("path"),
            "line": comment.get("line"),
            "position": comment.get("position"),
            "diff_hunk": comment.get("diff_hunk"),
        },
    )

    persisted = await record_comment_outcome(
        mini_id=mini["id"],
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        reviewer_login=reviewer_login,
        issue_key=issue_key,
        disposition=disposition,
        trigger=trigger,
        outcome_capture_context=context,
    )
    if persisted:
        logger.info(
            "Captured reply outcome %s for PR #%d mini=%s key=%s",
            disposition,
            pr_number,
            reviewer_login,
            issue_key,
        )
    else:
        logger.warning(
            "Failed to persist reply outcome for PR #%d mini=%s",
            pr_number,
            reviewer_login,
        )


# ---------------------------------------------------------------------------
# Private helpers for outcome capture
# ---------------------------------------------------------------------------

# Matches "### Review by @username's mini" header in mini-posted comments
_MINI_REVIEW_HEADER_PATTERN = re.compile(
    r"###\s+Review\s+by\s+@([\w][\w-]*)'s\s+mini",
    re.IGNORECASE,
)


def _extract_mini_reviewer_from_comment(body: str) -> str | None:
    """Return the reviewer username if the comment was posted by a mini, else None."""
    match = _MINI_REVIEW_HEADER_PATTERN.search(body or "")
    return match.group(1) if match else None


def _build_outcome_capture_context(
    *,
    event_type: str,
    actor_login: str | None,
    mini_reviewer_login: str,
    target_comment_id: int | str | None,
    target_comment_url: str | None = None,
    thread_comment_id: int | str | None = None,
    thread_comment_url: str | None = None,
    parent_comment_url: str | None = None,
    issue_keys: list[str] | None = None,
    mapped_issue_key: str | None = None,
    maps_to_predicted_suggestion: bool = False,
    location: dict[str, str | int | None] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "event_type": event_type,
        "actor_login": actor_login,
        "mini_reviewer_login": mini_reviewer_login,
        "target_comment_id": target_comment_id,
        "target_comment_url": target_comment_url,
        "thread_comment_id": thread_comment_id,
        "thread_comment_url": thread_comment_url,
        "parent_comment_url": parent_comment_url,
        "issue_keys": issue_keys or [],
        "mapped_issue_key": mapped_issue_key,
        "maps_to_predicted_suggestion": maps_to_predicted_suggestion,
    }
    if location:
        context["location"] = location
    return context
