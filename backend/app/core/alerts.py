"""Structured logging alerts for LLM cost anomalies."""

import logging

logger = logging.getLogger("app.alerts.llm_cost")


def alert_budget_threshold(
    user_id: str, spent: float, budget: float, pct: float
) -> None:
    """Log when a user hits 80%+ of their monthly budget."""
    logger.warning(
        "BUDGET_THRESHOLD user_id=%s spent=%.4f budget=%.2f pct=%.1f%%",
        user_id,
        spent,
        budget,
        pct * 100,
    )


def alert_global_threshold(spent: float, budget: float, pct: float) -> None:
    """Log when global spend hits 80%+ of the platform budget."""
    logger.warning(
        "GLOBAL_BUDGET_THRESHOLD spent=%.4f budget=%.2f pct=%.1f%%",
        spent,
        budget,
        pct * 100,
    )


def alert_expensive_request(
    user_id: str | None, model: str, cost: float, tokens: int
) -> None:
    """Log when a single request costs more than $0.50."""
    logger.warning(
        "EXPENSIVE_REQUEST user_id=%s model=%s cost=%.4f tokens=%d",
        user_id or "anonymous",
        model,
        cost,
        tokens,
    )


def alert_budget_exceeded(user_id: str, spent: float, budget: float) -> None:
    """Log when a user's budget is fully exhausted."""
    logger.error(
        "BUDGET_EXCEEDED user_id=%s spent=%.4f budget=%.2f",
        user_id,
        spent,
        budget,
    )
