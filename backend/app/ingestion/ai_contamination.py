"""AI contamination detection for evidence items (ALLIE-433).

Hybrid approach:
- Heuristic pass: fast, zero-cost regex/pattern matching.
- LLM pass: FAST-tier PydanticAI agent for ambiguous middle-zone items.

Scores: 0.0 = definitely human, 1.0 = definitely AI-generated.

Classification strategy:
- score < 0.2 → heuristic confident human → skip LLM
- score > 0.8 → heuristic confident AI → skip LLM
- 0.2 <= score <= 0.8 → ambiguous → LLM pass refines
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# ── Heuristic stock-phrase patterns ──────────────────────────────────────────
# Each pattern is (name, compiled_regex, score_increment).
# Presence of a pattern adds its increment to the raw score.
# Final heuristic score is clamped to [0.0, 1.0].

AI_STOCK_PHRASES: tuple[tuple[str, re.Pattern[str], float], ...] = (
    # Classic assistant opener phrases
    ("happy_to_help", re.compile(r"\bi'?d?\s+be\s+happy\s+to\s+help\b", re.IGNORECASE), 0.35),
    ("certainly", re.compile(r"^certainly[,!.]?\s", re.IGNORECASE | re.MULTILINE), 0.30),
    ("of_course", re.compile(r"^of\s+course[,!.]?\s", re.IGNORECASE | re.MULTILINE), 0.25),
    ("sure_here", re.compile(r"\bsure[,!]?\s+here'?s?\b", re.IGNORECASE), 0.30),
    ("absolutely", re.compile(r"^absolutely[,!.]?\s", re.IGNORECASE | re.MULTILINE), 0.25),
    ("great_question", re.compile(r"\bgreat\s+question\b", re.IGNORECASE), 0.35),
    ("happy_to_assist", re.compile(r"\bhappy\s+to\s+assist\b", re.IGNORECASE), 0.30),
    ("glad_to_help", re.compile(r"\bglad\s+to\s+help\b", re.IGNORECASE), 0.30),
    # Transition phrases
    ("lets_break_down", re.compile(r"\blet'?s?\s+break\s+(?:this|it|that)\s+down\b", re.IGNORECASE), 0.30),
    ("lets_dive_in", re.compile(r"\blet'?s?\s+dive\s+in\b", re.IGNORECASE), 0.20),
    ("in_summary", re.compile(r"\bin\s+summary[,:]", re.IGNORECASE), 0.20),
    ("in_conclusion", re.compile(r"\bin\s+conclusion[,:]", re.IGNORECASE), 0.20),
    ("to_summarize", re.compile(r"\bto\s+summarize[,:]", re.IGNORECASE), 0.20),
    ("to_recap", re.compile(r"\bto\s+recap[,:]", re.IGNORECASE), 0.15),
    ("hope_this_helps", re.compile(r"\bhope\s+this\s+helps\b", re.IGNORECASE), 0.25),
    ("feel_free", re.compile(r"\bfeel\s+free\s+to\b", re.IGNORECASE), 0.20),
    ("please_let_me_know", re.compile(r"\bplease\s+let\s+me\s+know\s+if\b", re.IGNORECASE), 0.20),
    ("dont_hesitate", re.compile(r"\bdon'?t\s+hesitate\s+to\b", re.IGNORECASE), 0.20),
    # Enumeration overuse (3+ items in tight numeric list)
    (
        "heavy_enumeration",
        re.compile(
            r"(?:(?:^|\n)\s*(?:\d+[\.\)]|[-*•])\s+.+\n){3,}",
            re.MULTILINE,
        ),
        0.25,
    ),
    # Em-dash overuse (AI models love em-dashes)
    ("em_dash_heavy", re.compile(r"(?:—){2,}|(?:[^—]—[^—].*){3,}", re.DOTALL), 0.15),
    # "As an AI" / "As a language model"
    ("as_an_ai", re.compile(r"\bas\s+an?\s+(?:ai|language\s+model|llm|large\s+language\s+model)\b", re.IGNORECASE), 0.50),
    # Polite boilerplate closing
    ("looking_forward", re.compile(r"\blooking\s+forward\s+to\b", re.IGNORECASE), 0.15),
    ("best_regards", re.compile(r"\bbest\s+regards\b|\bkind\s+regards\b", re.IGNORECASE), 0.10),
    # Co-pilot / AI attribution markers
    ("copilot_attribution", re.compile(r"\bco-?pilot\b.*\bgenerated\b|\bai.{0,20}generated\b", re.IGNORECASE), 0.60),
    ("chatgpt_mention", re.compile(r"\bchatgpt\b|\bgpt-[34]\b|\bgpt4\b", re.IGNORECASE), 0.40),
    # Robotic "This PR" description patterns
    ("this_pr_introduces", re.compile(r"\bthis\s+(?:pr|pull\s+request)\s+introduces\b", re.IGNORECASE), 0.20),
    ("this_commit_adds", re.compile(r"\bthis\s+commit\s+(?:adds|updates|fixes|refactors)\b", re.IGNORECASE), 0.15),
    # Excessive hedging language clusters
    (
        "excessive_hedging",
        re.compile(
            r"(?:\bit(?:'s| is)\s+(?:worth\s+noting|important\s+to\s+note|crucial\s+to|essential\s+to)\b)",
            re.IGNORECASE,
        ),
        0.15,
    ),
)

# Number of stock phrase patterns
STOCK_PHRASE_COUNT = len(AI_STOCK_PHRASES)

# Thresholds for LLM bypass
_HEURISTIC_CONFIDENT_LOW = 0.2   # Below this → human, skip LLM
_HEURISTIC_CONFIDENT_HIGH = 0.8  # Above this → AI, skip LLM

# Minimum text length to score (very short snippets are unreliable)
_MIN_SCORE_LENGTH = 30


# ── Heuristic scorer ─────────────────────────────────────────────────────────


def score_heuristic(text: str) -> float:
    """Return a raw heuristic contamination score 0.0–1.0.

    Matches each AI stock-phrase pattern and sums increments.
    Score is clamped to [0.0, 1.0].  Short or empty text returns 0.0.
    """
    if not text or len(text.strip()) < _MIN_SCORE_LENGTH:
        return 0.0

    total = 0.0
    for _name, pattern, increment in AI_STOCK_PHRASES:
        if pattern.search(text):
            total += increment

    return min(total, 1.0)


# ── LLM scorer ───────────────────────────────────────────────────────────────


async def _score_via_llm(text: str) -> float:
    """Call a FAST-tier LLM to score AI contamination probability.

    Returns a float in [0.0, 1.0].  On any failure returns 0.5 (uncertain).
    """
    try:
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent

        from app.core.models import ModelTier, get_model

        class ContaminationScore(BaseModel):
            score: float = Field(
                ge=0.0,
                le=1.0,
                description="AI contamination probability: 0.0 = human, 1.0 = AI-generated",
            )
            reasoning: str = Field(description="Brief one-sentence justification")

        snippet = text[:1200]  # Cap to avoid excessive token use
        model = get_model(ModelTier.FAST)
        agent: Agent[None, ContaminationScore] = Agent(
            model=model,
            output_type=ContaminationScore,
            system_prompt=(
                "You are an AI contamination detector. "
                "Given a text snippet, score the probability (0.0–1.0) that it was "
                "generated by an AI assistant (e.g. ChatGPT, Copilot) rather than "
                "written naturally by a human developer. "
                "Focus on: generic opener phrases, robotic enumeration, disclaimer "
                "language, and lack of personal voice. "
                "0.0 = clearly human-written (terse, idiosyncratic, typos OK). "
                "1.0 = clearly AI-generated (polished opener, numbered lists, "
                '"happy to help" etc).'
            ),
        )
        result = await agent.run(f"Score this text:\n\n{snippet}")
        return float(result.output.score)
    except Exception:
        logger.warning("LLM contamination scoring failed — defaulting to 0.5", exc_info=True)
        return 0.5


# ── Public API ────────────────────────────────────────────────────────────────


async def score_ai_contamination(text: str) -> float:
    """Score AI contamination for *text*, 0.0 (human) to 1.0 (AI).

    Strategy:
    - Heuristic pass always runs (zero cost).
    - LLM pass only runs if heuristic score is in the ambiguous middle zone
      [_HEURISTIC_CONFIDENT_LOW, _HEURISTIC_CONFIDENT_HIGH].
    - Never raises; returns 0.0 on error/empty text.
    """
    if not text or len(text.strip()) < _MIN_SCORE_LENGTH:
        return 0.0

    heuristic = score_heuristic(text)

    # Decisive heuristic result — no need for LLM
    if heuristic < _HEURISTIC_CONFIDENT_LOW or heuristic > _HEURISTIC_CONFIDENT_HIGH:
        return heuristic

    # Ambiguous zone — refine with LLM
    llm_score = await _score_via_llm(text)

    # Blend: weight LLM more heavily when it contradicts heuristic
    blended = (heuristic + llm_score * 2) / 3
    return round(min(max(blended, 0.0), 1.0), 4)


def classify_evidence_contamination(evidence: object) -> float:  # type: ignore[type-arg]
    """Synchronous wrapper: return the stored contamination score for an Evidence object.

    Returns the cached ``ai_contamination_score`` if present, otherwise 0.0.
    Call :func:`score_ai_contamination` (async) to compute and persist a fresh score.
    """
    score = getattr(evidence, "ai_contamination_score", None)
    return float(score) if score is not None else 0.0
