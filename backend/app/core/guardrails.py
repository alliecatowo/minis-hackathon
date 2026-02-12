"""Guardrails module -- prompt injection detection, PII detection, and size limits.

These checks run BEFORE sending messages to the LLM. They log and flag
suspicious content but do not hard-block requests (defense-in-depth, not
a wall).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Prompt injection patterns ────────────────────────────────────────────────
# Common attempts to override system instructions. Matches are case-insensitive.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?prior\s+instructions",
        r"disregard\s+(all\s+)?previous\s+instructions",
        r"forget\s+(all\s+)?(your\s+)?instructions",
        r"override\s+(your\s+)?system\s+prompt",
        r"new\s+system\s+prompt",
        r"you\s+are\s+now\s+(?:a\s+)?(?:DAN|jailbroken|unfiltered)",
        r"^\s*system\s*:",
        r"<\|(?:im_start|system|assistant)\|>",
        r"\[INST\]",
        r"```\s*system",
        r"act\s+as\s+(?:if\s+)?(?:you\s+(?:have|had)\s+)?no\s+(?:restrictions|rules|guidelines)",
        r"pretend\s+(?:you\s+(?:are|have)\s+)?(?:no\s+)?(?:restrictions|rules|boundaries)",
        r"reveal\s+(?:your\s+)?system\s+prompt",
        r"show\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?(?:prompt|instructions)",
        r"print\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions)",
        r"output\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions)",
        r"repeat\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions)",
        r"what\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions)",
    ]
]

# ── PII patterns ─────────────────────────────────────────────────────────────
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone_us": re.compile(
        r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
    ),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}

# ── Size limits ──────────────────────────────────────────────────────────────
# Rough token estimation: 1 token ~= 4 characters
_CHARS_PER_TOKEN = 4
_MAX_INPUT_TOKENS = 8_000  # Warn threshold for a single user message
_MAX_HISTORY_TOKENS = 32_000  # Warn threshold for total conversation history


@dataclass
class GuardrailResult:
    """Result of running guardrail checks on a message."""

    flagged: bool = False
    injection_matches: list[str] = field(default_factory=list)
    pii_types: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    token_warning: bool = False


def check_prompt_injection(text: str) -> list[str]:
    """Check text for prompt injection patterns. Returns matched pattern descriptions."""
    matches: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            matches.append(pattern.pattern)
    return matches


def check_pii(text: str) -> list[str]:
    """Check text for PII patterns. Returns list of PII types found."""
    found: list[str] = []
    for pii_type, pattern in _PII_PATTERNS.items():
        if pattern.search(text):
            found.append(pii_type)
    return found


def estimate_tokens(text: str) -> int:
    """Estimate token count using char/4 heuristic."""
    return len(text) // _CHARS_PER_TOKEN


def check_message(message: str, history: list[dict] | None = None) -> GuardrailResult:
    """Run all guardrail checks on an incoming message.

    This is the main entry point -- call BEFORE sending to the LLM.
    Logs warnings but does not raise exceptions (flag, don't block).
    """
    result = GuardrailResult()

    # Prompt injection detection
    result.injection_matches = check_prompt_injection(message)
    if result.injection_matches:
        result.flagged = True
        logger.warning(
            "Prompt injection detected: %d pattern(s) matched in message",
            len(result.injection_matches),
        )

    # PII detection
    result.pii_types = check_pii(message)
    if result.pii_types:
        result.flagged = True
        logger.warning(
            "PII detected in message: %s",
            ", ".join(result.pii_types),
        )

    # Size limit estimation
    result.estimated_tokens = estimate_tokens(message)
    if result.estimated_tokens > _MAX_INPUT_TOKENS:
        result.token_warning = True
        result.flagged = True
        logger.warning(
            "Large message: ~%d estimated tokens (threshold: %d)",
            result.estimated_tokens,
            _MAX_INPUT_TOKENS,
        )

    # Check history size if provided
    if history:
        total_history_chars = sum(len(msg.get("content", "")) for msg in history)
        history_tokens = estimate_tokens(
            "x" * total_history_chars
        )  # Reuse same heuristic
        if history_tokens > _MAX_HISTORY_TOKENS:
            result.token_warning = True
            result.flagged = True
            logger.warning(
                "Large conversation history: ~%d estimated tokens (threshold: %d)",
                history_tokens,
                _MAX_HISTORY_TOKENS,
            )

    return result
