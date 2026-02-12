import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    refresh_access_token,
    revoke_user_tokens,
)
from app.core.config import settings
from app.db import get_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class GitHubCodeRequest(BaseModel):
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class SyncRequest(BaseModel):
    github_id: int
    github_username: str
    display_name: str | None = None
    avatar_url: str | None = None


class SyncResponse(BaseModel):
    user_id: str
    token: str


class UserResponse(BaseModel):
    id: str
    github_username: str
    display_name: str | None
    avatar_url: str | None


class AuthResponse(BaseModel):
    token: str
    refresh_token: str
    user: UserResponse


@router.post("/github", response_model=AuthResponse)
async def github_auth(
    body: GitHubCodeRequest,
    session: AsyncSession = Depends(get_session),
):
    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": body.code,
            },
            headers={"Accept": "application/json"},
        )

    if token_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to exchange code with GitHub",
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        error_code = token_data.get("error", "unknown")
        error_desc = token_data.get("error_description", "Unknown error")
        logger.error(
            "GitHub OAuth token exchange failed: error=%s, description=%s, "
            "client_id_set=%s",
            error_code,
            error_desc,
            bool(settings.github_client_id),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"GitHub OAuth error: {error_desc}",
        )

    # Fetch GitHub user profile
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )

    if user_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch GitHub user profile",
        )

    gh_user = user_resp.json()
    github_id = gh_user["id"]
    github_username = gh_user["login"]
    display_name = gh_user.get("name")
    avatar_url = gh_user.get("avatar_url")

    # Upsert user by github_id
    result = await session.execute(select(User).where(User.github_id == github_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            github_id=github_id,
            github_username=github_username,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        session.add(user)
    else:
        user.github_username = github_username
        user.display_name = display_name
        user.avatar_url = avatar_url

    await session.commit()
    await session.refresh(user)

    # Create JWT access token and refresh token
    jwt_token = create_access_token({"sub": str(user.id)})
    refresh_tok = await create_refresh_token(user.id, session)
    await session.commit()

    return AuthResponse(
        token=jwt_token,
        refresh_token=refresh_tok,
        user=UserResponse(
            id=user.id,
            github_username=user.github_username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        ),
    )


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        new_access, new_refresh = await refresh_access_token(
            body.refresh_token, session
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return {"token": new_access, "refresh_token": new_refresh}


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await revoke_user_tokens(current_user.id, session)
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
):
    """Upsert user from Auth.js signIn callback. Returns backend user ID and access token.

    Called by the BFF during the Auth.js signIn flow. The BFF passes GitHub profile
    data and receives a backend user ID to embed in the session JWT.
    """
    result = await session.execute(select(User).where(User.github_id == body.github_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            github_id=body.github_id,
            github_username=body.github_username,
            display_name=body.display_name,
            avatar_url=body.avatar_url,
        )
        session.add(user)
    else:
        user.github_username = body.github_username
        user.display_name = body.display_name
        user.avatar_url = body.avatar_url

    await session.commit()
    await session.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return SyncResponse(user_id=str(user.id), token=token)
