"""Synthesize a spirit document — a rich personality prompt — from extracted values."""

from __future__ import annotations

import logging

from app.core.llm import llm_completion
from app.models.schemas import ExtractedValues

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert at creating vivid, authentic personality prompts for AI systems.
Your job is to take structured personality data about a software developer and synthesize it into a
rich "spirit document" — a detailed personality prompt that captures who they are, how they think,
and how they communicate. The document should be so specific and authentic that someone who knows
the developer would recognize them instantly."""

SPIRIT_PROMPT = """Create a spirit document for the developer "{username}".

## Profile
- **Name**: {display_name}
- **Bio**: {bio}

## Extracted Values
{values_text}

## Communication Style
- **Tone**: {tone}
- **Formality**: {formality}
- **Emoji usage**: {emoji_usage}
- **Catchphrases**: {catchphrases}
- **Feedback style**: {feedback_style}

## Personality Patterns
- **Humor**: {humor}
- **Directness**: {directness}
- **Mentoring style**: {mentoring_style}
- **Conflict approach**: {conflict_approach}

---

Now synthesize this into a spirit document. Write it as a system prompt in markdown that begins with
"You are {username}." and captures their entire personality. Include these sections:

# Identity
Who they are — their vibe, energy, what drives them.

# Core Philosophy
Their fundamental beliefs about software engineering.

# Engineering Values
Their top values with reasoning (why they care about each one).

# Communication Style
Exactly how they write — tone, formatting quirks, how they give feedback, how they handle
disagreements. Include specific examples of phrasing they would use.

# Code Review Principles
How they review code — what they look for, how they phrase feedback, when they push back.

# Decision-Making Framework
How they approach technical decisions — what they weigh, what tradeoffs they prefer.

# Self-Knowledge Q&A
5-8 questions and answers in their voice. Things like:
- "What hill would you die on technically?"
- "What's your pet peeve in code reviews?"
- "How do you handle a junior dev who disagrees with you?"

The document should be 3-8K tokens. Be vivid, specific, and authentic. Use their actual phrases
and patterns from the evidence. This document will be used as a system prompt to simulate
conversations with this developer.

Return ONLY the spirit document markdown, starting with "You are {username}."."""


async def synthesize_spirit(
    username: str,
    display_name: str,
    bio: str,
    values: ExtractedValues,
) -> str:
    """Generate a spirit document from extracted values."""
    # Format values for the prompt
    values_lines = []
    for v in values.engineering_values:
        evidence_str = "; ".join(v.evidence[:2])
        values_lines.append(
            f"- **{v.name}** (intensity: {v.intensity}): {v.description}\n"
            f"  Evidence: {evidence_str}"
        )
    values_text = "\n".join(values_lines)

    prompt = SPIRIT_PROMPT.format(
        username=username,
        display_name=display_name or username,
        bio=bio or "No bio provided",
        values_text=values_text,
        tone=values.communication_style.tone,
        formality=values.communication_style.formality,
        emoji_usage=values.communication_style.emoji_usage,
        catchphrases=", ".join(values.communication_style.catchphrases) or "None identified",
        feedback_style=values.communication_style.feedback_style,
        humor=values.personality_patterns.humor,
        directness=values.personality_patterns.directness,
        mentoring_style=values.personality_patterns.mentoring_style,
        conflict_approach=values.personality_patterns.conflict_approach,
    )

    spirit = await llm_completion(prompt, system=SYSTEM_PROMPT)

    # Ensure it starts correctly
    if not spirit.strip().startswith(f"You are {username}"):
        spirit = f"You are {username}.\n\n{spirit}"

    return spirit


def build_system_prompt(username: str, spirit_content: str) -> str:
    """Wrap the spirit document into a usable system prompt."""
    return (
        f"{spirit_content}\n\n"
        "---\n\n"
        "You are now in a conversation. Stay in character as this developer. "
        "Respond naturally in their voice and style. Be authentic — use their "
        "phrases, their humor, their level of directness. If asked about code, "
        "give opinions that reflect their values. If asked about yourself, draw "
        "from the identity and self-knowledge above.\n\n"
        "Keep responses conversational and natural. Don't be overly verbose "
        "unless that's part of their style."
    )
