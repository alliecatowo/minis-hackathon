from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.review import (
    _build_signal_index,
    _format_prediction_comment,
    _render_framework_footer,
    generate_mention_response,
    generate_review,
    get_mini,
    infer_author_model_from_github_context,
    render_review_prediction,
)


class _AsyncClientStub:
    def __init__(
        self,
        *,
        get_responses: list[httpx.Response] | None = None,
        post_responses: list[httpx.Response] | None = None,
    ):
        self._get_responses = list(get_responses or [])
        self._post_responses = list(post_responses or [])
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float,
    ):
        self.calls.append(
            {"method": "GET", "url": url, "headers": headers, "timeout": timeout}
        )
        return self._get_responses.pop(0)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict,
        timeout: float,
    ):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self._post_responses.pop(0)


def _response(method: str, url: str, *, status_code: int = 200, json: dict | None = None):
    return httpx.Response(
        status_code,
        request=httpx.Request(method, url),
        json=json,
    )


@pytest.mark.asyncio
async def test_get_mini_uses_trusted_lookup_path_and_header():
    stub = _AsyncClientStub(
        get_responses=[
            _response(
                "GET",
                f"{settings.minis_api_url}/api/minis/trusted/by-username/alliecatowo",
                json={
                    "id": "mini-123",
                    "username": "alliecatowo",
                    "display_name": "Allie",
                    "avatar_url": None,
                    "status": "ready",
                    "system_prompt": "be pragmatic",
                },
            )
        ]
    )

    with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
        with patch("app.review.httpx.AsyncClient", return_value=stub):
            mini = await get_mini("alliecatowo")

    assert mini is not None
    assert mini["system_prompt"] == "be pragmatic"
    assert stub.calls == [
        {
            "method": "GET",
            "url": f"{settings.minis_api_url}/api/minis/trusted/by-username/alliecatowo",
            "headers": {"X-Trusted-Service-Secret": "secret-for-tests"},
            "timeout": 10.0,
        }
    ]


@pytest.mark.asyncio
async def test_generate_review_calls_trusted_review_prediction_endpoint_and_formats_response():
    prediction = {
        "version": "review_prediction_v1",
        "reviewer_username": "alliecatowo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.7,
        },
        "delivery_policy": {
            "author_model": "unknown",
            "context": "hotfix",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": False,
            "rationale": "fallback defaults",
        },
        "expressed_feedback": {
            "summary": "Would likely request changes and surface the highest-severity concerns first.",
            "approval_state": "request_changes",
            "comments": [
                {
                    "type": "blocker",
                    "disposition": "request_changes",
                    "issue_key": "auth-boundary",
                    "summary": "Likely to scrutinize auth and permission boundaries before approving.",
                    "rationale": "Credentials changes are high-severity review territory.",
                }
            ],
        },
    }
    stub = _AsyncClientStub(
        post_responses=[
            _response(
                "POST",
                "https://backend.test/api/minis/trusted/mini-123/review-prediction",
                json=prediction,
            )
        ]
    )

    with patch.object(settings, "minis_api_url", "https://backend.test"):
        with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
            with patch("app.review.httpx.AsyncClient", return_value=stub):
                review_text = await generate_review(
                    mini={"id": "mini-123"},
                    repo_name="octo/repo",
                    pr_title="Hotfix auth boundary",
                    pr_body="Tightens token checks around webhook auth.",
                    diff="diff --git a/app/auth.py b/app/auth.py",
                    changed_files=["app/auth.py"],
                    delivery_context="hotfix",
                )

    assert "Predicted stance" in review_text
    assert "`request changes`" in review_text
    assert "auth-boundary" in review_text
    assert "Credentials changes are high-severity review territory." in review_text
    assert stub.calls == [
        {
            "method": "POST",
            "url": "https://backend.test/api/minis/trusted/mini-123/review-prediction",
            "headers": {"X-Trusted-Service-Secret": "secret-for-tests"},
            "json": {
                "repo_name": "octo/repo",
                "title": "Hotfix auth boundary",
                "description": "Tightens token checks around webhook auth.",
                "diff_summary": "diff --git a/app/auth.py b/app/auth.py",
                "changed_files": ["app/auth.py"],
                "author_model": "unknown",
                "delivery_context": "hotfix",
            },
            "timeout": 30.0,
        }
    ]


@pytest.mark.asyncio
async def test_generate_mention_response_labels_structured_prediction_for_non_review_prompt():
    prediction = {
        "version": "review_prediction_v1",
        "reviewer_username": "alliecatowo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.7,
        },
        "delivery_policy": {
            "author_model": "unknown",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": False,
            "rationale": "fallback defaults",
        },
        "expressed_feedback": {
            "summary": "Would likely leave a small set of comments without blocking the change.",
            "approval_state": "comment",
            "comments": [],
        },
    }
    stub = _AsyncClientStub(
        post_responses=[
            _response(
                "POST",
                "https://backend.test/api/minis/trusted/mini-123/review-prediction",
                json=prediction,
            )
        ]
    )

    with patch.object(settings, "minis_api_url", "https://backend.test"):
        with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
            with patch("app.review.httpx.AsyncClient", return_value=stub):
                review_text = await generate_mention_response(
                    mini={"id": "mini-123"},
                    user_message="@alliecatowo-mini what do you think about the auth layer?",
                    repo_name="octo/repo",
                    pr_title="Update auth flow",
                    pr_body="",
                    diff="diff --git a/app/auth.py b/app/auth.py",
                )

    assert "structured review prediction" in review_text.lower()
    assert "`comment`" in review_text


@pytest.mark.asyncio
async def test_get_mini_requires_trusted_service_secret_config():
    with patch.object(settings, "trusted_service_secret", "", create=True):
        mini = await get_mini("alliecatowo")

    assert mini is None


def test_infer_author_model_from_github_context_uses_author_association_mapping():
    assert infer_author_model_from_github_context(author_association="OWNER") == "senior_peer"
    assert (
        infer_author_model_from_github_context(author_association="collaborator")
        == "trusted_peer"
    )
    assert (
        infer_author_model_from_github_context(author_association="FIRST_TIME_CONTRIBUTOR")
        == "junior_peer"
    )
    assert infer_author_model_from_github_context(author_association="MANNEQUIN") == "unknown"


def test_infer_author_model_from_github_context_falls_back_to_repo_owner_match():
    assert (
        infer_author_model_from_github_context(
            author_association=None,
            author_login="octo-org",
            repo_owner_login="octo-org",
        )
        == "senior_peer"
    )


def test_infer_author_model_from_github_context_uses_permission_hints_relative_to_reviewer():
    assert (
        infer_author_model_from_github_context(
            author_association="MEMBER",
            author_login="octo-dev",
            repo_owner_login="octo-org",
            reviewer_login="allie",
            author_permission="read",
            reviewer_permission="admin",
        )
        == "junior_peer"
    )
    assert (
        infer_author_model_from_github_context(
            author_association="FIRST_TIME_CONTRIBUTOR",
            author_login="octo-dev",
            repo_owner_login="octo-org",
            reviewer_login="allie",
            author_permission="maintain",
            reviewer_permission="write",
        )
        == "senior_peer"
    )


def test_infer_author_model_from_github_context_handles_self_review_requests():
    assert (
        infer_author_model_from_github_context(
            author_association="MEMBER",
            author_login="allie",
            repo_owner_login="octo-org",
            reviewer_login="allie",
        )
        == "trusted_peer"
    )


# ---------------------------------------------------------------------------
# Framework-signal footer tests
# ---------------------------------------------------------------------------


def _base_prediction(framework_signals=None) -> dict:
    base = {
        "version": "review_prediction_v1",
        "reviewer_username": "alliecatowo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.7,
        },
        "delivery_policy": {
            "author_model": "unknown",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": False,
            "rationale": "defaults",
        },
        "expressed_feedback": {
            "summary": "Looks good overall.",
            "approval_state": "approve",
            "comments": [],
        },
    }
    if framework_signals is not None:
        base["framework_signals"] = framework_signals
    return base


def test_render_framework_footer_absent_when_no_signals():
    """Footer must be empty when prediction has no framework_signals field."""
    footer = _render_framework_footer(_base_prediction())
    assert footer == ""


def test_render_framework_footer_absent_when_signals_empty_list():
    footer = _render_framework_footer(_base_prediction(framework_signals=[]))
    assert footer == ""


def test_render_framework_footer_renders_high_confidence_badge():
    signals = [{"name": "Prefer explicit over implicit", "confidence": 0.85, "revision_count": 3}]
    footer = _render_framework_footer(_base_prediction(framework_signals=signals))
    assert "Framework signals" in footer
    assert "[HIGH CONFIDENCE ✓]" in footer
    assert "[validated 3 times]" in footer
    assert "Prefer explicit over implicit" in footer


def test_render_framework_footer_renders_low_confidence_badge():
    signals = [{"name": "Avoid premature abstraction", "confidence": 0.2, "revision_count": 0}]
    footer = _render_framework_footer(_base_prediction(framework_signals=signals))
    assert "[LOW CONFIDENCE ⚠]" in footer
    assert "Avoid premature abstraction" in footer


def test_render_framework_footer_no_badge_for_medium_confidence():
    signals = [{"name": "Write tests first", "confidence": 0.5, "revision_count": 1}]
    footer = _render_framework_footer(_base_prediction(framework_signals=signals))
    assert "[HIGH CONFIDENCE ✓]" not in footer
    assert "[LOW CONFIDENCE ⚠]" not in footer
    assert "[validated 1 time]" in footer
    assert "Write tests first" in footer


def test_render_framework_footer_caps_at_five():
    signals = [
        {"name": f"Framework {i}", "confidence": 0.9 - i * 0.1, "revision_count": i}
        for i in range(8)
    ]
    footer = _render_framework_footer(_base_prediction(framework_signals=signals))
    # Only 5 entries should be present — each line starts with "- **Framework"
    rendered_entries = [line for line in footer.splitlines() if line.startswith("- **Framework")]
    assert len(rendered_entries) == 5


def test_render_framework_footer_orders_by_confidence_descending():
    signals = [
        {"name": "Low one", "confidence": 0.2, "revision_count": 0},
        {"name": "High one", "confidence": 0.9, "revision_count": 2},
        {"name": "Mid one", "confidence": 0.55, "revision_count": 0},
    ]
    footer = _render_framework_footer(_base_prediction(framework_signals=signals))
    high_pos = footer.index("High one")
    mid_pos = footer.index("Mid one")
    low_pos = footer.index("Low one")
    assert high_pos < mid_pos < low_pos


def test_render_review_prediction_includes_footer_when_signals_present():
    signals = [{"name": "Keep PRs small", "confidence": 0.8, "revision_count": 5}]
    prediction = _base_prediction(framework_signals=signals)
    result = render_review_prediction(prediction)
    assert "Framework signals" in result
    assert "[HIGH CONFIDENCE ✓]" in result
    assert "[validated 5 times]" in result


def test_render_review_prediction_omits_footer_when_signals_absent():
    prediction = _base_prediction()
    result = render_review_prediction(prediction)
    assert "Framework signals" not in result


# ---------------------------------------------------------------------------
# framework_id attribution in expressed_feedback comment rendering
# ---------------------------------------------------------------------------


def _prediction_with_framework_signal(
    *,
    framework_id: str | None = None,
    revision: int | None = None,
) -> dict:
    """Build a prediction where the blocker signal carries framework attribution."""
    signal: dict = {
        "key": "test-coverage",
        "summary": "Tests required.",
        "rationale": "Untested path.",
        "confidence": 0.9,
    }
    if framework_id is not None:
        signal["framework_id"] = framework_id
    if revision is not None:
        signal["revision"] = revision

    return {
        "version": "review_prediction_v1",
        "reviewer_username": "alliecatowo",
        "private_assessment": {
            "blocking_issues": [signal],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.9,
        },
        "delivery_policy": {
            "author_model": "unknown",
            "context": "normal",
            "strictness": "high",
            "teaching_mode": False,
            "shield_author_from_noise": False,
            "rationale": "defaults",
        },
        "expressed_feedback": {
            "summary": "Needs tests before merge.",
            "approval_state": "request_changes",
            "comments": [
                {
                    "type": "blocker",
                    "disposition": "request_changes",
                    "issue_key": "test-coverage",
                    "summary": "Please add tests for the new path.",
                    "rationale": "Untested changes increase regression risk.",
                }
            ],
        },
    }


def test_format_prediction_comment_appends_framework_attribution_with_revision():
    comment = {
        "type": "blocker",
        "issue_key": "no-tests",
        "summary": "Add tests.",
        "rationale": "Untested.",
    }
    result = _format_prediction_comment(comment, framework_id="fw-require-tests", revision=3)
    assert "fw-require-tests" in result
    assert "validated 3×" in result


def test_format_prediction_comment_appends_framework_attribution_without_validated_when_revision_zero():
    comment = {
        "type": "blocker",
        "issue_key": "no-tests",
        "summary": "Add tests.",
        "rationale": "Untested.",
    }
    result = _format_prediction_comment(comment, framework_id="fw-require-tests", revision=0)
    assert "fw-require-tests" in result
    assert "validated" not in result


def test_format_prediction_comment_no_attribution_when_framework_id_absent():
    comment = {
        "type": "note",
        "issue_key": "style",
        "summary": "Minor style nit.",
        "rationale": "Consistency.",
    }
    result = _format_prediction_comment(comment)
    assert "from framework" not in result


def test_render_review_prediction_includes_framework_attribution_in_comment():
    """render_review_prediction pulls framework_id from signal index into comment body."""
    prediction = _prediction_with_framework_signal(framework_id="fw-always-test", revision=4)
    result = render_review_prediction(prediction)
    assert "fw-always-test" in result
    assert "validated 4×" in result


def test_render_review_prediction_no_framework_attribution_when_signal_has_no_framework_id():
    """render_review_prediction omits attribution when no framework_id on matching signal."""
    prediction = _prediction_with_framework_signal()
    result = render_review_prediction(prediction)
    assert "from framework" not in result


def test_build_signal_index_indexes_all_buckets():
    """_build_signal_index finds signals across all private_assessment lists."""
    prediction = {
        "private_assessment": {
            "blocking_issues": [{"key": "b1", "framework_id": "fw-b"}],
            "non_blocking_issues": [{"key": "nb1", "framework_id": "fw-nb"}],
            "open_questions": [{"key": "q1", "framework_id": "fw-q"}],
            "positive_signals": [{"key": "p1", "framework_id": "fw-p"}],
        }
    }
    index = _build_signal_index(prediction)
    assert index["b1"]["framework_id"] == "fw-b"
    assert index["nb1"]["framework_id"] == "fw-nb"
    assert index["q1"]["framework_id"] == "fw-q"
    assert index["p1"]["framework_id"] == "fw-p"


def test_build_signal_index_empty_when_no_assessment():
    index = _build_signal_index({})
    assert index == {}
