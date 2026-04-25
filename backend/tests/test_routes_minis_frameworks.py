"""Tests for frameworks-at-risk and retire-framework routes (ALLIE-519).

Covers:
- GET  /api/minis/{id}/frameworks-at-risk  — three reason shapes, owner-only auth
- POST /api/minis/{id}/frameworks/{framework_id}/retire  — flips the retired flag
- GET  /api/minis/by-username/{username}/decision-frameworks  — public route excludes retired
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirrors test_routes_extended.py helpers)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_ip_rate_limit_windows():
    import app.middleware.ip_rate_limit as _rl

    _rl._windows.clear()
    yield
    _rl._windows.clear()


def _make_user(username: str = "owner", user_id: str | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or str(uuid.uuid4())
    u.github_username = username
    u.display_name = username.title()
    u.avatar_url = None
    return u


def _make_session() -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalars.return_value.first.return_value = None
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = 0
    result.one_or_none.return_value = None
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    return session


def _make_result_with(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = []
    result.scalars.return_value.first.return_value = None
    result.scalar_one.return_value = 0
    result.one_or_none.return_value = None
    result.all.return_value = []
    return result


def _make_mini(
    mini_id: str | None = None,
    username: str = "testuser",
    owner_id: str | None = None,
    principles_json: dict | None = None,
    created_at: datetime.datetime | None = None,
) -> MagicMock:
    mini = MagicMock(
        spec_set=[
            "id",
            "username",
            "owner_id",
            "status",
            "visibility",
            "system_prompt",
            "spirit_content",
            "memory_content",
            "knowledge_graph_json",
            "principles_json",
            "display_name",
            "avatar_url",
            "evidence_cache",
            "created_at",
            "updated_at",
            "org_id",
            "bio",
            "values_json",
            "roles_json",
            "skills_json",
            "traits_json",
            "metadata_json",
            "sources_used",
        ]
    )
    mini.id = mini_id or str(uuid.uuid4())
    mini.username = username
    mini.owner_id = owner_id or str(uuid.uuid4())
    mini.status = "ready"
    mini.visibility = "public"
    mini.system_prompt = "You are a test mini."
    mini.spirit_content = "Soul doc."
    mini.memory_content = "Memory."
    mini.knowledge_graph_json = None
    mini.principles_json = principles_json
    mini.display_name = username
    mini.avatar_url = None
    mini.evidence_cache = None
    mini.created_at = created_at or datetime.datetime(
        2024, 1, 1, tzinfo=datetime.timezone.utc
    )
    mini.updated_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    mini.org_id = None
    mini.bio = None
    mini.values_json = None
    mini.roles_json = None
    mini.skills_json = None
    mini.traits_json = None
    mini.metadata_json = None
    mini.sources_used = None
    return mini


# ---------------------------------------------------------------------------
# Shared decision-frameworks payload builders
# ---------------------------------------------------------------------------


def _framework(
    framework_id: str = "framework:test",
    condition: str = "When code review is needed",
    confidence: float = 0.5,
    revision: int = 0,
    confidence_history: list | None = None,
    retired: bool = False,
) -> dict:
    return {
        "framework_id": framework_id,
        "condition": condition,
        "action": "Review thoroughly",
        "confidence": confidence,
        "revision": revision,
        "confidence_history": confidence_history or [],
        "priority": "medium",
        "tradeoff": "Quality over speed",
        "escalation_threshold": "Block if critical.",
        "counterexamples": [],
        "temporal_span": {},
        "evidence_ids": [],
        "evidence_provenance": [],
        "counter_evidence_ids": [],
        "specificity_level": "case_pattern",
        "value_ids": ["value:quality"],
        "motivation_ids": [],
        "decision_order": ["Review thoroughly"],
        "approval_policy": None,
        "block_policy": None,
        "expression_policy": None,
        "exceptions": [],
        "source_type": None,
        "version": "framework-model-v1",
        "retired": retired,
    }


def _principles_json(frameworks: list[dict]) -> dict:
    return {
        "principles": [],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": frameworks,
            "source": "principles_motivations_normalizer",
        },
    }


# ===========================================================================
# GET /api/minis/{id}/frameworks-at-risk
# ===========================================================================


@pytest.mark.asyncio
async def test_frameworks_at_risk_low_band():
    """low_band reason surfaced for confidence < 0.3."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    owner = _make_user()
    fw = _framework(framework_id="framework:low", confidence=0.15, revision=2)
    mini = _make_mini(owner_id=owner.id, principles_json=_principles_json([fw]))

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/frameworks-at-risk")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["reason"] == "low_band"
    assert data[0]["framework_id"] == "framework:low"
    assert data[0]["confidence"] == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_frameworks_at_risk_declining_trend():
    """declining_trend reason surfaced for 3+ consecutive negative deltas."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    owner = _make_user()
    history = [
        {"revision": 1, "prior_confidence": 0.5, "new_confidence": 0.45, "delta": -0.05,
         "outcome_type": "missed", "issue_key": "k1", "cycle_id": "c1", "applied_at": "2024-01-01T00:00:00Z"},
        {"revision": 2, "prior_confidence": 0.45, "new_confidence": 0.40, "delta": -0.05,
         "outcome_type": "missed", "issue_key": "k2", "cycle_id": "c2", "applied_at": "2024-01-02T00:00:00Z"},
        {"revision": 3, "prior_confidence": 0.40, "new_confidence": 0.35, "delta": -0.05,
         "outcome_type": "missed", "issue_key": "k3", "cycle_id": "c3", "applied_at": "2024-01-03T00:00:00Z"},
    ]
    fw = _framework(
        framework_id="framework:declining",
        confidence=0.35,
        revision=3,
        confidence_history=history,
    )
    mini = _make_mini(owner_id=owner.id, principles_json=_principles_json([fw]))

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/frameworks-at-risk")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert any(f["reason"] == "declining_trend" for f in data)
    declining = next(f for f in data if f["reason"] == "declining_trend")
    assert declining["trend_summary"] is not None
    assert "↘" in declining["trend_summary"]


@pytest.mark.asyncio
async def test_frameworks_at_risk_low_evidence():
    """low_evidence reason surfaced for revision=0 on an old mini."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    owner = _make_user()
    fw = _framework(framework_id="framework:old", confidence=0.55, revision=0)
    old_date = datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
    mini = _make_mini(owner_id=owner.id, principles_json=_principles_json([fw]), created_at=old_date)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/frameworks-at-risk")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert any(f["reason"] == "low_evidence" for f in data)


@pytest.mark.asyncio
async def test_frameworks_at_risk_healthy_framework_not_included():
    """A healthy framework (high confidence, revisions, no declining trend) is NOT at risk."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    owner = _make_user()
    fw = _framework(framework_id="framework:healthy", confidence=0.85, revision=3)
    recent_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)
    mini = _make_mini(
        owner_id=owner.id,
        principles_json=_principles_json([fw]),
        created_at=recent_date,
    )

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/frameworks-at-risk")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert not any(f["framework_id"] == "framework:healthy" for f in data)


@pytest.mark.asyncio
async def test_frameworks_at_risk_requires_auth():
    """GET /{id}/frameworks-at-risk returns 401 when unauthenticated."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    from fastapi import HTTPException

    async def _raise_401():
        raise HTTPException(status_code=401, detail="Authentication required")

    session = _make_session()
    app.dependency_overrides[get_current_user] = _raise_401
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/some-id/frameworks-at-risk")

    app.dependency_overrides.clear()
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_frameworks_at_risk_non_owner_returns_403():
    """GET /{id}/frameworks-at-risk returns 403 when caller is not the owner."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    other_user = _make_user("other")
    mini = _make_mini(owner_id=str(uuid.uuid4()))  # different owner

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: other_user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/frameworks-at-risk")

    app.dependency_overrides.clear()
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_frameworks_at_risk_empty_when_no_principles():
    """Returns empty list when mini has no principles_json."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    owner = _make_user()
    mini = _make_mini(owner_id=owner.id, principles_json=None)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/frameworks-at-risk")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


# ===========================================================================
# POST /api/minis/{id}/frameworks/{framework_id}/retire
# ===========================================================================


@pytest.mark.asyncio
async def test_retire_framework_sets_flag():
    """Retire route flips the retired flag and persists it."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    owner = _make_user()
    fid = "framework:retire-me"
    fw = _framework(framework_id=fid, confidence=0.15)
    p_json = _principles_json([fw])

    # Use a plain object so attribute assignment works
    class SimpleMini:
        def __init__(self, mini_id, owner_id, principles_json):
            self.id = mini_id
            self.owner_id = owner_id
            self.principles_json = principles_json

    simple_mini = SimpleMini(str(uuid.uuid4()), owner.id, p_json)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(simple_mini))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/minis/{simple_mini.id}/frameworks/{fid}/retire")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["framework_id"] == fid
    assert body["retired"] is True


@pytest.mark.asyncio
async def test_retire_framework_not_found_returns_404():
    """Retire route returns 404 when framework_id does not exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    owner = _make_user()
    fw = _framework(framework_id="framework:exists")
    mini = _make_mini(owner_id=owner.id, principles_json=_principles_json([fw]))

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/minis/{mini.id}/frameworks/framework:does-not-exist/retire")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_retire_framework_non_owner_returns_403():
    """Retire route returns 403 for non-owner callers."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    other_user = _make_user("other")
    fw = _framework(framework_id="framework:x")
    mini = _make_mini(owner_id=str(uuid.uuid4()), principles_json=_principles_json([fw]))

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))
    app.dependency_overrides[get_current_user] = lambda: other_user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/minis/{mini.id}/frameworks/framework:x/retire")

    app.dependency_overrides.clear()
    assert r.status_code == 403


# ===========================================================================
# GET /api/minis/by-username/{username}/decision-frameworks
# ===========================================================================


@pytest.mark.asyncio
async def test_decision_frameworks_by_username_excludes_retired():
    """Public decision-frameworks route excludes retired entries."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    active_fw = _framework(framework_id="framework:active", confidence=0.8)
    retired_fw = _framework(framework_id="framework:retired", confidence=0.5, retired=True)
    p_json = _principles_json([active_fw, retired_fw])
    mini = _make_mini(principles_json=p_json)

    # When user is None, route skips owner lookup and goes straight to public
    # lookup via scalars().first()
    result_with_mini = MagicMock()
    result_with_mini.scalars.return_value.first.return_value = mini
    result_with_mini.scalar_one_or_none.return_value = None

    session = _make_session()
    session.execute = AsyncMock(return_value=result_with_mini)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/by-username/{mini.username}/decision-frameworks")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    fwids = [f["framework_id"] for f in body.get("frameworks", [])]
    assert "framework:active" in fwids
    assert "framework:retired" not in fwids


@pytest.mark.asyncio
async def test_decision_frameworks_by_username_not_found():
    """Returns 404 when mini does not exist."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    result_first_none = MagicMock()
    result_first_none.scalars.return_value.first.return_value = None
    result_first_none.scalar_one_or_none.return_value = None

    session = _make_session()
    session.execute = AsyncMock(return_value=result_first_none)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/by-username/nobody/decision-frameworks")

    app.dependency_overrides.clear()
    assert r.status_code == 404
