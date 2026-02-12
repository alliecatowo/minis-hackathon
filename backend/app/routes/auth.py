import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class SyncRequest(BaseModel):
    neon_auth_id: str
    github_username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    email: str | None = None


class SyncResponse(BaseModel):
    user_id: str


class UserResponse(BaseModel):
    id: str
    github_username: str | None
    display_name: str | None
    avatar_url: str | None


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
):
    """Upsert user from Neon Auth. Returns backend user ID.

    Called by the BFF during the Auth.js signIn flow. The BFF passes Neon Auth
    profile data and receives a backend user ID to embed in the session JWT.
    """
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
        user.github_username = body.github_username
        user.display_name = body.display_name
        user.avatar_url = body.avatar_url

    await session.commit()
    await session.refresh(user)

    return SyncResponse(user_id=str(user.id))
