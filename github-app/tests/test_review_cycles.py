from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.review_cycles import (
    record_human_review_outcome,
    record_review_prediction,
)


class _AsyncClientStub:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict | None = None,
        timeout: float,
    ):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self._response


@pytest.mark.asyncio
async def test_record_review_prediction_uses_reconciled_review_cycle_endpoint():
    stub = _AsyncClientStub(
        httpx.Response(
            200,
            request=httpx.Request(
                "PUT",
                f"{settings.minis_api_url}/api/minis/trusted/mini-123/review-cycles",
            ),
            json={"ok": True},
        )
    )

    prediction = {
        "version": "review_prediction_v1",
        "private_assessment": {
            "blocking_issues": [{"issue_key": "missing-tests"}],
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
            "rationale": "keep focus on the high-signal issue",
        },
        "expressed_feedback": {
            "summary": "Please add tests.",
            "approval_state": "request_changes",
            "comments": [],
        },
    }

    with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
        with patch("app.review_cycles.httpx.AsyncClient", return_value=stub):
            result = await record_review_prediction(
                mini_id="mini-123",
                installation_id=99,
                owner="octo-org",
                repo="hello-world",
                pr_number=42,
                pr_title="Tighten retry behavior",
                pr_html_url="https://github.com/octo-org/hello-world/pull/42",
                reviewer_login="alliecatowo",
                prediction=prediction,
                github_review_id=12345,
                github_review_state="COMMENTED",
                author_login="octo-dev",
                author_association="MEMBER",
            )

    assert result is True
    assert len(stub.calls) == 1

    call = stub.calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == f"{settings.minis_api_url}/api/minis/trusted/mini-123/review-cycles"
    assert call["headers"] == {"X-Trusted-Service-Secret": "secret-for-tests"}
    assert call["timeout"] == 10.0
    assert call["json"]["external_id"] == "octo-org/hello-world#42:alliecatowo"
    assert call["json"]["predicted_state"]["expressed_feedback"]["approval_state"] == "request_changes"
    assert call["json"]["metadata_json"]["review_prediction_version"] == "review_prediction_v1"
    assert call["json"]["metadata_json"]["github_review_id"] == 12345
    assert call["json"]["metadata_json"]["author_login"] == "octo-dev"
    assert call["json"]["metadata_json"]["author_association"] == "MEMBER"


@pytest.mark.asyncio
async def test_record_human_review_outcome_uses_reconciled_review_cycle_endpoint():
    stub = _AsyncClientStub(
        httpx.Response(
            200,
            request=httpx.Request(
                "PATCH",
                f"{settings.minis_api_url}/api/minis/trusted/mini-123/review-cycles",
            ),
            json={"ok": True},
        )
    )

    with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
        with patch("app.review_cycles.httpx.AsyncClient", return_value=stub):
            result = await record_human_review_outcome(
                mini_id="mini-123",
                owner="octo-org",
                repo="hello-world",
                pr_number=42,
                reviewer_login="human-reviewer",
                action="submitted",
                review={
                    "id": 987,
                    "state": "CHANGES_REQUESTED",
                    "body": (
                        "- **Blocker** `auth-boundary`: Please separate transport retries "
                        "from auth retries. Why: These failures have different rollback paths.\n"
                        "- **Note** `retry-coverage`: Add regression coverage for the retry split."
                    ),
                },
            )

    assert result is True
    assert len(stub.calls) == 1

    call = stub.calls[0]
    assert call["method"] == "PATCH"
    assert call["url"] == f"{settings.minis_api_url}/api/minis/trusted/mini-123/review-cycles"
    assert call["headers"] == {"X-Trusted-Service-Secret": "secret-for-tests"}
    assert call["json"]["external_id"] == "octo-org/hello-world#42:human-reviewer"
    assert call["json"]["human_review_outcome"]["expressed_feedback"]["approval_state"] == (
        "request_changes"
    )
    assert call["json"]["human_review_outcome"]["expressed_feedback"]["comments"] == [
        {
            "type": "blocker",
            "disposition": "request_changes",
            "issue_key": "auth-boundary",
            "summary": "Please separate transport retries from auth retries.",
            "rationale": "These failures have different rollback paths.",
        },
        {
            "type": "note",
            "disposition": "comment",
            "issue_key": "retry-coverage",
            "summary": "Add regression coverage for the retry split.",
            "rationale": "",
        },
    ]
    assert call["json"]["delta_metrics"] == {
        "github_review_action": "submitted",
        "github_review_id": 987,
        "github_review_state": "CHANGES_REQUESTED",
    }
