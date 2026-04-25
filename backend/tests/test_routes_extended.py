"""Extended endpoint tests for all FastAPI routes.

Covers: chat, minis (CRUD), conversations, teams, orgs, settings, export,
upload, usage, and team_chat routes.

Uses httpx.AsyncClient with ASGITransport — no real server needed.
All DB and auth dependencies are mocked.
"""

from __future__ import annotations

import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Auto-use fixture: clear the IP rate limit window before every test so the
# in-memory sliding window doesn't accumulate across the test suite and block
# tests that legitimately expect 2xx responses.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_ip_rate_limit_windows():
    """Backward-compatible no-op for tests that used the old in-memory limiter."""
    import app.middleware.ip_rate_limit as _rl

    getattr(_rl, "_windows", {}).clear()
    yield
    getattr(_rl, "_windows", {}).clear()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_user(username: str = "testuser", user_id: str | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or str(uuid.uuid4())
    user.github_username = username
    user.display_name = username.title()
    user.avatar_url = None
    return user


def _make_session() -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalars.return_value.first.return_value = None
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = 0
    result.one_or_none.return_value = None
    result.one.return_value = (0, 0, 0)
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    return session


def _make_mini(
    mini_id: str | None = None,
    username: str = "testuser",
    owner_id: str | None = None,
    status: str = "ready",
    visibility: str = "public",
    system_prompt: str | None = "You are a test mini.",
    spirit_content: str | None = "Soul doc content.",
    memory_content: str | None = "Memory content.",
    knowledge_graph_json: dict | None = None,
    principles_json: dict | None = None,
    display_name: str | None = None,
    avatar_url: str | None = None,
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
    mini.status = status
    mini.visibility = visibility
    mini.system_prompt = system_prompt
    mini.spirit_content = spirit_content
    mini.memory_content = memory_content
    mini.knowledge_graph_json = knowledge_graph_json
    mini.principles_json = principles_json
    mini.display_name = display_name or username
    mini.avatar_url = avatar_url
    mini.evidence_cache = None
    mini.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
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


def _make_conversation(
    conv_id: str | None = None,
    mini_id: str | None = None,
    user_id: str | None = None,
    title: str | None = "Test Conversation",
) -> MagicMock:
    conv = MagicMock()
    conv.id = conv_id or str(uuid.uuid4())
    conv.mini_id = mini_id or str(uuid.uuid4())
    conv.user_id = user_id or str(uuid.uuid4())
    conv.title = title
    conv.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    conv.updated_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    return conv


def _make_team(
    team_id: str | None = None,
    owner_id: str | None = None,
    name: str = "Test Team",
) -> MagicMock:
    team = MagicMock()
    team.id = team_id or str(uuid.uuid4())
    team.owner_id = owner_id or str(uuid.uuid4())
    team.name = name
    team.description = None
    team.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    return team


def _make_result_with(value):
    """Return a mock session result that yields `value` from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = []
    result.scalars.return_value.first.return_value = None
    result.scalar_one.return_value = 0
    result.one_or_none.return_value = None
    result.one.return_value = (0, 0, 0)
    result.all.return_value = []
    return result


def _make_count_result(value: int):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


async def _client_with(user=None, session=None):
    """Return an (app, transport, overrides) tuple with dependencies applied."""
    from app.main import app
    from app.core.auth import get_current_user, get_optional_user
    from app.db import get_session

    overrides: dict = {}
    if user is not None:
        overrides[get_current_user] = lambda: user
        overrides[get_optional_user] = lambda: user
    else:
        overrides[get_optional_user] = lambda: None

    if session is not None:
        overrides[get_session] = lambda: session

    app.dependency_overrides.update(overrides)
    return app


# ===========================================================================
# MINIS ROUTES — additional coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_get_mini_by_id_not_found():
    """GET /api/minis/{id} with unknown ID returns 404."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/nonexistent-id")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_by_id_public_mini():
    """GET /api/minis/{id} returns public mini to anonymous user."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(visibility="public")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_mini_by_id_private_mini_no_auth():
    """GET /api/minis/{id} returns 404 for private mini when unauthenticated."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(visibility="private")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_by_id_owner_sees_private():
    """GET /api/minis/{id} returns private mini to its owner."""
    from app.main import app
    from app.core.auth import get_current_user, get_optional_user
    from app.db import get_session

    user = _make_user()
    mini = _make_mini(visibility="private", owner_id=user.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_mini_requires_auth():
    """DELETE /api/minis/{id} returns 401 when unauthenticated."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/minis/some-id")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_mini_not_found():
    """DELETE /api/minis/{id} returns 404 when mini does not exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()  # scalar_one_or_none returns None

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/minis/nonexistent-id")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_mini_not_owner():
    """DELETE /api/minis/{id} returns 403 when user is not the owner."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    mini = _make_mini(owner_id="different-owner-id")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/minis/{mini.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_mini_owner_success():
    """DELETE /api/minis/{id} returns 204 when user is the owner."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    mini = _make_mini(owner_id=user.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/minis/{mini.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_get_promo_mini_not_configured():
    """GET /api/minis/promo returns 404 when PROMO_MINI_USERNAME is not set."""
    from app.main import app
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    with patch("app.routes.minis.settings") as mock_settings:
        mock_settings.promo_mini_username = None

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/minis/promo")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_mini_authenticated_triggers_pipeline():
    """POST /api/minis with auth returns 202 and triggers background pipeline."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    mini = _make_mini(owner_id=user.id, status="processing")

    session = _make_session()
    # First execute (check existing): returns None
    # After commit + refresh: mini is returned
    session.execute = AsyncMock(return_value=_make_result_with(None))

    async def fake_refresh(obj):
        obj.id = mini.id
        obj.username = "torvalds"
        obj.status = "processing"
        obj.owner_id = user.id
        obj.visibility = "public"
        obj.display_name = None
        obj.avatar_url = None
        obj.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        obj.knowledge_graph_json = None
        obj.principles_json = None
        obj.spirit_content = None
        obj.memory_content = None

    session.refresh = AsyncMock(side_effect=fake_refresh)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with (
        patch("app.routes.minis.check_rate_limit", new=AsyncMock()),
        patch("app.routes.minis.run_pipeline_with_events", new=AsyncMock()),
        patch("asyncio.create_task"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/minis", json={"username": "torvalds", "sources": ["github"]}
            )

    app.dependency_overrides.clear()
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_get_mini_revisions_requires_auth():
    """GET /api/minis/{id}/revisions returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/some-id/revisions")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_mini_revisions_not_found():
    """GET /api/minis/{id}/revisions returns 404 when mini doesn't exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/nonexistent-id/revisions")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_repos_requires_auth():
    """GET /api/minis/{id}/repos returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/some-id/repos")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_mini_dataset_not_found():
    """GET /api/minis/{id}/dataset returns 404 when mini doesn't exist."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/nonexistent-id/dataset")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_dataset_no_soul_doc():
    """GET /api/minis/{id}/dataset returns 422 when mini has no spirit_content."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(spirit_content=None, visibility="public")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/dataset")

    app.dependency_overrides.clear()
    assert r.status_code == 422


# ===========================================================================
# CHAT ROUTE — auth, 404, 409 paths (no LLM streaming)
# ===========================================================================


@pytest.mark.asyncio
async def test_chat_mini_not_found():
    """POST /api/minis/{id}/chat returns 404 when mini doesn't exist."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/minis/nonexistent-id/chat",
            json={"message": "Hello", "history": []},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_chat_mini_not_ready():
    """POST /api/minis/{id}/chat returns 409 when mini status is not ready."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(status="processing", visibility="public")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/minis/{mini.id}/chat",
            json={"message": "Hello", "history": []},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_chat_mini_no_system_prompt():
    """POST /api/minis/{id}/chat returns 500 when mini has no system_prompt."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(status="ready", system_prompt=None, visibility="public")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/minis/{mini.id}/chat",
            json={"message": "Hello", "history": []},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_chat_private_mini_no_auth():
    """POST /api/minis/{id}/chat returns 404 for private mini when unauthenticated."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(visibility="private", status="ready")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/minis/{mini.id}/chat",
            json={"message": "Hello", "history": []},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 404


# ===========================================================================
# CONVERSATIONS ROUTES
# ===========================================================================


@pytest.mark.asyncio
async def test_list_conversations_requires_auth():
    """GET /api/minis/{mini_id}/conversations returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/some-mini-id/conversations")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_conversations_empty():
    """GET /api/minis/{mini_id}/conversations returns empty list when there are none."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    mini_id = str(uuid.uuid4())
    session = _make_session()  # scalars().all() returns []

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini_id}/conversations")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_conversation_requires_auth():
    """GET /api/minis/{mini_id}/conversations/{id} returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/m1/conversations/c1")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_conversation_not_found():
    """GET /api/minis/{mini_id}/conversations/{id} returns 404 when not found."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()  # scalar_one_or_none returns None

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/m1/conversations/c1")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_conversation_found():
    """GET /api/minis/{mini_id}/conversations/{id} returns conversation with messages."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    conv = _make_conversation(user_id=user.id)

    call_count = 0

    async def multi_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: return conversation
            return _make_result_with(conv)
        else:
            # Second call: return messages
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r

    session = _make_session()
    session.execute = AsyncMock(side_effect=multi_execute)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{conv.mini_id}/conversations/{conv.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == conv.id
    assert "messages" in body


@pytest.mark.asyncio
async def test_update_conversation_title_not_found():
    """PATCH /api/minis/{mini_id}/conversations/{id} returns 404 when not found."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.patch(
            "/api/minis/m1/conversations/c1",
            json={"title": "New Title"},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_conversation_title_success():
    """PATCH /api/minis/{mini_id}/conversations/{id} updates title and returns 200."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    conv = _make_conversation(user_id=user.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(conv))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.patch(
            f"/api/minis/{conv.mini_id}/conversations/{conv.id}",
            json={"title": "Updated Title"},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_conversation_requires_auth():
    """DELETE /api/minis/{mini_id}/conversations/{id} returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/minis/m1/conversations/c1")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_conversation_not_found():
    """DELETE /api/minis/{mini_id}/conversations/{id} returns 404 when not found."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/minis/m1/conversations/c1")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation_success():
    """DELETE /api/minis/{mini_id}/conversations/{id} returns 204 on success."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    conv = _make_conversation(user_id=user.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(conv))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/minis/{conv.mini_id}/conversations/{conv.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 204


# ===========================================================================
# TEAMS ROUTES
# ===========================================================================


@pytest.mark.asyncio
async def test_create_team_requires_auth():
    """POST /api/teams returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/teams", json={"name": "My Team"})

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_team_success():
    """POST /api/teams creates a team and returns 201."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    team = _make_team(owner_id=user.id)

    session = _make_session()

    async def fake_refresh(obj):
        obj.id = team.id
        obj.name = "My Team"
        obj.description = None
        obj.created_at = team.created_at

    session.refresh = AsyncMock(side_effect=fake_refresh)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/teams", json={"name": "My Team"})

    app.dependency_overrides.clear()
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "My Team"


@pytest.mark.asyncio
async def test_list_teams_requires_auth():
    """GET /api/teams returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/teams")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_teams_empty():
    """GET /api/teams returns empty list when user has no teams."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/teams")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_team_not_found():
    """GET /api/teams/{team_id} returns 404 when team doesn't exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/teams/nonexistent-team-id")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_team_not_found():
    """DELETE /api/teams/{team_id} returns 404 when team doesn't exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/teams/nonexistent-team-id")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_team_not_owner():
    """DELETE /api/teams/{team_id} returns 403 when user is not the owner."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    team = _make_team(owner_id="other-user-id")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(team))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/teams/{team.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_team_success():
    """DELETE /api/teams/{team_id} returns 204 when user is the owner."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    team = _make_team(owner_id=user.id)

    call_count = 0

    async def multi_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_result_with(team)
        # Subsequent calls (delete TeamMember) return an empty result
        return _make_result_with(None)

    session = _make_session()
    session.execute = AsyncMock(side_effect=multi_execute)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/teams/{team.id}")

    app.dependency_overrides.clear()
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_add_team_member_not_found_team():
    """POST /api/teams/{team_id}/members returns 404 when team not found."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/teams/nonexistent/members",
            json={"mini_id": "some-mini-id"},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_add_team_member_not_owner():
    """POST /api/teams/{team_id}/members returns 403 when user is not the owner."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    team = _make_team(owner_id="other-owner-id")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(team))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/teams/{team.id}/members",
            json={"mini_id": "some-mini-id"},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_remove_team_member_requires_auth():
    """DELETE /api/teams/{team_id}/members/{mini_id} returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/teams/t1/members/m1")

    assert r.status_code == 401


# ===========================================================================
# SETTINGS ROUTES — additional coverage
# ===========================================================================


@pytest.mark.asyncio
async def test_update_settings_requires_auth():
    """PUT /api/settings returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.put("/api/settings", json={"llm_provider": "openai"})

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_update_settings_creates_new_record():
    """PUT /api/settings creates settings when none exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    user_settings = MagicMock()
    user_settings.llm_provider = "openai"
    user_settings.preferred_model = None
    user_settings.llm_api_key = None
    user_settings.is_admin = False
    user_settings.model_preferences = None

    session.execute = AsyncMock(return_value=_make_result_with(None))
    session.refresh = AsyncMock(
        side_effect=lambda obj: setattr(obj, "llm_provider", "openai") or None
    )

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with patch("app.routes.settings.encrypt_value", return_value="encrypted"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put("/api/settings", json={"llm_provider": "openai"})

    app.dependency_overrides.clear()
    # Should succeed (200) — the response shape may vary due to new object
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_usage_requires_auth():
    """GET /api/settings/usage returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings/usage")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_usage_returns_counts():
    """GET /api/settings/usage returns usage counts for authenticated user."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    call_count = 0

    async def multi_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # user settings lookup
            return _make_result_with(None)
        else:
            # rate limit count queries
            r = MagicMock()
            r.scalar_one.return_value = 0
            return r

    session.execute = AsyncMock(side_effect=multi_execute)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings/usage")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert "mini_creates_today" in body
    assert "chat_messages_today" in body


@pytest.mark.asyncio
async def test_test_api_key_requires_auth():
    """POST /api/settings/test-key returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/settings/test-key",
            json={"api_key": "test-key", "provider": "gemini"},
        )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_test_api_key_invalid_format():
    """POST /api/settings/test-key returns invalid=True for bad key format."""
    from app.main import app
    from app.core.auth import get_current_user

    user = _make_user()
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/settings/test-key",
            json={"api_key": "definitely-not-a-valid-key", "provider": "gemini"},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False


@pytest.mark.asyncio
async def test_test_api_key_unknown_provider():
    """POST /api/settings/test-key returns invalid=True for unknown provider."""
    from app.main import app
    from app.core.auth import get_current_user

    user = _make_user()
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/settings/test-key",
            json={"api_key": "some-key", "provider": "unknownprovider"},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False


# ===========================================================================
# EXPORT ROUTES
# ===========================================================================


@pytest.mark.asyncio
async def test_export_subagent_not_found():
    """GET /api/export/minis/{mini_id}/subagent returns 404 when mini not found."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/export/minis/nonexistent-id/subagent")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_subagent_not_ready():
    """GET /api/export/minis/{mini_id}/subagent returns 409 when mini not ready."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owner = _make_user()
    mini = _make_mini(status="processing", visibility="public", owner_id=owner.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/subagent")

    app.dependency_overrides.clear()
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_export_subagent_owner_success():
    """GET /api/export/minis/{mini_id}/subagent returns 200 for the mini owner."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owner = _make_user()
    mini = _make_mini(status="ready", visibility="public", owner_id=owner.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/subagent")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert mini.username in r.text


@pytest.mark.asyncio
async def test_export_subagent_source_authorized_company_evidence_visible():
    """Company-classified, source-authorized evidence keeps owner export visible."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owner = _make_user()
    mini = _make_mini(status="ready", visibility="public", owner_id=owner.id)

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_result_with(mini),
            _make_count_result(0),
        ]
    )

    app.dependency_overrides[get_optional_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/subagent")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert mini.username in r.text


@pytest.mark.asyncio
async def test_export_subagent_blocks_private_or_missing_policy_evidence():
    """Private, missing-policy, or revoked evidence makes export fail closed."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owner = _make_user()
    mini = _make_mini(status="ready", visibility="public", owner_id=owner.id)

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[
            _make_result_with(mini),
            _make_count_result(3),
        ]
    )

    app.dependency_overrides[get_optional_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/subagent")

    app.dependency_overrides.clear()
    assert r.status_code == 409
    assert r.json()["detail"] == "Mini export blocked by evidence lifecycle policy"


@pytest.mark.asyncio
async def test_export_soul_doc_not_found():
    """GET /api/export/minis/{mini_id}/soul-doc returns 404 when mini not found."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/export/minis/nonexistent-id/soul-doc")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_soul_doc_no_spirit_content():
    """GET /api/export/minis/{mini_id}/soul-doc returns 404 when no spirit_content."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owner = _make_user()
    mini = _make_mini(spirit_content=None, visibility="public", owner_id=owner.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/soul-doc")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_soul_doc_owner_success():
    """GET /api/export/minis/{mini_id}/soul-doc returns spirit_content for owner."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owner = _make_user()
    mini = _make_mini(
        visibility="public", spirit_content="This is the soul doc.", owner_id=owner.id
    )

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: owner
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/soul-doc")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert "This is the soul doc." in r.text


@pytest.mark.asyncio
async def test_export_private_mini_soul_doc_no_auth():
    """GET /api/export/minis/{mini_id}/soul-doc returns 404 for private mini without auth."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _make_mini(visibility="private", spirit_content="Private soul doc.")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/soul-doc")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_subagent_public_mini_non_owner_denied():
    """GET /api/export/minis/{mini_id}/subagent returns 404 for non-owner."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owner = _make_user(user_id="owner-id")
    other_user = _make_user(user_id="other-user-id")
    mini = _make_mini(status="ready", visibility="public", owner_id=owner.id)

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: other_user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/export/minis/{mini.id}/subagent")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_soul_doc_public_mini_trusted_service_success():
    """GET /api/export/minis/{mini_id}/soul-doc returns 200 with trusted secret."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.core.config import settings
    from app.db import get_session

    mini = _make_mini(visibility="public", spirit_content="Trusted soul doc.")

    session = _make_session()
    session.execute = AsyncMock(return_value=_make_result_with(mini))

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/api/export/minis/{mini.id}/soul-doc",
            headers={"X-Trusted-Service-Secret": settings.trusted_service_secret},
        )

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert "Trusted soul doc." in r.text


@pytest.mark.asyncio
async def test_export_team_agents_requires_auth():
    """GET /api/export/teams/{team_id}/agent-team returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/export/teams/some-team-id/agent-team")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_export_team_agents_not_found():
    """GET /api/export/teams/{team_id}/agent-team returns 404 when team not found."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/export/teams/nonexistent-team-id/agent-team")

    app.dependency_overrides.clear()
    assert r.status_code == 404


# ===========================================================================
# UPLOAD ROUTES
# ===========================================================================


@pytest.mark.asyncio
async def test_upload_claude_code_requires_auth():
    """POST /api/upload/claude-code returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/upload/claude-code", files=[])

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_upload_claude_code_no_valid_files():
    """POST /api/upload/claude-code returns 400 when no valid .jsonl files uploaded."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with patch("app.routes.upload.check_rate_limit", new=AsyncMock()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/upload/claude-code",
                files=[("files", ("test.txt", b"not a jsonl file", "text/plain"))],
            )

    app.dependency_overrides.clear()
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_claude_code_valid_jsonl(tmp_path):
    """POST /api/upload/claude-code with valid .jsonl file returns 200."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    jsonl_content = b'{"role": "user", "content": "hello"}\n'

    with (
        patch("app.routes.upload.check_rate_limit", new=AsyncMock()),
        patch("app.routes.upload.Path") as mock_path_cls,
    ):
        # Mock the upload directory
        mock_dir = MagicMock()
        mock_dir.mkdir.return_value = None
        mock_dir.resolve.return_value = mock_dir
        dest = MagicMock()
        dest.resolve.return_value = dest
        dest.is_relative_to.return_value = True
        dest.write_bytes = MagicMock()
        mock_dir.__truediv__ = MagicMock(return_value=dest)
        mock_path_cls.return_value = mock_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/upload/claude-code",
                files=[("files", ("data.jsonl", jsonl_content, "application/octet-stream"))],
            )

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert "files_saved" in body


# ===========================================================================
# USAGE ROUTES
# ===========================================================================


@pytest.mark.asyncio
async def test_usage_me_requires_auth():
    """GET /api/usage/me returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/usage/me")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_usage_me_no_budget():
    """GET /api/usage/me returns default values when no budget record exists."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    call_count = 0

    async def multi_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # budget lookup
            return _make_result_with(None)
        else:
            # aggregate query
            r = MagicMock()
            r.one.return_value = (0, 0, 0)
            return r

    session.execute = AsyncMock(side_effect=multi_execute)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/usage/me")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    assert body["total_spent_usd"] == 0.0
    assert body["monthly_budget_usd"] == 5.0


@pytest.mark.asyncio
async def test_usage_me_history_requires_auth():
    """GET /api/usage/me/history returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/usage/me/history")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_usage_me_history_empty():
    """GET /api/usage/me/history returns empty list when no events."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()  # scalars().all() returns []

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/usage/me/history")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_update_my_budget_requires_auth():
    """PUT /api/usage/me/budget returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.put("/api/usage/me/budget", json={"monthly_budget_usd": 10.0})

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_update_my_budget_negative_rejected():
    """PUT /api/usage/me/budget rejects negative values with 400."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.put("/api/usage/me/budget", json={"monthly_budget_usd": -1.0})

    app.dependency_overrides.clear()
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_usage_global_requires_auth():
    """GET /api/usage/global returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/usage/global")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_usage_global_non_admin_forbidden():
    """GET /api/usage/global returns 403 for non-admin user."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user("regularuser")
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with patch("app.core.admin.settings") as mock_settings:
        mock_settings.admin_username_list = []

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/usage/global")

    app.dependency_overrides.clear()
    assert r.status_code == 403


# ===========================================================================
# ORGS ROUTES
# ===========================================================================


@pytest.mark.asyncio
async def test_list_orgs_requires_auth():
    """GET /api/orgs returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/orgs")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_orgs_empty():
    """GET /api/orgs returns empty list when user is not in any org."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/orgs")

    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_org_requires_auth():
    """POST /api/orgs returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/orgs",
            json={"name": "myorg", "display_name": "My Org"},
        )

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_org_not_found():
    """GET /api/orgs/{org_id} returns 404 when org doesn't exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/orgs/nonexistent-org-id")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_join_org_invalid_code():
    """POST /api/orgs/join/{code} returns 404 with invalid invite code."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/orgs/join/invalid-code-xyz")

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_org_requires_auth():
    """DELETE /api/orgs/{org_id} returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/orgs/some-org-id")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_org_not_found():
    """DELETE /api/orgs/{org_id} returns 404 when org doesn't exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/api/orgs/nonexistent-org-id")

    app.dependency_overrides.clear()
    assert r.status_code == 404


# ===========================================================================
# TEAM CHAT ROUTE — auth/404/409 only (no LLM streaming)
# ===========================================================================


@pytest.mark.asyncio
async def test_team_chat_requires_auth():
    """POST /api/teams/{team_id}/chat returns 401 without auth."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/teams/some-team-id/chat", json={"message": "Hello"})

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_team_chat_team_not_found():
    """POST /api/teams/{team_id}/chat returns 404 when team doesn't exist."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with patch("app.routes.team_chat.check_rate_limit", new=AsyncMock()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/teams/nonexistent-team-id/chat",
                json={"message": "Hello"},
            )

    app.dependency_overrides.clear()
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_team_chat_no_members():
    """POST /api/teams/{team_id}/chat returns 400 when team has no members."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    team = _make_team(owner_id=user.id)

    call_count = 0

    async def multi_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Team lookup
            return _make_result_with(team)
        else:
            # Members lookup - empty
            r = MagicMock()
            r.scalars.return_value.all.return_value = []
            return r

    session = _make_session()
    session.execute = AsyncMock(side_effect=multi_execute)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with (
        patch("app.routes.team_chat.check_rate_limit", new=AsyncMock()),
        patch("app.routes.team_chat.require_team_access", new=AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                f"/api/teams/{team.id}/chat",
                json={"message": "Hello"},
            )

    app.dependency_overrides.clear()
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_team_chat_no_ready_members():
    """POST /api/teams/{team_id}/chat returns 409 when no members are ready."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    team = _make_team(owner_id=user.id)
    mini = _make_mini(status="processing", system_prompt=None, owner_id=user.id)

    call_count = 0

    async def multi_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_result_with(team)
        else:
            r = MagicMock()
            r.scalars.return_value.all.return_value = [mini]
            return r

    session = _make_session()
    session.execute = AsyncMock(side_effect=multi_execute)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with (
        patch("app.routes.team_chat.check_rate_limit", new=AsyncMock()),
        patch("app.routes.team_chat.require_team_access", new=AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                f"/api/teams/{team.id}/chat",
                json={"message": "Hello"},
            )

    app.dependency_overrides.clear()
    assert r.status_code == 409
