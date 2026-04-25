import logging
import re
import secrets
from datetime import timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import issue_service_jwt, get_current_user
from app.core.config import settings
from app.db import get_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# GitHub login handle pattern: 1–39 chars, alphanumeric + hyphens (no leading/trailing hyphens)
_GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


class SyncRequest(BaseModel):
    neon_auth_id: str
    github_username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    email: str | None = None

    @field_validator("github_username")
    @classmethod
    def validate_github_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Reject display names: any whitespace is a clear signal (e.g. "Allison Coleman")
        if " " in v or "\t" in v:
            raise ValueError(
                f"github_username '{v}' looks like a display name (contains whitespace). "
                "The BFF must send the GitHub login handle, not the display name."
            )
        # Reject values that don't match the GitHub handle pattern
        if not _GITHUB_LOGIN_RE.match(v):
            raise ValueError(
                f"github_username '{v}' is not a valid GitHub login handle "
                "(must match ^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){{0,38}}$)."
            )
        return v


class SyncResponse(BaseModel):
    user_id: str
    github_username: str | None = None


class UserResponse(BaseModel):
    id: str
    github_username: str | None
    display_name: str | None
    avatar_url: str | None


class GithubDeviceConfigResponse(BaseModel):
    client_id: str
    scope: str = "read:user"


class GithubDeviceExchangeRequest(BaseModel):
    access_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    github_username: str


async def _fetch_github_user(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid GitHub access token")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub user verification failed: {response.status_code}",
        )
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("id") or not payload.get("login"):
        raise HTTPException(status_code=502, detail="GitHub user response missing id/login")
    return payload


@router.get("/github-device/config", response_model=GithubDeviceConfigResponse)
async def get_github_device_config():
    """Return the public GitHub OAuth client ID for CLI/MCP device auth."""
    if not settings.github_device_client_id:
        raise HTTPException(status_code=501, detail="GitHub device auth is not configured")
    return GithubDeviceConfigResponse(client_id=settings.github_device_client_id)


@router.post("/github-device/exchange", response_model=TokenResponse)
async def exchange_github_device_token(
    body: GithubDeviceExchangeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Exchange a GitHub device-flow token for a Minis bearer token.

    This gives non-browser clients the same user-scoped auth contract as the
    web BFF without exposing the service JWT secret or relying on localhost
    callback redirects.
    """
    github_user = await _fetch_github_user(body.access_token.strip())
    github_id = str(github_user["id"])
    github_username = str(github_user["login"])

    result = await session.execute(
        select(User).where(func.lower(User.github_username) == github_username.lower())
    )
    user = result.scalar_one_or_none()

    if user is None:
        backend_user_id = f"github:{github_id}"
        result = await session.execute(select(User).where(User.id == backend_user_id))
        user = result.scalar_one_or_none()

    if user is None:
        user = User(id=f"github:{github_id}")
        session.add(user)

    user.github_username = github_username
    user.display_name = github_user.get("name") or github_username
    user.avatar_url = github_user.get("avatar_url")

    await session.commit()
    await session.refresh(user)

    expires_delta = timedelta(days=30)
    token = issue_service_jwt(str(user.id), expires_delta=expires_delta)
    return TokenResponse(
        access_token=token,
        expires_in=int(expires_delta.total_seconds()),
        user_id=str(user.id),
        github_username=github_username,
    )


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        github_username=current_user.github_username,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )


@router.post("/sync", response_model=SyncResponse)
async def sync_user(
    body: SyncRequest,
    session: AsyncSession = Depends(get_session),
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
):
    """Upsert user from Neon Auth. Returns backend user ID.

    Called by the BFF during the Auth.js signIn flow. The BFF passes Neon Auth
    profile data and receives a backend user ID to embed in the session JWT.

    Requires X-Internal-Secret header matching INTERNAL_API_SECRET env var.
    """
    if not x_internal_secret or not secrets.compare_digest(
        x_internal_secret, settings.internal_api_secret
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if body.github_username is None:
        logger.warning(
            "auth/sync: github_username is null for neon_auth_id=%s — "
            "BFF may have failed to resolve the GitHub login handle.",
            body.neon_auth_id,
        )

    result = await session.execute(select(User).where(User.id == body.neon_auth_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=body.neon_auth_id,
            github_username=body.github_username,
            display_name=body.display_name,
            avatar_url=body.avatar_url,
        )
        session.add(user)
    else:
        # Only overwrite github_username if the new value is non-null, so a
        # transient GitHub API failure never erases a previously-correct handle.
        if body.github_username is not None:
            user.github_username = body.github_username
        user.display_name = body.display_name
        user.avatar_url = body.avatar_url

    await session.commit()
    await session.refresh(user)

    return SyncResponse(user_id=str(user.id), github_username=user.github_username)
