"""Model hierarchy and tier system for LLM provider management.

Every model reference in the codebase goes through this module.
Users can override defaults via settings or per-request overrides.
"""

from __future__ import annotations

import os
from enum import StrEnum

# Bridge GEMINI_API_KEY to GOOGLE_API_KEY for PydanticAI
if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


class ModelTier(StrEnum):
    FAST = "fast"  # Compaction, summaries, classifications
    STANDARD = "standard"  # Explorer agents, chat, tool-calling
    THINKING = "thinking"  # Complex synthesis, soul documents
    EMBEDDING = "embedding"  # Vector embeddings


class Provider(StrEnum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


# Provider defaults using PydanticAI model string format ("provider:model-name")
PROVIDER_DEFAULTS: dict[Provider, dict[ModelTier, str]] = {
    Provider.GEMINI: {
        ModelTier.FAST: "google-gla:gemini-2.5-flash",
        ModelTier.STANDARD: "google-gla:gemini-2.5-flash",
        ModelTier.THINKING: "google-gla:gemini-2.5-pro",
        ModelTier.EMBEDDING: "google-gla:text-embedding-004",
    },
    Provider.ANTHROPIC: {
        ModelTier.FAST: "anthropic:claude-haiku-4-5",
        ModelTier.STANDARD: "anthropic:claude-sonnet-4-6",
        ModelTier.THINKING: "anthropic:claude-sonnet-4-6",
    },
    Provider.OPENAI: {
        # Cost-optimized mix (see docs/audits/2026-05-09-openai-pricing.md):
        #
        # | Tier      | Model                  | Input $/1M | Output $/1M | Free quota   |
        # |-----------|------------------------|-----------:|------------:|--------------|
        # | FAST      | gpt-4.1-nano           |      $0.10 |       $0.40 | 10M/day pool |
        # | STANDARD  | gpt-5                  |      $2.00 |       $8.00 | 1M/day pool  |
        # | THINKING  | o4-mini                |      $1.10 |       $4.40 | 10M/day pool |
        # | EMBEDDING | text-embedding-3-small |      $0.02 |           — | —            |
        #
        # FAST: gpt-4.1-nano replaces non-existent "gpt-5-mini" (caused silent errors).
        # STANDARD: gpt-5 stays — same price as gpt-4.1 with better tool-calling quality.
        # THINKING: o4-mini replaces o3 ($10/$40/1M); 9x cheaper for narrative essay synthesis.
        ModelTier.FAST: "openai:gpt-4.1-nano",
        ModelTier.STANDARD: "openai:gpt-5",
        ModelTier.THINKING: "openai:o4-mini",
        ModelTier.EMBEDDING: "openai:text-embedding-3-small",
    },
}


def _detect_default_provider() -> Provider:
    """Detect the default provider from env vars."""
    env_provider = os.environ.get("DEFAULT_PROVIDER", "gemini").lower()
    try:
        return Provider(env_provider)
    except ValueError:
        return Provider.GEMINI


def get_model(
    tier: ModelTier = ModelTier.STANDARD,
    user_override: str | None = None,
) -> str:
    """Resolve a model string for the given tier.

    Resolution order:
    1. User override (if provided) — returned as-is
    2. Provider defaults for the system's default provider
    3. Gemini fallback (always available)

    Returns a PydanticAI model string like "gemini:gemini-2.5-flash".
    """
    # Defensive bridge: ensure GOOGLE_API_KEY is set if we have GEMINI_API_KEY
    if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

    if user_override:
        return user_override

    provider = _detect_default_provider()
    provider_models = PROVIDER_DEFAULTS.get(provider, {})

    if tier in provider_models:
        return provider_models[tier]

    # Fallback to Gemini defaults
    gemini_models = PROVIDER_DEFAULTS[Provider.GEMINI]
    if tier in gemini_models:
        return gemini_models[tier]

    # Ultimate fallback
    return "google-gla:gemini-2.5-flash"


def get_default_model() -> str:
    """Get the default standard-tier model. Convenience wrapper."""
    return get_model(ModelTier.STANDARD)
