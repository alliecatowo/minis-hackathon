from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


def _session_with_results(*values):
    session = AsyncMock()
    results = []
    for value in values:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        results.append(result)
    session.execute = AsyncMock(side_effect=results)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_github_device_exchange_creates_user_and_issues_service_jwt(monkeypatch):
    from app.core.auth import _validate_service_jwt
    from app.routes import auth

    async def fake_fetch_github_user(access_token: str):
        assert access_token == "gho_test"
        return {
            "id": 12345,
            "login": "octocat",
            "name": "The Octocat",
            "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        }

    monkeypatch.setattr(auth, "_fetch_github_user", fake_fetch_github_user)
    session = _session_with_results(None, None)

    response = await auth.exchange_github_device_token(
        auth.GithubDeviceExchangeRequest(access_token="gho_test"),
        session=session,
    )

    session.add.assert_called_once()
    created_user = session.add.call_args.args[0]
    assert created_user.id == "github:12345"
    assert created_user.github_username == "octocat"
    assert response.github_username == "octocat"
    assert response.token_type == "bearer"
    assert _validate_service_jwt(response.access_token) == "github:12345"


@pytest.mark.asyncio
async def test_github_device_exchange_reuses_existing_user(monkeypatch):
    from app.models.user import User
    from app.routes import auth

    existing = User(id="existing-user", github_username="OctoCat")

    async def fake_fetch_github_user(access_token: str):
        return {
            "id": 12345,
            "login": "octocat",
            "name": None,
            "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        }

    monkeypatch.setattr(auth, "_fetch_github_user", fake_fetch_github_user)
    session = _session_with_results(existing)

    response = await auth.exchange_github_device_token(
        auth.GithubDeviceExchangeRequest(access_token="gho_test"),
        session=session,
    )

    session.add.assert_not_called()
    assert existing.id == "existing-user"
    assert existing.github_username == "octocat"
    assert existing.display_name == "octocat"
    assert response.user_id == "existing-user"


@pytest.mark.asyncio
async def test_github_device_exchange_rejects_invalid_github_token(monkeypatch):
    from app.routes import auth

    async def fake_fetch_github_user(access_token: str):
        raise HTTPException(status_code=401, detail="Invalid GitHub access token")

    monkeypatch.setattr(auth, "_fetch_github_user", fake_fetch_github_user)

    with pytest.raises(HTTPException) as exc_info:
        await auth.exchange_github_device_token(
            auth.GithubDeviceExchangeRequest(access_token="bad"),
            session=_session_with_results(),
        )

    assert exc_info.value.status_code == 401
