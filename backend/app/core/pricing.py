"""Model pricing and cost calculation for LLM metering."""

# Prices per 1M tokens (USD)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini/gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini/gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini/gemini-2.5-flash-preview-05-20": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}

# Fallback pricing for unknown models (conservative estimate)
DEFAULT_PRICING: dict[str, float] = {"input": 1.00, "output": 3.00}


def calculate_cost(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Calculate USD cost for a completion given token counts.

    Returns cost in USD (e.g. 0.00015 for a small request).
    """
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
