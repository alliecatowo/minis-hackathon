import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.rate_limit import RateLimitEvent
from app.models.user import User
from app.models.user_settings import UserSettings

RATE_LIMITS: dict[str, int] = {
    "mini_create": 1,
    "chat_message": 25,
    "team_chat": 15,
    "file_upload": 5,
}


async def check_rate_limit(
    user_id: str, event_type: str, session: AsyncSession
) -> None:
    limit = RATE_LIMITS.get(event_type)
    if limit is None:
        return

    # Check exemptions: user settings (BYOK or admin flag)
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if user_settings:
        if user_settings.llm_api_key:
            return
        if user_settings.is_admin:
            return

    # Check exemptions: admin username list from config
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and user.github_username.lower() in settings.admin_username_list:
        return

    # Count events in the last 24 hours
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    result = await session.execute(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(
            RateLimitEvent.user_id == user_id,
            RateLimitEvent.event_type == event_type,
            RateLimitEvent.created_at >= cutoff,
        )
    )
    count = result.scalar_one()

    if count >= limit:
        # Calculate reset time from the oldest event in the window
        oldest_result = await session.execute(
            select(RateLimitEvent.created_at)
            .where(
                RateLimitEvent.user_id == user_id,
                RateLimitEvent.event_type == event_type,
                RateLimitEvent.created_at >= cutoff,
            )
            .order_by(RateLimitEvent.created_at.asc())
            .limit(1)
        )
        oldest_time = oldest_result.scalar_one()
        reset_time = oldest_time + datetime.timedelta(hours=24)
        hours_remaining = max(
            1,
            int(
                (reset_time - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
                / 3600
            ),
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: {limit} {event_type} per day. "
                f"Resets in {hours_remaining} hours. "
                "Add your own API key in Settings to remove limits."
            ),
        )

    # Record the event
    session.add(RateLimitEvent(user_id=user_id, event_type=event_type))
    await session.flush()
