import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.db import get_session
from app.models.usage import GlobalBudget, LLMUsageEvent, UserBudget
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["usage"])


# --- Response schemas ---


class UsageSummaryResponse(BaseModel):
    total_spent_usd: float
    monthly_budget_usd: float
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int


class UsageEventResponse(BaseModel):
    id: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    endpoint: str | None
    created_at: str


class BudgetUpdateRequest(BaseModel):
    monthly_budget_usd: float


class GlobalBudgetResponse(BaseModel):
    monthly_budget_usd: float
    total_spent_usd: float


# --- Helpers ---


def _require_admin(user: User) -> None:
    """Raise 403 if the user is not an admin."""
    if user.github_username.lower() not in settings.admin_username_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


# --- User endpoints ---


@router.get("/me", response_model=UsageSummaryResponse)
async def get_my_usage(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get the current user's usage summary and budget."""
    # Get or create budget record
    result = await session.execute(
        select(UserBudget).where(UserBudget.user_id == current_user.id)
    )
    budget = result.scalar_one_or_none()
    total_spent = budget.total_spent_usd if budget else 0.0
    monthly_budget = budget.monthly_budget_usd if budget else 5.0

    # Aggregate token counts
    result = await session.execute(
        select(
            func.count(LLMUsageEvent.id),
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
        ).where(LLMUsageEvent.user_id == current_user.id)
    )
    row = result.one()
    total_requests, total_input, total_output = row

    return UsageSummaryResponse(
        total_spent_usd=total_spent,
        monthly_budget_usd=monthly_budget,
        total_requests=total_requests,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )


@router.get("/me/history", response_model=list[UsageEventResponse])
async def get_my_usage_history(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get the current user's recent usage events."""
    result = await session.execute(
        select(LLMUsageEvent)
        .where(LLMUsageEvent.user_id == current_user.id)
        .order_by(LLMUsageEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()
    return [
        UsageEventResponse(
            id=e.id,
            model=e.model,
            input_tokens=e.input_tokens,
            output_tokens=e.output_tokens,
            total_tokens=e.total_tokens,
            cost_usd=e.cost_usd,
            endpoint=e.endpoint,
            created_at=e.created_at.isoformat(),
        )
        for e in events
    ]


@router.put("/me/budget", response_model=UsageSummaryResponse)
async def update_my_budget(
    body: BudgetUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update the current user's monthly budget."""
    if body.monthly_budget_usd < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Budget must be non-negative",
        )

    result = await session.execute(
        select(UserBudget).where(UserBudget.user_id == current_user.id)
    )
    budget = result.scalar_one_or_none()
    if budget is None:
        budget = UserBudget(user_id=current_user.id, monthly_budget_usd=body.monthly_budget_usd)
        session.add(budget)
    else:
        budget.monthly_budget_usd = body.monthly_budget_usd

    await session.commit()
    await session.refresh(budget)

    # Re-fetch aggregate stats
    result = await session.execute(
        select(
            func.count(LLMUsageEvent.id),
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
        ).where(LLMUsageEvent.user_id == current_user.id)
    )
    row = result.one()
    total_requests, total_input, total_output = row

    return UsageSummaryResponse(
        total_spent_usd=budget.total_spent_usd,
        monthly_budget_usd=budget.monthly_budget_usd,
        total_requests=total_requests,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )


# --- Admin endpoints ---


@router.get("/global", response_model=GlobalBudgetResponse)
async def get_global_usage(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get platform-wide usage summary (admin only)."""
    _require_admin(current_user)

    result = await session.execute(
        select(GlobalBudget).where(GlobalBudget.key == "global")
    )
    budget = result.scalar_one_or_none()

    return GlobalBudgetResponse(
        monthly_budget_usd=budget.monthly_budget_usd if budget else 100.0,
        total_spent_usd=budget.total_spent_usd if budget else 0.0,
    )


@router.put("/global/budget", response_model=GlobalBudgetResponse)
async def update_global_budget(
    body: BudgetUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update the platform-wide monthly budget (admin only)."""
    _require_admin(current_user)

    if body.monthly_budget_usd < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Budget must be non-negative",
        )

    result = await session.execute(
        select(GlobalBudget).where(GlobalBudget.key == "global")
    )
    budget = result.scalar_one_or_none()
    if budget is None:
        budget = GlobalBudget(monthly_budget_usd=body.monthly_budget_usd)
        session.add(budget)
    else:
        budget.monthly_budget_usd = body.monthly_budget_usd

    await session.commit()
    await session.refresh(budget)

    return GlobalBudgetResponse(
        monthly_budget_usd=budget.monthly_budget_usd,
        total_spent_usd=budget.total_spent_usd,
    )
