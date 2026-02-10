import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, get_current_user
from app.core.config import settings
from app.db import get_session
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class GitHubCodeRequest(BaseModel):
    code: str


class UserResponse(BaseModel):
    id: int
    github_username: str
    display_name: str | None
    avatar_url: str | None


class AuthResponse(BaseModel):
    token: str
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
        error = token_data.get("error_description", "Unknown error")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"GitHub OAuth error: {error}",
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

    # Create JWT
    jwt_token = create_access_token({"sub": str(user.id)})

    return AuthResponse(
        token=jwt_token,
        user=UserResponse(
            id=user.id,
            github_username=user.github_username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        ),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        github_username=current_user.github_username,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )
