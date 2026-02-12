import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.rate_limit import RATE_LIMITS
from app.db import get_session
from app.models.rate_limit import RateLimitEvent
from app.models.user import User
from app.models.user_settings import UserSettings

router = APIRouter(prefix="/settings", tags=["settings"])

AVAILABLE_MODELS = {
    "gemini": [
        {"id": "gemini/gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        {"id": "gemini/gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
    ],
}


class SettingsResponse(BaseModel):
    llm_provider: str
    preferred_model: str | None
    has_api_key: bool
    is_admin: bool


class UpdateSettingsRequest(BaseModel):
    llm_api_key: str | None = None
    llm_provider: str | None = None
    preferred_model: str | None = None


class UsageResponse(BaseModel):
    mini_creates_today: int
    mini_create_limit: int
    chat_messages_today: int
    chat_message_limit: int
    is_exempt: bool


@router.get("")
async def get_settings(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        return SettingsResponse(
            llm_provider="gemini",
            preferred_model=None,
            has_api_key=False,
            is_admin=user.github_username.lower() in settings.admin_username_list,
        )
    return SettingsResponse(
        llm_provider=user_settings.llm_provider,
        preferred_model=user_settings.preferred_model,
        has_api_key=bool(user_settings.llm_api_key),
        is_admin=user_settings.is_admin
        or user.github_username.lower() in settings.admin_username_list,
    )


@router.put("")
async def update_settings(
    body: UpdateSettingsRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        user_settings = UserSettings(user_id=user.id)
        session.add(user_settings)

    if body.llm_api_key is not None:
        user_settings.llm_api_key = body.llm_api_key or None
    if body.llm_provider is not None:
        user_settings.llm_provider = body.llm_provider
    if body.preferred_model is not None:
        user_settings.preferred_model = body.preferred_model or None

    await session.commit()
    await session.refresh(user_settings)

    return SettingsResponse(
        llm_provider=user_settings.llm_provider,
        preferred_model=user_settings.preferred_model,
        has_api_key=bool(user_settings.llm_api_key),
        is_admin=user_settings.is_admin
        or user.github_username.lower() in settings.admin_username_list,
    )


@router.get("/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsageResponse:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    # Check exemption status
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    user_settings = result.scalar_one_or_none()
    is_exempt = False
    if user_settings:
        if user_settings.llm_api_key or user_settings.is_admin:
            is_exempt = True
    if user.github_username.lower() in settings.admin_username_list:
        is_exempt = True

    # Count events in last 24h
    mini_creates = 0
    chat_messages = 0
    for event_type, attr in [("mini_create", "mini_creates"), ("chat_message", "chat_messages")]:
        result = await session.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.user_id == user.id,
                RateLimitEvent.event_type == event_type,
                RateLimitEvent.created_at >= cutoff,
            )
        )
        count = result.scalar_one()
        if event_type == "mini_create":
            mini_creates = count
        else:
            chat_messages = count

    return UsageResponse(
        mini_creates_today=mini_creates,
        mini_create_limit=RATE_LIMITS["mini_create"],
        chat_messages_today=chat_messages,
        chat_message_limit=RATE_LIMITS["chat_message"],
        is_exempt=is_exempt,
    )


@router.get("/models")
async def get_available_models():
    """Get available LLM models grouped by provider."""
    return AVAILABLE_MODELS
