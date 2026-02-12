import logging
import os
from collections.abc import AsyncGenerator

import litellm

from app.core.config import settings

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


class BudgetExceededError(Exception):
    """Raised when a user or the platform has exceeded their LLM budget."""

    def __init__(self, message: str = "LLM budget exceeded"):
        self.message = message
        super().__init__(self.message)


def setup_langfuse() -> None:
    """Configure litellm to send traces to Langfuse when enabled."""
    if not settings.langfuse_enabled:
        logger.debug("Langfuse observability is disabled")
        return

    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = settings.langfuse_host

    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]
    logger.info("Langfuse observability enabled (host=%s)", settings.langfuse_host)


async def _check_budget(user_id: str | None) -> None:
    """Check user and global budgets before making an LLM call.

    Raises BudgetExceededError if the budget is exhausted.
    Does nothing if user_id is None (unauthenticated/system calls).
    """
    if user_id is None:
        return

    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models.usage import GlobalBudget, UserBudget

        async with async_session() as session:
            # Check user budget
            result = await session.execute(
                select(UserBudget).where(UserBudget.user_id == user_id)
            )
            user_budget = result.scalar_one_or_none()
            if user_budget and user_budget.total_spent_usd >= user_budget.monthly_budget_usd:
                raise BudgetExceededError(
                    f"Monthly budget of ${user_budget.monthly_budget_usd:.2f} exceeded"
                )

            # Check global budget
            result = await session.execute(
                select(GlobalBudget).where(GlobalBudget.key == "global")
            )
            global_budget = result.scalar_one_or_none()
            if global_budget and global_budget.total_spent_usd >= global_budget.monthly_budget_usd:
                raise BudgetExceededError("Platform-wide LLM budget exceeded")
    except BudgetExceededError:
        raise
    except Exception:
        logger.debug("Budget check failed (non-blocking)", exc_info=True)


async def _record_usage(
    user_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    endpoint: str | None = None,
    error: str | None = None,
) -> None:
    """Record an LLM usage event to the database.

    Never raises -- failures are logged and swallowed so metering
    does not break the caller.
    """
    try:
        from app.core.alerts import (
            alert_budget_threshold,
            alert_expensive_request,
            alert_global_threshold,
        )
        from app.db import async_session
        from app.models.usage import GlobalBudget, LLMUsageEvent, UserBudget

        async with async_session() as session:
            # 1. Write the usage event
            event = LLMUsageEvent(
                user_id=user_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost_usd,
                endpoint=endpoint,
                error=error,
            )
            session.add(event)

            # 2. Update user budget running total
            if user_id:
                from sqlalchemy import select

                result = await session.execute(
                    select(UserBudget).where(UserBudget.user_id == user_id)
                )
                user_budget = result.scalar_one_or_none()
                if user_budget is None:
                    user_budget = UserBudget(user_id=user_id)
                    session.add(user_budget)
                    await session.flush()
                user_budget.total_spent_usd += cost_usd

                # Alert at 80% threshold
                if user_budget.monthly_budget_usd > 0:
                    pct = user_budget.total_spent_usd / user_budget.monthly_budget_usd
                    if pct >= 0.8:
                        alert_budget_threshold(
                            user_id,
                            user_budget.total_spent_usd,
                            user_budget.monthly_budget_usd,
                            pct,
                        )

            # 3. Update global budget running total
            from sqlalchemy import select

            result = await session.execute(
                select(GlobalBudget).where(GlobalBudget.key == "global")
            )
            global_budget = result.scalar_one_or_none()
            if global_budget is None:
                global_budget = GlobalBudget()
                session.add(global_budget)
                await session.flush()
            global_budget.total_spent_usd += cost_usd

            if global_budget.monthly_budget_usd > 0:
                pct = global_budget.total_spent_usd / global_budget.monthly_budget_usd
                if pct >= 0.8:
                    alert_global_threshold(
                        global_budget.total_spent_usd,
                        global_budget.monthly_budget_usd,
                        pct,
                    )

            await session.commit()

        # 4. Alert on expensive single requests
        if cost_usd > 0.50:
            alert_expensive_request(
                user_id, model, cost_usd, input_tokens + output_tokens
            )

    except Exception:
        logger.error("Failed to record LLM usage event", exc_info=True)


def _extract_usage(response) -> tuple[int, int]:
    """Extract input/output token counts from a litellm response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0


async def llm_completion(
    prompt: str,
    system: str = "",
    model: str | None = None,
    api_key: str | None = None,
    user_id: str | None = None,
) -> str:
    """Single-shot LLM completion. Returns the assistant message content."""
    model = model or settings.default_llm_model
    await _check_budget(user_id)

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {"model": model, "messages": messages}
    if api_key:
        kwargs["api_key"] = api_key
    response = await litellm.acompletion(**kwargs)

    input_tokens, output_tokens = _extract_usage(response)
    from app.core.pricing import calculate_cost

    cost = calculate_cost(model, input_tokens, output_tokens)
    await _record_usage(user_id, model, input_tokens, output_tokens, cost, endpoint="llm_completion")

    return response.choices[0].message.content


async def llm_completion_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
    api_key: str | None = None,
    user_id: str | None = None,
) -> str:
    """LLM completion with JSON response format. Returns raw string (caller parses)."""
    model = model or settings.default_llm_model
    await _check_budget(user_id)

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if api_key:
        kwargs["api_key"] = api_key
    response = await litellm.acompletion(**kwargs)

    input_tokens, output_tokens = _extract_usage(response)
    from app.core.pricing import calculate_cost

    cost = calculate_cost(model, input_tokens, output_tokens)
    await _record_usage(user_id, model, input_tokens, output_tokens, cost, endpoint="llm_completion_json")

    return response.choices[0].message.content


async def llm_stream(
    messages: list[dict],
    model: str | None = None,
    api_key: str | None = None,
    user_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Streaming LLM completion. Yields content deltas as strings.

    Token usage is recorded after the stream completes using litellm's
    stream_options to request usage in the final chunk.
    """
    model = model or settings.default_llm_model
    await _check_budget(user_id)

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if api_key:
        kwargs["api_key"] = api_key
    response = await litellm.acompletion(**kwargs)

    input_tokens = 0
    output_tokens = 0
    async for chunk in response:
        # Capture usage from final chunk if present
        usage = getattr(chunk, "usage", None)
        if usage:
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0

        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content

    # Record usage after stream ends
    from app.core.pricing import calculate_cost

    cost = calculate_cost(model, input_tokens, output_tokens)
    await _record_usage(user_id, model, input_tokens, output_tokens, cost, endpoint="llm_stream")
