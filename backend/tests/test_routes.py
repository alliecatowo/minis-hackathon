"""Endpoint tests for all FastAPI routes.

Uses httpx.AsyncClient with ASGITransport so no real server is needed.
Database and auth dependencies are overridden to avoid real connections.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Auto-use fixture: clear the IP rate limit window before every test so the
# in-memory sliding window doesn't accumulate across the test suite.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_ip_rate_limit_windows():
    """Backward-compatible no-op for tests that used the old in-memory limiter."""
    import app.middleware.ip_rate_limit as _rl

    getattr(_rl, "_windows", {}).clear()
    yield
    getattr(_rl, "_windows", {}).clear()


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_user(username: str = "testuser") -> MagicMock:
    """Create a minimal mock User for dependency overrides."""
    user = MagicMock()
    user.id = str(uuid.uuid4())
    user.github_username = username
    user.display_name = username
    user.avatar_url = None
    return user


def _make_session() -> AsyncMock:
    """Create a minimal mock AsyncSession that returns empty results."""
    session = AsyncMock()
    # .execute(...) -> result with scalars().all() -> []
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalars.return_value.first.return_value = None
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


def _make_mini(**overrides) -> SimpleNamespace:
    """Create a minimal plain object that behaves like a loaded Mini row."""
    data = {
        "id": str(uuid.uuid4()),
        "username": "testuser",
        "display_name": "Test User",
        "avatar_url": None,
        "owner_id": None,
        "visibility": "public",
        "org_id": None,
        "bio": None,
        "spirit_content": None,
        "memory_content": None,
        "personality_typology_json": None,
        "behavioral_context_json": None,
        "motivations_json": None,
        "values_json": None,
        "roles_json": None,
        "skills_json": None,
        "traits_json": None,
        "metadata_json": None,
        "sources_used": None,
        "system_prompt": None,
        "status": "ready",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _make_review_cycle(**overrides) -> SimpleNamespace:
    data = {
        "id": str(uuid.uuid4()),
        "mini_id": str(uuid.uuid4()),
        "source_type": "github",
        "external_id": "repo:123:reviewer:sha",
        "metadata_json": {"repo_full_name": "acme/widgets", "pr_number": 123},
        "predicted_state": {
            "private_assessment": {
                "blocking_issues": [],
                "non_blocking_issues": [],
                "open_questions": [],
                "positive_signals": [],
                "confidence": 0.6,
            },
            "delivery_policy": {
                "author_model": "trusted_peer",
                "context": "normal",
                "strictness": "medium",
                "teaching_mode": True,
                "shield_author_from_noise": True,
            },
            "expressed_feedback": {
                "summary": "Looks reasonable.",
                "comments": [],
                "approval_state": "comment",
            },
        },
        "human_review_outcome": None,
        "delta_metrics": None,
        "predicted_at": "2024-01-01T00:00:00Z",
        "human_reviewed_at": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _make_prediction_feedback_memory(**overrides) -> SimpleNamespace:
    data = {
        "id": str(uuid.uuid4()),
        "mini_id": str(uuid.uuid4()),
        "cycle_type": "review_cycle",
        "cycle_id": str(uuid.uuid4()),
        "source_type": "github",
        "external_id": "repo:123:reviewer:sha",
        "feedback_kind": "issue_delta",
        "outcome_status": "accepted",
        "delta_type": "confirmed",
        "issue_key": "missing-tests",
        "predicted_private_assessment": {"summary": "Add tests."},
        "predicted_expressed_feedback": {"approval_state": "request_changes"},
        "actual_reviewer_behavior": {"approval_state": "request_changes"},
        "raw_outcome": {"expressed_feedback": {"approval_state": "request_changes"}},
        "delta": {"outcome": "confirmed", "outcome_status": "accepted"},
        "provenance": {"review_cycle_id": "cycle-1"},
        "created_at": "2024-01-01T00:00:00Z",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


async def _get_test_client(user=None, session=None):
    """Return an AsyncClient with optional dependency overrides applied."""
    from app.main import app
    from app.core.auth import get_current_user, get_optional_user
    from app.db import get_session

    overrides = {}
    if user is not None:
        overrides[get_current_user] = lambda: user
        overrides[get_optional_user] = lambda: user
    else:
        overrides[get_optional_user] = lambda: None

    if session is not None:
        overrides[get_session] = lambda: session

    app.dependency_overrides.update(overrides)
    return app


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health():
    """GET /api/health should return 200 with status=ok."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/health")

    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /api/minis — list public minis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_minis_returns_empty_list():
    """GET /api/minis should return a paginated envelope."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"data": [], "next_cursor": None, "has_more": False}


@pytest.mark.asyncio
async def test_list_minis_paginates_with_stable_cursor():
    """GET /api/minis applies limit+1 pagination and emits an opaque cursor."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    created_at = "2026-04-25T12:00:00Z"
    minis = [
        _make_mini(id="mini-c", username="charlie", created_at=created_at),
        _make_mini(id="mini-b", username="bravo", created_at=created_at),
        _make_mini(id="mini-a", username="alpha", created_at=created_at),
    ]

    session = _make_session()
    result = MagicMock()
    result.scalars.return_value.all.return_value = minis
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis?limit=2")

    app.dependency_overrides.clear()

    body = r.json()
    assert r.status_code == 200
    assert [mini["id"] for mini in body["data"]] == ["mini-c", "mini-b"]
    assert body["has_more"] is True
    assert isinstance(body["next_cursor"], str)


@pytest.mark.asyncio
async def test_list_minis_rejects_invalid_cursor():
    """GET /api/minis returns an explicit 400 for malformed pagination cursors."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis?cursor=not-a-valid-cursor")

    app.dependency_overrides.clear()

    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid cursor for minis list"


@pytest.mark.asyncio
async def test_list_minis_mine_requires_auth():
    """GET /api/minis?mine=true should return 401 when unauthenticated."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis?mine=true")

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_minis_openapi_documents_paginated_response():
    """OpenAPI documents the product API envelope for GET /api/minis."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/openapi.json")

    assert r.status_code == 200
    schema = r.json()["paths"]["/api/minis"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert schema["$ref"].endswith("/MiniListResponse")


# ---------------------------------------------------------------------------
# GET /api/minis/by-username/{username} — lookup by username
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mini_by_username_not_found():
    """GET /api/minis/by-username/nonexistent should return 404."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/by-username/nonexistent-user-xyz")

    app.dependency_overrides.clear()

    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_mini_by_username_public_lookup_omits_private_fields():
    """GET /api/minis/by-username/{username} should not leak system_prompt to anonymous callers."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(
        owner_id="owner-1",
        visibility="public",
        system_prompt="private prompt",
    )

    session = _make_session()
    result = MagicMock()
    result.scalars.return_value.first.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/by-username/testuser")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "testuser"
    assert "system_prompt" not in body


@pytest.mark.asyncio
async def test_get_mini_by_username_owner_lookup_still_returns_private_fields():
    """GET /api/minis/by-username/{username} should still return MiniDetail to the owner."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    user = _make_user("testuser")
    mini = _make_mini(
        owner_id=user.id,
        visibility="private",
        spirit_content="soul",
        memory_content="memory",
        system_prompt="private prompt",
    )

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/by-username/testuser")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "testuser"
    assert body["system_prompt"] == "private prompt"


@pytest.mark.asyncio
async def test_get_trusted_mini_by_username_requires_secret():
    """GET /api/minis/trusted/by-username/{username} should reject unauthenticated callers."""
    from app.main import app
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/trusted/by-username/testuser")

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_trusted_mini_by_username_rejects_wrong_secret():
    """GET /api/minis/trusted/by-username/{username} should reject the wrong service secret."""
    from app.main import app
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/minis/trusted/by-username/testuser",
            headers={"X-Trusted-Service-Secret": "wrong-secret"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_trusted_mini_by_username_returns_private_fields_with_secret():
    """GET /api/minis/trusted/by-username/{username} should return the private trusted payload."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    mini = _make_mini(
        owner_id="owner-1",
        visibility="private",
        system_prompt="private prompt",
    )

    session = _make_session()
    result = MagicMock()
    result.scalars.return_value.first.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/minis/trusted/by-username/testuser",
            headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "testuser"
    assert body["system_prompt"] == "private prompt"
    assert body["status"] == "ready"


@pytest.mark.asyncio
async def test_put_review_cycle_prediction_requires_secret():
    """PUT /api/minis/trusted/{mini_id}/review-cycles should reject missing secret."""
    from app.main import app

    mini_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.put(
            f"/api/minis/trusted/{mini_id}/review-cycles",
            json={
                "external_id": "repo:123:reviewer:sha",
                "predicted_state": {
                    "private_assessment": {},
                    "expressed_feedback": {},
                },
            },
        )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_put_trusted_review_cycle_prediction_rejects_browser_auth_without_secret():
    """A normal BFF-authenticated browser request must not become trusted-service access."""
    from app.main import app
    from app.core.auth import get_current_user

    mini_id = str(uuid.uuid4())
    user = _make_user("attacker")

    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.put(
            f"/api/minis/trusted/{mini_id}/review-cycles",
            json={
                "external_id": "repo:123:reviewer:sha",
                "source_type": "github",
                "predicted_state": {
                    "private_assessment": {},
                    "expressed_feedback": {},
                },
            },
        )

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_put_review_cycle_prediction_returns_record_with_secret():
    """PUT /api/minis/trusted/{mini_id}/review-cycles should return the stored record."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    cycle = _make_review_cycle(mini_id=mini_id)
    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routes.minis.upsert_review_cycle_prediction", AsyncMock(return_value=cycle))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put(
                f"/api/minis/trusted/{mini_id}/review-cycles",
                headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
                json={
                    "external_id": cycle.external_id,
                    "source_type": cycle.source_type,
                    "predicted_state": cycle.predicted_state,
                    "metadata_json": cycle.metadata_json,
                },
            )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["mini_id"] == mini_id
    assert body["external_id"] == cycle.external_id
    assert body["predicted_state"]["expressed_feedback"]["approval_state"] == "comment"


@pytest.mark.asyncio
async def test_put_owned_review_cycle_prediction_rejects_non_owner():
    """Browser review-cycle writes are owner-only and cannot target another user's mini."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    user = _make_user("attacker")
    mini = _make_mini(id=mini_id, owner_id=str(uuid.uuid4()), visibility="private")
    cycle = _make_review_cycle(mini_id=mini_id)

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with pytest.MonkeyPatch.context() as mp:
        upsert = AsyncMock()
        mp.setattr("app.routes.minis.upsert_review_cycle_prediction", upsert)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put(
                f"/api/minis/{mini_id}/review-cycles",
                json={
                    "external_id": cycle.external_id,
                    "source_type": cycle.source_type,
                    "predicted_state": cycle.predicted_state,
                    "metadata_json": cycle.metadata_json,
                },
            )

    app.dependency_overrides.clear()

    assert r.status_code == 403
    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_owned_review_cycle_prediction_allows_owner():
    """Owner-facing browser review-cycle writes use user ownership, not trusted-service secret."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    user = _make_user("owner")
    mini = _make_mini(id=mini_id, owner_id=user.id, visibility="private")
    cycle = _make_review_cycle(mini_id=mini_id)

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routes.minis.upsert_review_cycle_prediction", AsyncMock(return_value=cycle))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put(
                f"/api/minis/{mini_id}/review-cycles",
                json={
                    "external_id": cycle.external_id,
                    "source_type": cycle.source_type,
                    "predicted_state": cycle.predicted_state,
                    "metadata_json": cycle.metadata_json,
                },
            )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["mini_id"] == mini_id


@pytest.mark.asyncio
async def test_patch_review_cycle_outcome_returns_structured_outcome_capture():
    """PATCH /api/minis/trusted/{mini_id}/review-cycles should return stored outcome capture."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    cycle = _make_review_cycle(
        mini_id=mini_id,
        human_review_outcome={
            "private_assessment": {
                "blocking_issues": [],
                "non_blocking_issues": [],
                "open_questions": [],
                "positive_signals": [],
                "confidence": 0.6,
            },
            "delivery_policy": {
                "author_model": "trusted_peer",
                "context": "normal",
                "strictness": "medium",
                "teaching_mode": True,
                "shield_author_from_noise": True,
            },
            "expressed_feedback": {
                "summary": "",
                "comments": [],
                "approval_state": "comment",
            },
            "outcome_capture": {
                "artifact_outcome": "revised",
                "final_disposition": "commented",
                "reviewer_summary": "Ship with a short docs follow-up.",
                "suggestion_outcomes": [
                    {
                        "suggestion_key": "docs-note",
                        "outcome": "deferred",
                        "summary": "Docs can land after merge.",
                    }
                ],
            },
        },
        delta_metrics={
            "artifact_outcome": "revised",
            "final_disposition": "commented",
            "suggestion_outcomes": [
                {
                    "suggestion_key": "docs-note",
                    "outcome": "deferred",
                    "summary": "Docs can land after merge.",
                }
            ],
            "suggestion_outcome_counts": {"deferred": 1},
        },
        human_reviewed_at="2024-01-01T01:00:00Z",
    )
    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routes.minis.finalize_review_cycle", AsyncMock(return_value=cycle))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.patch(
                f"/api/minis/trusted/{mini_id}/review-cycles",
                headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
                json={
                    "external_id": cycle.external_id,
                    "source_type": cycle.source_type,
                    "human_review_outcome": cycle.human_review_outcome,
                    "delta_metrics": cycle.delta_metrics,
                },
            )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["human_review_outcome"]["outcome_capture"]["artifact_outcome"] == "revised"
    assert body["human_review_outcome"]["outcome_capture"]["reviewer_summary"] == (
        "Ship with a short docs follow-up."
    )
    assert body["delta_metrics"]["suggestion_outcomes"] == [
        {
            "suggestion_key": "docs-note",
            "outcome": "deferred",
            "summary": "Docs can land after merge.",
        }
    ]
    assert body["delta_metrics"]["suggestion_outcome_counts"] == {"deferred": 1}


@pytest.mark.asyncio
async def test_patch_review_cycle_outcome_returns_404_when_missing():
    """PATCH /api/minis/trusted/{mini_id}/review-cycles should 404 for an unknown cycle."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.routes.minis.finalize_review_cycle", AsyncMock(return_value=None))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.patch(
                f"/api/minis/trusted/{mini_id}/review-cycles",
                headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
                json={
                    "external_id": "repo:123:reviewer:sha",
                    "human_review_outcome": {
                        "private_assessment": {},
                        "expressed_feedback": {},
                    },
                    "delta_metrics": {"approval_state_changed": True},
                },
            )

    app.dependency_overrides.clear()

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_trusted_prediction_feedback_memories_returns_memory_records():
    """Trusted integrations can read first-class prediction feedback memories."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    memory = _make_prediction_feedback_memory(mini_id=mini_id)
    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    with pytest.MonkeyPatch.context() as mp:
        list_memories = AsyncMock(return_value=[memory])
        mp.setattr("app.routes.minis.list_prediction_feedback_memories", list_memories)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(
                f"/api/minis/trusted/{mini_id}/prediction-feedback-memories",
                headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
                params={"outcome_status": "accepted", "limit": 25},
            )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body[0]["mini_id"] == mini_id
    assert body[0]["outcome_status"] == "accepted"
    assert body[0]["delta"]["outcome"] == "confirmed"
    list_memories.assert_awaited_once()
    assert list_memories.await_args.kwargs["outcome_status"] == "accepted"
    assert list_memories.await_args.kwargs["limit"] == 25


@pytest.mark.asyncio
async def test_get_owned_prediction_feedback_memories_requires_owner():
    """Owner-facing memory reads use mini ownership, not trusted service auth."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    user = _make_user("owner")
    mini = _make_mini(id=mini_id, owner_id=user.id, visibility="private")
    memory = _make_prediction_feedback_memory(mini_id=mini_id)

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.routes.minis.list_prediction_feedback_memories",
            AsyncMock(return_value=[memory]),
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get(f"/api/minis/{mini_id}/prediction-feedback-memories")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()[0]["feedback_kind"] == "issue_delta"


# ---------------------------------------------------------------------------
# POST /api/minis — create mini (requires auth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_mini_requires_auth():
    """POST /api/minis without auth token should return 401."""
    from app.main import app

    # No override: get_current_user will raise 401
    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/minis", json={"username": "torvalds"})

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/minis/{id}/graph — knowledge graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mini_graph_not_found():
    """GET /api/minis/{id}/graph with unknown ID should return 404."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/does-not-exist-abc123/graph")

    app.dependency_overrides.clear()

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_graph_no_graph_returns_404():
    """GET /api/minis/{id}/graph when mini exists but has no graph should return 404."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = MagicMock()
    mini.id = str(uuid.uuid4())
    mini.username = "testuser"
    mini.visibility = "public"
    mini.owner_id = "owner-1"
    mini.knowledge_graph_json = None
    mini.principles_json = None

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/graph")

    app.dependency_overrides.clear()

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_graph_returns_data():
    """GET /api/minis/{id}/graph when graph exists should return 200 with graph data."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    mini = MagicMock()
    mini.id = mini_id
    mini.username = "testuser"
    mini.visibility = "public"
    mini.owner_id = "owner-1"
    mini.knowledge_graph_json = {"nodes": [{"id": "python", "type": "skill"}], "edges": []}
    mini.principles_json = {"principles": []}

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini_id}/graph")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["mini_id"] == mini_id
    assert "knowledge_graph" in body
    assert "principles" in body


# ---------------------------------------------------------------------------
# GET /api/settings — requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_requires_auth():
    """GET /api/settings without auth should return 401."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_settings_authenticated_no_settings():
    """GET /api/settings with auth and no stored settings returns default gemini settings."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["llm_provider"] == "gemini"
    assert body["has_api_key"] is False


# ---------------------------------------------------------------------------
# POST /api/auth/sync — requires X-Internal-Secret header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_sync_missing_secret_returns_401():
    """POST /api/auth/sync without X-Internal-Secret should return 401."""
    from app.main import app
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": "user-abc", "github_username": "testuser"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_sync_wrong_secret_returns_401():
    """POST /api/auth/sync with wrong X-Internal-Secret should return 401."""
    from app.main import app
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": "user-abc", "github_username": "testuser"},
            headers={"X-Internal-Secret": "definitely-wrong-secret"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_sync_correct_secret_upserts_user():
    """POST /api/auth/sync with correct X-Internal-Secret upserts user and returns user_id."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())
    user_mock = MagicMock()
    user_mock.id = user_id
    user_mock.github_username = "testuser"
    user_mock.display_name = "Test User"
    user_mock.avatar_url = None

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None  # New user
    session.execute = AsyncMock(return_value=result)

    # After refresh, user.id should be set — simulate by returning our mock on refresh
    async def _refresh(obj):
        obj.id = user_id

    session.refresh = AsyncMock(side_effect=_refresh)

    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": user_id, "github_username": "testuser"},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert "user_id" in body


# ---------------------------------------------------------------------------
# POST /api/auth/sync — github_username validator (ALLIE-379)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_sync_rejects_display_name_with_space():
    """POST /api/auth/sync must reject github_username containing whitespace (display name)."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": "user-xyz", "github_username": "Allison Coleman"},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_auth_sync_rejects_invalid_handle_characters():
    """POST /api/auth/sync must reject github_username that doesn't match GitHub handle pattern."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": "user-xyz", "github_username": "bad username!"},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_auth_sync_accepts_valid_handle():
    """POST /api/auth/sync must accept a well-formed GitHub login handle."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())
    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None  # New user

    async def _refresh(obj):
        obj.id = user_id

    session.execute = AsyncMock(return_value=result)
    session.refresh = AsyncMock(side_effect=_refresh)
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": user_id, "github_username": "alliecatowo"},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_sync_response_includes_github_username():
    """POST /api/auth/sync response must include github_username (ALLIE-383)."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())
    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None  # New user

    async def _refresh(obj):
        obj.id = user_id
        obj.github_username = "alliecatowo"

    session.execute = AsyncMock(return_value=result)
    session.refresh = AsyncMock(side_effect=_refresh)
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": user_id, "github_username": "alliecatowo"},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert "user_id" in body
    assert "github_username" in body, "SyncResponse must include github_username for BFF JWT claim"
    assert body["github_username"] == "alliecatowo"


@pytest.mark.asyncio
async def test_auth_sync_null_github_username_preserved():
    """POST /api/auth/sync with null github_username must not overwrite existing handle."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())

    # Existing user with a valid handle already in DB
    existing_user = MagicMock()
    existing_user.id = user_id
    existing_user.github_username = "alliecatowo"
    existing_user.display_name = "Allison Coleman"
    existing_user.avatar_url = "https://avatars.githubusercontent.com/u/12345"

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_user
    session.execute = AsyncMock(return_value=result)

    async def _refresh(obj):
        pass  # nothing extra needed

    session.refresh = AsyncMock(side_effect=_refresh)
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": user_id, "github_username": None},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    # The existing handle must not have been erased
    assert existing_user.github_username == "alliecatowo"


@pytest.mark.asyncio
async def test_auth_sync_keeps_display_name_separate_from_github_login():
    """POST /api/auth/sync stores provider login as github_username, not display_name."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())
    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={
                "neon_auth_id": user_id,
                "github_username": "octocat",
                "display_name": "Mona Lisa",
            },
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    created_user = session.add.call_args.args[0]
    assert created_user.github_username == "octocat"
    assert created_user.display_name == "Mona Lisa"


@pytest.mark.asyncio
async def test_auth_sync_missing_github_login_creates_unknown_username():
    """POST /api/auth/sync with missing login must not copy display_name into github_username."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())
    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={
                "neon_auth_id": user_id,
                "github_username": None,
                "display_name": "Display Name",
            },
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    created_user = session.add.call_args.args[0]
    assert created_user.github_username is None
    assert created_user.display_name == "Display Name"
    assert r.json()["github_username"] is None


@pytest.mark.asyncio
async def test_auth_sync_existing_profile_updates_display_without_erasing_login():
    """Existing profiles keep authoritative github_username when sync lacks provider login."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())
    existing_user = MagicMock()
    existing_user.id = user_id
    existing_user.github_username = "octocat"
    existing_user.display_name = "Old Display"
    existing_user.avatar_url = "https://avatars.githubusercontent.com/u/1?v=4"

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_user
    session.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={
                "neon_auth_id": user_id,
                "github_username": None,
                "display_name": "New Display",
                "avatar_url": "https://avatars.githubusercontent.com/u/1?v=5",
            },
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    assert existing_user.github_username == "octocat"
    assert existing_user.display_name == "New Display"
    assert existing_user.avatar_url == "https://avatars.githubusercontent.com/u/1?v=5"
    assert r.json()["github_username"] == "octocat"


# ---------------------------------------------------------------------------
# GET /api/minis/sources — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_no_auth():
    """GET /api/minis/sources should return a list (plugins may not be loaded in test env)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/sources")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # Each source entry should have id, name, available fields
    for source in body:
        assert "id" in source
        assert "name" in source
        assert "available" in source


# ---------------------------------------------------------------------------
# GET /api/settings/models — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_available_models_no_auth():
    """GET /api/settings/models should return model catalogue without auth."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings/models")

    assert r.status_code == 200
    body = r.json()
    assert "gemini" in body
    assert "openai" in body
    assert "anthropic" in body


# ---------------------------------------------------------------------------
# GET /api/settings/models/tiers — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tier_models_no_auth():
    """GET /api/settings/models/tiers should return tier model catalogue without auth."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings/models/tiers")

    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert "tiers" in body
    assert "defaults" in body


# ---------------------------------------------------------------------------
# GET /api/auth/me — requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_me_requires_auth():
    """GET /api/auth/me without auth should return 401."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/auth/me")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_authenticated():
    """GET /api/auth/me with auth should return user info."""
    from app.main import app
    from app.core.auth import get_current_user

    user = _make_user("octocat")

    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/auth/me")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["github_username"] == "octocat"
