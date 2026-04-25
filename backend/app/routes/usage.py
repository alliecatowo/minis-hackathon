import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin import is_trusted_admin
from app.core.auth import get_current_user
from app.core.config import settings
from app.db import async_session, get_session
from app.models.mini import Mini
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


class LLMUsageDailyRow(BaseModel):
    day: str
    model_tier: str
    user_id: str | None
    endpoint: str | None
    call_count: int
    input_tokens: int
    output_tokens: int


class AdminCostControlsResponse(BaseModel):
    llm_kill_switch_enabled: bool
    disable_llm_calls_value: str
    global_monthly_budget_usd: float
    global_total_spent_usd: float
    max_pipeline_tokens_per_mini: int
    token_budget_exceeded_minis: list[dict[str, str | None]]


# --- Helpers ---


def _require_admin(user: User) -> None:
    """Raise 403 if the user is not an admin."""
    if not is_trusted_admin(user):
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
    result = await session.execute(select(UserBudget).where(UserBudget.user_id == current_user.id))
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

    result = await session.execute(select(UserBudget).where(UserBudget.user_id == current_user.id))
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

    result = await session.execute(select(GlobalBudget).where(GlobalBudget.key == "global"))
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

    result = await session.execute(select(GlobalBudget).where(GlobalBudget.key == "global"))
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


@router.get("/admin/llm-usage", response_model=list[LLMUsageDailyRow])
async def get_admin_llm_usage(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return last-24h LLM usage totals by (tier, user_id, endpoint). Admin only."""
    _require_admin(current_user)

    from app.core.llm_usage import get_last_24h_totals

    rows = await get_last_24h_totals(async_session)
    return [LLMUsageDailyRow(**row) for row in rows]


@router.get("/admin/cost-controls", response_model=AdminCostControlsResponse)
async def get_admin_cost_controls(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return admin-visible LLM cost caps, kill-switch state, and budget failures."""
    _require_admin(current_user)

    result = await session.execute(select(GlobalBudget).where(GlobalBudget.key == "global"))
    budget = result.scalar_one_or_none()

    minis_result = await session.execute(
        select(Mini).where(
            Mini.status == "failed",
            Mini.metadata_json.isnot(None),
        )
    )
    exceeded_minis: list[dict[str, str | None]] = []
    for mini in minis_result.scalars().all():
        metadata = mini.metadata_json if isinstance(mini.metadata_json, dict) else {}
        if metadata.get("failure_reason") != "token budget exceeded":
            continue
        exceeded_minis.append(
            {
                "mini_id": mini.id,
                "username": mini.username,
                "failure_reason": metadata.get("failure_reason"),
            }
        )

    return AdminCostControlsResponse(
        llm_kill_switch_enabled=settings.llm_disabled,
        disable_llm_calls_value=settings.disable_llm_calls,
        global_monthly_budget_usd=budget.monthly_budget_usd if budget else 100.0,
        global_total_spent_usd=budget.total_spent_usd if budget else 0.0,
        max_pipeline_tokens_per_mini=settings.max_pipeline_tokens_per_mini,
        token_budget_exceeded_minis=exceeded_minis,
    )
