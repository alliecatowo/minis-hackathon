from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _session_with_mini(mini, review_cycles=None):
    session = AsyncMock()
    mini_result = MagicMock()
    mini_result.scalar_one_or_none.return_value = mini
    cycles_result = MagicMock()
    cycles_result.scalars.return_value = review_cycles or []
    call_count = {"value": 0}

    async def _execute(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return mini_result
        return cycles_result

    session.execute = AsyncMock(side_effect=_execute)
    return session


def _mini(**overrides) -> SimpleNamespace:
    data = {
        "id": "mini-123",
        "username": "reviewer",
        "display_name": "Reviewer",
        "avatar_url": None,
        "owner_id": "owner-1",
        "visibility": "public",
        "org_id": None,
        "bio": None,
        "spirit_content": None,
        "memory_content": "Pushes for tests and rollback plans in code review.",
        "personality_typology_json": None,
        "behavioral_context_json": {
            "summary": "Direct in code review.",
            "contexts": [
                {
                    "context": "code_review",
                    "summary": "Flags missing tests and unclear rollout plans.",
                    "behaviors": ["asks for tests", "asks for rollout safety"],
                }
            ],
        },
        "motivations_json": {
            "motivations": [],
            "motivation_chains": [],
            "summary": "Values code quality.",
        },
        "values_json": {
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 8.0},
                {"name": "Directness", "description": "", "intensity": 7.0},
                {"name": "Pragmatism", "description": "", "intensity": 5.0},
            ]
        },
        "roles_json": None,
        "skills_json": None,
        "traits_json": None,
        "metadata_json": None,
        "sources_used": None,
        "system_prompt": None,
        "evidence_cache": "review: add tests before merge",
        "principles_json": {
            "decision_frameworks": {
                "version": "decision_frameworks_v1",
                "frameworks": [
                    {
                        "framework_id": "fw-tests",
                        "condition": "risky backend changes lack tests",
                        "priority": "high",
                        "tradeoff": "coverage vs speed",
                        "escalation_threshold": "high",
                        "counterexamples": [],
                        "evidence_ids": ["ev-framework-tests-1"],
                        "evidence_provenance": [
                            {
                                "id": "prov-tests-1",
                                "source_type": "review",
                                "item_type": "comment",
                            }
                        ],
                        "counter_evidence_ids": [],
                        "confidence": 0.9,
                        "specificity_level": "global",
                        "value_ids": ["quality"],
                        "motivation_ids": ["craftsmanship"],
                        "decision_order": ["if risky path", "require tests"],
                        "revision": 2,
                    }
                ],
            }
        },
        "status": "ready",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _stub_review_agent(monkeypatch):
    from app.core import review_predictor_agent

    monkeypatch.setattr(
        review_predictor_agent,
        "run_agent",
        AsyncMock(return_value=SimpleNamespace(final_response=None)),
    )


@pytest.mark.asyncio
async def test_review_prediction_endpoint_returns_structured_payload(app, monkeypatch):
    from app.core.auth import get_optional_user
    from app.db import get_session

    _stub_review_agent(monkeypatch)
    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/review-prediction",
            json={
                "title": "Update auth flow",
                "description": "Touches token validation and queue retries.",
                "changed_files": ["backend/app/auth.py"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "review_prediction_v1"
    assert body["reviewer_username"] == "reviewer"
    assert body["artifact_summary"] == {
        "artifact_type": "pull_request",
        "title": "Update auth flow",
    }
    assert body["prediction_available"] is False
    assert body["mode"] == "gated"
    assert "LLM review predictor returned no response" in body["unavailable_reason"]
    assert body["private_assessment"]["blocking_issues"] == []
    assert body["expressed_feedback"]["comments"] == []
    assert body["expressed_feedback"]["approval_state"] == "uncertain"


@pytest.mark.asyncio
async def test_trusted_review_prediction_endpoint_allows_private_minis(app, monkeypatch):
    from app.core.config import settings
    from app.db import get_session

    _stub_review_agent(monkeypatch)
    mini = _mini(visibility="private", owner_id="someone-else")
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/trusted/{mini.id}/review-prediction",
            headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
            json={"title": "Update auth flow"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["reviewer_username"] == "reviewer"
    assert body["prediction_available"] is False


@pytest.mark.asyncio
async def test_review_prediction_endpoint_respects_private_access(app, mock_user):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini(visibility="private", owner_id="someone-else")
    app.dependency_overrides[get_optional_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/review-prediction",
            json={"title": "Update auth flow"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_prediction_endpoint_infers_delivery_context_from_request(app, monkeypatch):
    from app.core.auth import get_optional_user
    from app.db import get_session

    _stub_review_agent(monkeypatch)
    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/review-prediction",
            json={
                "title": "WIP prototype for ingestion retries",
                "description": "Draft experiment to explore queue semantics before hardening them.",
                "changed_files": ["backend/app/ingestion/github.py"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["prediction_available"] is False
    assert body["private_assessment"]["blocking_issues"] == []
    assert body["expressed_feedback"]["comments"] == []
    assert body["delivery_policy"]["context"] == "exploratory"


@pytest.mark.asyncio
async def test_artifact_review_endpoint_accepts_design_docs(app, monkeypatch):
    from app.core.auth import get_optional_user
    from app.db import get_session

    _stub_review_agent(monkeypatch)
    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/artifact-review",
            json={
                "artifact_type": "design_doc",
                "title": "Design doc for retry isolation",
                "artifact_summary": "Proposes queue retry isolation, rollback notes, and validation follow-up.",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "artifact_review_v1"
    assert body["artifact_summary"] == {
        "artifact_type": "design_doc",
        "title": "Design doc for retry isolation",
    }
    assert "merge" not in body["expressed_feedback"]["summary"].lower()


@pytest.mark.asyncio
async def test_trusted_artifact_review_endpoint_accepts_issue_plans(app, monkeypatch):
    from app.core.config import settings
    from app.db import get_session

    _stub_review_agent(monkeypatch)
    mini = _mini(visibility="private", owner_id="someone-else")
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/trusted/{mini.id}/artifact-review",
            headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
            json={
                "artifact_type": "issue_plan",
                "title": "Issue plan for retry hardening",
                "artifact_summary": "Plans auth boundary checks, tests, and rollback notes.",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "artifact_review_v1"
    assert body["artifact_summary"]["artifact_type"] == "issue_plan"


@pytest.mark.asyncio
async def test_artifact_review_endpoint_rejects_pull_requests(app, monkeypatch):
    from app.core.auth import get_optional_user
    from app.db import get_session

    _stub_review_agent(monkeypatch)
    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/artifact-review",
            json={
                "artifact_type": "pull_request",
                "title": "Update auth flow",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_review_prediction_endpoint_rejects_non_pr_artifacts(app, monkeypatch):
    from app.core.auth import get_optional_user
    from app.db import get_session

    _stub_review_agent(monkeypatch)
    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/review-prediction",
            json={
                "artifact_type": "design_doc",
                "title": "Design doc for retry isolation",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_advisor_endpoint_returns_framework_backed_artifact(app):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/patch-advisor",
            json={
                "title": "Update auth flow",
                "description": "Touches token validation and queue retries.",
                "changed_files": ["backend/app/auth.py"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "patch_advisor_v1"
    assert body["advice_available"] is True
    assert body["mode"] == "framework"
    assert body["change_plan"]
    assert body["do_not_change"]
    assert body["risks"]
    assert body["expected_reviewer_objections"]
    assert body["evidence_references"][0]["framework_id"] == "fw-tests"
    assert body["evidence_references"][0]["evidence_ids"] == ["ev-framework-tests-1"]
    assert body["review_prediction"]["version"] == "review_prediction_v1"


@pytest.mark.asyncio
async def test_patch_advisor_endpoint_gates_without_decision_frameworks(app):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini(principles_json=None)
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/patch-advisor",
            json={
                "title": "Update auth flow",
                "description": "Touches token validation and queue retries.",
                "changed_files": ["backend/app/auth.py"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "patch_advisor_v1"
    assert body["advice_available"] is False
    assert body["mode"] == "gated"
    assert "No decision-framework evidence" in body["unavailable_reason"]
    assert body["change_plan"] == []
    assert body["evidence_references"] == []
    assert body["review_prediction"] is None
