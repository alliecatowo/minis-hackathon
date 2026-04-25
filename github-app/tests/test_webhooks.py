from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.webhooks import (
    handle_issue_comment,
    handle_pr_review_comment_reaction,
    handle_pr_review_thread_reply,
    handle_pull_request_opened,
    handle_pull_request_review,
)


@pytest.mark.asyncio
async def test_handle_pull_request_opened_records_prediction_after_posting_review():
    payload = {
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    prediction = {
        "version": "review_prediction_v1",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.8,
        },
        "delivery_policy": {
            "author_model": "trusted_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": True,
            "shield_author_from_noise": True,
            "rationale": "keep it focused",
        },
        "expressed_feedback": {
            "summary": "Looks good. One small concern.",
            "approval_state": "comment",
            "comments": [],
        },
    }

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch(
                    "app.webhooks.get_repo_collaborator_permission",
                    AsyncMock(return_value=None),
                ):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(return_value=prediction),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.render_review_prediction",
                                return_value="Looks good. One small concern.",
                            ):
                                with patch(
                                    "app.webhooks.post_pr_review",
                                    AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                                ) as post_review:
                                    with patch(
                                        "app.webhooks.record_review_prediction",
                                        AsyncMock(return_value=True),
                                    ) as record_prediction:
                                        await handle_pull_request_opened(payload)

    reviewers.assert_awaited_once_with(321, "octo-org", "hello-world", 7)
    get_prediction.assert_awaited_once_with(
        "mini-1",
        repo_name="octo-org/hello-world",
        pr_title="Refactor retry client",
        pr_body="This extracts retry policy handling.",
        diff="diff --git a/x b/x",
        changed_files=["app/retry.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )
    post_review.assert_awaited_once()
    record_prediction.assert_awaited_once()

    kwargs = record_prediction.await_args.kwargs
    assert kwargs["mini_id"] == "mini-1"
    assert kwargs["installation_id"] == 321
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 7
    assert kwargs["pr_title"] == "Refactor retry client"
    assert kwargs["pr_html_url"] == "https://github.com/octo-org/hello-world/pull/7"
    assert kwargs["reviewer_login"] == "allie"
    assert kwargs["prediction"] == prediction
    assert kwargs["github_review_id"] == 55
    assert kwargs["github_review_state"] == "COMMENTED"
    assert kwargs["author_login"] == "octo-dev"
    assert kwargs["author_association"] == "MEMBER"


@pytest.mark.asyncio
async def test_handle_pull_request_opened_infers_author_model_from_github_context():
    payload = {
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "FIRST_TIME_CONTRIBUTOR",
            "user": {"login": "new-contributor"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch(
                    "app.webhooks.get_repo_collaborator_permission",
                    AsyncMock(return_value=None),
                ):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(
                                return_value={
                                    "version": "review_prediction_v1",
                                    "private_assessment": {
                                        "blocking_issues": [],
                                        "non_blocking_issues": [],
                                        "open_questions": [],
                                        "positive_signals": [],
                                        "confidence": 0.8,
                                    },
                                    "delivery_policy": {
                                        "author_model": "junior_peer",
                                        "context": "normal",
                                        "strictness": "medium",
                                        "teaching_mode": True,
                                        "shield_author_from_noise": False,
                                        "rationale": "mapped from author association",
                                    },
                                    "expressed_feedback": {
                                        "summary": "Looks good. One small concern.",
                                        "approval_state": "comment",
                                        "comments": [],
                                    },
                                }
                            ),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.render_review_prediction",
                                return_value="Looks good. One small concern.",
                            ):
                                with patch(
                                    "app.webhooks.post_pr_review",
                                    AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                                ):
                                    with patch(
                                        "app.webhooks.record_review_prediction",
                                        AsyncMock(return_value=True),
                                    ):
                                        await handle_pull_request_opened(payload)

    assert get_prediction.await_args.kwargs["author_model"] == "junior_peer"


@pytest.mark.asyncio
async def test_handle_issue_comment_passes_inferred_author_model_to_mention_response():
    payload = {
        "comment": {"body": "@allie-mini can you take a look?"},
        "issue": {"number": 12, "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/12"}},
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch(
        "app.webhooks.get_pr_details",
        AsyncMock(
            return_value={
                "title": "Refactor retry client",
                "body": "This extracts retry policy handling.",
                "author_association": "COLLABORATOR",
                "user": {"login": "trusted-contributor"},
            }
        ),
    ):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.generate_mention_response",
                            AsyncMock(return_value="Looks good. One small concern."),
                        ) as generate_response:
                            with patch("app.webhooks.post_issue_comment", AsyncMock()):
                                await handle_issue_comment(payload)

    assert generate_response.await_args.kwargs["author_model"] == "trusted_peer"


@pytest.mark.asyncio
async def test_handle_issue_comment_review_request_posts_pr_review_and_records_prediction():
    payload = {
        "comment": {
            "body": "@allie-mini please review this PR",
            "html_url": "https://github.com/octo-org/hello-world/pull/12#issuecomment-1",
        },
        "issue": {
            "number": 12,
            "html_url": "https://github.com/octo-org/hello-world/pull/12",
            "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/12"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }
    prediction = {
        "version": "review_prediction_v1",
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "reviewer_username": "allie",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.8,
        },
        "delivery_policy": {
            "author_model": "trusted_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "explicit reviewer request",
        },
        "expressed_feedback": {
            "summary": "Would leave one focused review note.",
            "approval_state": "comment",
            "comments": [],
        },
    }

    with patch(
        "app.webhooks.get_pr_details",
        AsyncMock(
            return_value={
                "title": "Refactor retry client",
                "body": "This extracts retry policy handling.",
                "html_url": "https://github.com/octo-org/hello-world/pull/12",
                "author_association": "COLLABORATOR",
                "user": {"login": "trusted-contributor"},
            }
        ),
    ):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(return_value=prediction),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.post_pr_review",
                                AsyncMock(return_value={"id": 77, "state": "COMMENTED"}),
                            ) as post_review:
                                with patch(
                                    "app.webhooks.record_review_prediction",
                                    AsyncMock(return_value=True),
                                ) as record_prediction:
                                    with patch(
                                        "app.webhooks.generate_mention_response",
                                        AsyncMock(),
                                    ) as generate_response:
                                        with patch(
                                            "app.webhooks.post_issue_comment",
                                            AsyncMock(),
                                        ) as post_issue_comment:
                                            await handle_issue_comment(payload)

    get_prediction.assert_awaited_once_with(
        "mini-1",
        repo_name="octo-org/hello-world",
        pr_title="Refactor retry client",
        pr_body="This extracts retry policy handling.",
        diff="diff --git a/x b/x",
        changed_files=["app/retry.py"],
        author_model="trusted_peer",
        delivery_context="normal",
    )
    post_review.assert_awaited_once()
    body = post_review.await_args.kwargs["body"]
    assert "Reviewer mode: structured prediction for the requested reviewer." in body
    assert "**Predicted stance:** `comment`" in body
    generate_response.assert_not_awaited()
    post_issue_comment.assert_not_awaited()
    record_prediction.assert_awaited_once()

    kwargs = record_prediction.await_args.kwargs
    assert kwargs["mini_id"] == "mini-1"
    assert kwargs["installation_id"] == 321
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 12
    assert kwargs["pr_title"] == "Refactor retry client"
    assert kwargs["pr_html_url"] == "https://github.com/octo-org/hello-world/pull/12"
    assert kwargs["reviewer_login"] == "allie"
    assert kwargs["prediction"] == prediction
    assert kwargs["github_review_id"] == 77
    assert kwargs["github_review_state"] == "COMMENTED"
    assert kwargs["author_login"] == "trusted-contributor"
    assert kwargs["author_association"] == "COLLABORATOR"


@pytest.mark.asyncio
async def test_handle_pull_request_opened_uses_requested_reviewer_payload_on_review_requested():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock()) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(
                                return_value={
                                    "version": "review_prediction_v1",
                                    "delivery_policy": {"author_model": "senior_peer"},
                                    "expressed_feedback": {
                                        "summary": "Looks good.",
                                        "approval_state": "comment",
                                        "comments": [],
                                    },
                                }
                            ),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.render_review_prediction",
                                return_value="Looks good.",
                            ):
                                with patch(
                                    "app.webhooks.post_pr_review",
                                    AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                                ):
                                    with patch(
                                        "app.webhooks.record_review_prediction",
                                        AsyncMock(return_value=True),
                                    ):
                                        await handle_pull_request_opened(payload)

    reviewers.assert_not_awaited()
    assert get_prediction.await_args.kwargs["author_model"] == "senior_peer"


@pytest.mark.asyncio
async def test_handle_review_requested_posts_reviewer_mode_prediction_when_available():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }
    prediction = {
        "version": "review_prediction_v1",
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "reviewer_username": "allie",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.82,
        },
        "delivery_policy": {
            "author_model": "senior_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "reviewer mode",
        },
        "expressed_feedback": {
            "summary": "Would likely leave one focused note.",
            "approval_state": "comment",
            "comments": [],
        },
        "framework_signals": [
            {"name": "Prefer focused diffs", "confidence": 0.82, "revision_count": 2}
        ],
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock()) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch("app.webhooks.get_pr_changed_files", AsyncMock(return_value=["app/retry.py"])):
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(return_value=prediction),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.post_pr_review",
                                AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                            ) as post_review:
                                with patch(
                                    "app.webhooks.record_review_prediction",
                                    AsyncMock(return_value=True),
                                ):
                                    await handle_pull_request_opened(payload)

    reviewers.assert_not_awaited()
    get_prediction.assert_awaited_once()
    body = post_review.await_args.kwargs["body"]
    assert "Reviewer mode: structured prediction for the requested reviewer." in body
    assert "**Predicted stance:** `comment`" in body
    assert "Framework signals" in body
    assert "[confidence 82%]" in body


@pytest.mark.asyncio
async def test_handle_review_requested_posts_restrained_unavailable_message_when_gated():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }
    prediction = {
        "version": "review_prediction_v1",
        "prediction_available": False,
        "mode": "gated",
        "unavailable_reason": "mini is still synthesizing review frameworks",
        "reviewer_username": "allie",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.0,
        },
        "delivery_policy": {},
        "expressed_feedback": {
            "summary": "Review prediction unavailable.",
            "approval_state": "uncertain",
            "comments": [],
        },
    }

    with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
        with patch("app.webhooks.get_pr_changed_files", AsyncMock(return_value=["app/retry.py"])):
            with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                with patch(
                    "app.webhooks.get_mini",
                    AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                ):
                    with patch(
                        "app.webhooks.get_review_prediction",
                        AsyncMock(return_value=prediction),
                    ):
                        with patch(
                            "app.webhooks.post_pr_review",
                            AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                        ) as post_review:
                            with patch(
                                "app.webhooks.record_review_prediction",
                                AsyncMock(return_value=True),
                            ):
                                await handle_pull_request_opened(payload)

    body = post_review.await_args.kwargs["body"]
    assert "Review prediction unavailable" in body
    assert "Reviewer mode was requested for this PR" in body
    assert "**Mode:** `gated`" in body
    assert "Predicted stance" not in body


@pytest.mark.asyncio
async def test_handle_review_requested_skips_when_requested_reviewer_has_no_mini():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch("app.webhooks.get_mini", AsyncMock(return_value=None)) as get_mini_mock:
        with patch("app.webhooks.get_pr_diff", AsyncMock()) as get_diff:
            with patch("app.webhooks.get_pr_changed_files", AsyncMock()) as get_files:
                with patch("app.webhooks.get_review_prediction", AsyncMock()) as get_prediction:
                    with patch("app.webhooks.post_pr_review", AsyncMock()) as post_review:
                        await handle_pull_request_opened(payload)

    get_mini_mock.assert_awaited_once_with("allie")
    get_diff.assert_not_awaited()
    get_files.assert_not_awaited()
    get_prediction.assert_not_awaited()
    post_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pull_request_opened_uses_permission_hints_for_author_model():
    payload = {
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    permission_lookup = AsyncMock(side_effect=["read", "admin"])

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch("app.webhooks.get_repo_collaborator_permission", permission_lookup):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(
                                return_value={
                                    "version": "review_prediction_v1",
                                    "delivery_policy": {"author_model": "junior_peer"},
                                    "expressed_feedback": {
                                        "summary": "Needs follow-up.",
                                        "approval_state": "comment",
                                        "comments": [],
                                    },
                                }
                            ),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.render_review_prediction",
                                return_value="Needs follow-up.",
                            ):
                                with patch(
                                    "app.webhooks.post_pr_review",
                                    AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                                ):
                                    with patch(
                                        "app.webhooks.record_review_prediction",
                                        AsyncMock(return_value=True),
                                    ):
                                        await handle_pull_request_opened(payload)

    assert get_prediction.await_args.kwargs["author_model"] == "junior_peer"


@pytest.mark.asyncio
async def test_handle_pull_request_review_records_human_review_outcome():
    payload = {
        "action": "submitted",
        "review": {
            "id": 888,
            "state": "APPROVED",
            "body": "Looks good to me.",
            "user": {"login": "human-reviewer", "type": "User"},
        },
        "pull_request": {
            "number": 9,
            "title": "Fix backoff jitter",
            "html_url": "https://github.com/octo-org/hello-world/pull/9",
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-123", "username": "human-reviewer"}),
    ):
        with patch(
            "app.webhooks.record_human_review_outcome",
            AsyncMock(return_value=True),
        ) as record_human_review_outcome:
            await handle_pull_request_review(payload)

    record_human_review_outcome.assert_awaited_once()
    kwargs = record_human_review_outcome.await_args.kwargs
    assert kwargs["mini_id"] == "mini-123"
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 9
    assert kwargs["reviewer_login"] == "human-reviewer"
    assert kwargs["action"] == "submitted"
    assert kwargs["review"]["id"] == 888


@pytest.mark.asyncio
async def test_handle_pull_request_review_ignores_non_human_reviews():
    payload = {
        "action": "submitted",
        "review": {
            "id": 888,
            "state": "COMMENTED",
            "body": "",
            "user": {"login": "minis-pr-reviewer[bot]", "type": "Bot"},
        },
        "pull_request": {
            "number": 9,
            "title": "Fix backoff jitter",
            "html_url": "https://github.com/octo-org/hello-world/pull/9",
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
    }

    with patch(
        "app.webhooks.record_human_review_outcome",
        AsyncMock(return_value=True),
    ) as record_human_review_outcome:
        await handle_pull_request_review(payload)

    record_human_review_outcome.assert_not_awaited()


# ---------------------------------------------------------------------------
# Outcome-capture webhook handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_calls_trusted_endpoint(monkeypatch):
    """A thumbs-up reaction on a mini comment → PATCH review-cycles with confirmed."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    # Comment body that matches the mini review header pattern
    mini_comment_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `sec-1`: Please sanitize this input. Why: SQL injection risk."
    )

    payload = {
        "action": "created_reaction",
        "comment": {
            "id": 999,
            "body": mini_comment_body,
            "in_reply_to_id": None,
        },
        "reaction": {"content": "+1"},
        "pull_request": {"number": 42},
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    record_outcome.assert_awaited_once()
    kwargs = record_outcome.await_args.kwargs
    assert kwargs["mini_id"] == "mini-allie"
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 42
    assert kwargs["reviewer_login"] == "allie"
    assert kwargs["disposition"] == "confirmed"
    assert kwargs["trigger"] == "reaction:+1"
    assert kwargs["issue_key"] == "sec-1"


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_with_multi_comment_body_does_not_assume_first_key(monkeypatch):
    """Multi-key review bodies should not default to the first key for reaction events."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    multi_comment_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `sec-1`: Please sanitize input. Why: SQL injection risk.\n"
        "**Note** `style-2`: Consider renaming this variable."
    )
    payload = {
        "action": "created_reaction",
        "comment": {"id": 999, "body": multi_comment_body},
        "reaction": {"content": "+1"},
        "pull_request": {"number": 42},
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    record_outcome.assert_awaited_once()
    kwargs = record_outcome.await_args.kwargs
    assert kwargs["issue_key"] == "unknown"
    assert kwargs["outcome_capture_context"]["issue_keys"] == ["sec-1", "style-2"]


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_negative_reaction(monkeypatch):
    """A thumbs-down reaction → overpredicted disposition."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    mini_comment_body = (
        "### Review by @allie's mini\n\n"
        "**Note** `style-2`: Consider renaming this variable. Why: clarity."
    )
    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": mini_comment_body},
        "reaction": {"content": "-1"},
        "pull_request": {"number": 7},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "overpredicted"


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_deferred_not_recorded(monkeypatch):
    """A no-signal reaction (eyes) → deferred → trusted endpoint NOT called."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    mini_comment_body = "### Review by @allie's mini\n\n**Note** `perf-1`: Cache this."
    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": mini_comment_body},
        "reaction": {"content": "eyes"},
        "pull_request": {"number": 7},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    record_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_flag_off_skips(monkeypatch):
    """When GH_APP_OUTCOME_CAPTURE is off, the handler silently no-ops."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "false")

    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": "### Review by @allie's mini\n\n**Note** `x-1`: Foo."},
        "reaction": {"content": "+1"},
        "pull_request": {"number": 1},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch("app.webhooks.get_mini", AsyncMock()) as get_mini_mock:
        with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    get_mini_mock.assert_not_awaited()
    record_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_non_mini_comment_skips(monkeypatch):
    """Reactions on non-mini comments (no header) are silently ignored."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": "LGTM overall"},
        "reaction": {"content": "+1"},
        "pull_request": {"number": 1},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch("app.webhooks.get_mini", AsyncMock()) as get_mini_mock:
        with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    get_mini_mock.assert_not_awaited()
    record_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_confirmed(monkeypatch):
    """An agreeing reply in a mini-comment thread → confirmed disposition."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `null-2`: Add a null check here. Why: NPE risk."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 200,
            "body": "Good point, fixed!",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 15},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    record_outcome.assert_awaited_once()
    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "confirmed"
    assert kwargs["issue_key"] == "null-2"
    assert kwargs["reviewer_login"] == "allie"


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_maps_to_specific_issue_in_multi_comment_body(monkeypatch):
    """Reply quoting one issue in a multi-comment body maps to that specific key."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `sec-1`: Validate input length. Why: NPE risk.\n"
        "**Question** `auth-2`: Should we include retry count? Why: Observability."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 205,
            "body": "> **Question** `auth-2`: Should we include retry count?\n\nFixed.",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 16},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["issue_key"] == "auth-2"
    assert kwargs["outcome_capture_context"]["mapped_issue_key"] == "auth-2"
    assert kwargs["outcome_capture_context"]["issue_keys"] == ["sec-1", "auth-2"]


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_disagreement(monkeypatch):
    """A disagreeing reply → overpredicted disposition."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Note** `style-3`: Use a more descriptive name."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 201,
            "body": "I disagree — the name is clear in context.",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 15},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "overpredicted"


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_not_a_reply_skips(monkeypatch):
    """Top-level review comments (no in_reply_to_id) are not outcome-captured."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    payload = {
        "action": "created",
        "comment": {
            "id": 300,
            "body": "Looks good.",
            "in_reply_to_id": None,
        },
        "pull_request": {"number": 10},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
        await handle_pr_review_thread_reply(payload)

    record_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_flag_off_skips(monkeypatch):
    """Handler is gated by GH_APP_OUTCOME_CAPTURE flag."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "false")

    payload = {
        "action": "created",
        "comment": {"id": 400, "body": "Fixed!", "in_reply_to_id": 99, "original_body": ""},
        "pull_request": {"number": 10},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
        await handle_pr_review_thread_reply(payload)

    record_outcome.assert_not_awaited()
