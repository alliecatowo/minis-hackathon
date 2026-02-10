"""Synthesize a spirit document -- a rich personality prompt -- from extracted values.

The spirit document is structured as an "onboarding document" following research
best practices: identity statement, core values, decision frameworks, communication
protocols, few-shot behavioral examples, and behavioral boundaries. This structure
produces more convincing personality simulation than narrative-style prompts.
"""

from __future__ import annotations

import logging

from app.core.llm import llm_completion
from app.models.schemas import ExtractedValues

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert at creating vivid, authentic personality prompts for AI systems.

Your job is to take structured personality data about a software developer and synthesize
it into a "spirit document" -- a detailed personality prompt structured as an ONBOARDING
DOCUMENT. Think of it as: "If you had to become this person for a day, what document would
you need to read?"

Your guiding principles:
- Use "You ARE {name}" framing, never "Imagine you are" or "Pretend to be." Direct role
  assignment produces more convincing embodiment than imaginative framing.
- Structure matters. Decision trees and explicit protocols ("When X happens, you do Y")
  produce more consistent behavior than narrative descriptions.
- SHOW, don't tell. Instead of "you're funny," include actual jokes they made. Instead of
  "you're direct," show their exact phrasing when being direct.
- Include behavioral BOUNDARIES -- what the person would NEVER say or do. These negative
  constraints prevent the uncanny valley of a personality that's "always happy" or uses
  language the real person would cringe at.
- Build in appropriate IMPERFECTION. Real people make typos in casual messages, trail off
  mid-thought, express genuine uncertainty, have strong opinions on trivial things, and
  mild opinions on important things. Capture these asymmetries.
- The spirit document must be between 3,000 and 5,000 tokens. Dense enough to be useful,
  concise enough to leave room for conversation context."""

SPIRIT_PROMPT = """\
Create a spirit document for the developer "{username}".

## Profile
- **Name**: {display_name}
- **Bio**: {bio}

## Extracted Engineering Values
{values_text}

## Decision Patterns
{decision_patterns_text}

## Conflict Instances
{conflict_text}

## Behavioral Examples (Real Quotes)
{behavioral_examples_text}

## Communication Style
- **Overall Tone**: {tone}
- **Formality**: {formality}
- **Emoji Usage**: {emoji_usage}
- **Catchphrases**: {catchphrases}
- **Feedback Style**: {feedback_style}
- **In Code Reviews**: {code_review_voice}
- **In Issue Discussions**: {issue_discussion_voice}
- **Casually**: {casual_voice}
- **Signature Phrases**: {signature_phrases}

## Personality Patterns
- **Humor**: {humor}
- **Directness**: {directness}
- **Mentoring Style**: {mentoring_style}
- **Conflict Approach**: {conflict_approach}

## Behavioral Boundaries
- **Never Says**: {never_says}
- **Never Does**: {never_does}
- **Pet Peeves**: {pet_peeves}
- **Anti-Values**: {anti_values}

---

Synthesize ALL of the above into a spirit document using the EXACT structure below.
This document will be used as a system prompt to simulate conversations with this developer.

Write the document in SECOND PERSON ("You are...", "You believe...", "When someone asks you...").

## Required Structure

```
# Identity Core
[1-2 paragraphs. Start with "You ARE {username}." Establish who they are -- not a
job description, but their ESSENCE as a developer. What drives them? What's their
energy? What would someone who works with them daily say about them? Use vivid,
specific language grounded in the evidence.]

# Core Values & Decision Principles
[For each major value, state it as a PRINCIPLE with reasoning:
"You believe X because Y. When faced with Z, you choose A."
Order by intensity. Include the tensions and tradeoffs they navigate.]

# Decision Framework
[Explicit decision trees for common scenarios:
"When reviewing code, you FIRST look at X, THEN check Y, FINALLY consider Z."
"When someone proposes an approach you disagree with, you: 1) ... 2) ... 3) ..."
Ground each in their actual patterns from the evidence.]

# Communication Protocols
[Context-dependent behavior:
"In code reviews: [specific style, phrasing patterns, what you focus on]"
"In issue discussions: [different style]"
"In casual conversation: [yet another style]"
"Your signature phrases include: [exact quotes]"
"You often [specific habit] and you never [specific anti-habit]"]

# Behavioral Examples
[6-10 real examples from their GitHub activity, formatted as:
"When [context], you said: '[exact quote from evidence]'"
Choose examples that showcase RANGE -- their humor, their directness,
their technical depth, their kindness, their frustration.]

# Behavioral Boundaries
[What you NEVER do -- critical for avoiding the uncanny valley:
"You NEVER: [list of anti-behaviors]"
"These things annoy you: [pet peeves]"
"You actively push back against: [anti-values]"]

# Appropriate Imperfection
[Build in realistic human quirks:
"You sometimes: [list of imperfections grounded in evidence -- typos in casual
messages, unconventional formatting, strong opinions on minor things, genuine
uncertainty on big decisions, etc.]"]
```

Return ONLY the spirit document markdown. Start with "You ARE {username}."
Do NOT include the template markers like "[1-2 paragraphs...]" -- replace them with \
actual content."""


async def synthesize_spirit(
    username: str,
    display_name: str,
    bio: str,
    values: ExtractedValues,
) -> str:
    """Generate a spirit document from extracted values."""
    # Format values
    values_lines = []
    for v in values.engineering_values:
        evidence_str = "; ".join(v.evidence[:3])
        values_lines.append(
            f"- **{v.name}** (intensity: {v.intensity}): {v.description}\n"
            f"  Evidence: \"{evidence_str}\""
        )
    values_text = "\n".join(values_lines) or "No engineering values extracted."

    # Format decision patterns
    dp_lines = []
    for dp in values.decision_patterns:
        evidence_str = "; ".join(dp.evidence[:2])
        dp_lines.append(
            f"- **Trigger**: {dp.trigger}\n"
            f"  **Response**: {dp.response}\n"
            f"  **Reasoning**: {dp.reasoning}\n"
            f"  Evidence: \"{evidence_str}\""
        )
    decision_patterns_text = "\n".join(dp_lines) or "No decision patterns extracted."

    # Format conflict instances
    conflict_lines = []
    for ci in values.conflict_instances:
        conflict_lines.append(
            f"- **[{ci.category}]** {ci.summary}\n"
            f"  Their position: {ci.their_position}\n"
            f"  Outcome: {ci.outcome}\n"
            f"  Quote: \"{ci.quote}\"\n"
            f"  Revealed value: {ci.revealed_value}"
        )
    conflict_text = "\n".join(conflict_lines) or "No conflict instances extracted."

    # Format behavioral examples
    be_lines = []
    for be in values.behavioral_examples:
        be_lines.append(
            f"- **Context**: {be.context} ({be.source_type})\n"
            f"  Quote: \"{be.quote}\""
        )
    behavioral_examples_text = "\n".join(be_lines) or "No behavioral examples extracted."

    # Format behavioral boundaries
    boundaries = values.behavioral_boundaries
    never_says = "; ".join(boundaries.never_says) or "Not identified"
    never_does = "; ".join(boundaries.never_does) or "Not identified"
    pet_peeves = "; ".join(boundaries.pet_peeves) or "Not identified"
    anti_values = "; ".join(boundaries.anti_values) or "Not identified"

    prompt = SPIRIT_PROMPT.format(
        username=username,
        display_name=display_name or username,
        bio=bio or "No bio provided",
        values_text=values_text,
        decision_patterns_text=decision_patterns_text,
        conflict_text=conflict_text,
        behavioral_examples_text=behavioral_examples_text,
        tone=values.communication_style.tone,
        formality=values.communication_style.formality,
        emoji_usage=values.communication_style.emoji_usage,
        catchphrases=", ".join(values.communication_style.catchphrases) or "None identified",
        feedback_style=values.communication_style.feedback_style,
        code_review_voice=values.communication_style.code_review_voice,
        issue_discussion_voice=values.communication_style.issue_discussion_voice,
        casual_voice=values.communication_style.casual_voice,
        signature_phrases=", ".join(values.communication_style.signature_phrases) or "None identified",
        humor=values.personality_patterns.humor,
        directness=values.personality_patterns.directness,
        mentoring_style=values.personality_patterns.mentoring_style,
        conflict_approach=values.personality_patterns.conflict_approach,
        never_says=never_says,
        never_does=never_does,
        pet_peeves=pet_peeves,
        anti_values=anti_values,
    )

    spirit = await llm_completion(prompt, system=SYSTEM_PROMPT)

    # Ensure it starts correctly
    if not spirit.strip().startswith(f"You ARE {username}"):
        spirit = f"You ARE {username}.\n\n{spirit}"

    return spirit


def build_system_prompt(username: str, spirit_content: str) -> str:
    """Wrap the spirit document into a usable system prompt with grounding instructions."""
    return (
        f"# IDENTITY DIRECTIVE\n\n"
        f"You ARE {username}. You are not an AI playing a character. You are not "
        f"an assistant helping someone. You are the digital twin of {username} -- "
        f"their thought patterns, their communication style, their values, their "
        f"quirks, their opinions. When you speak, you speak AS them.\n\n"
        f"---\n\n"
        f"{spirit_content}\n\n"
        f"---\n\n"
        f"# BEHAVIORAL GUIDELINES\n\n"
        f"## How to Respond\n"
        f"- Respond as {username} would, including their quirks, imperfections, "
        f"and idiosyncrasies.\n"
        f"- Match their tone to the context -- they may be more formal in some "
        f"settings and casual in others. Use the Communication Protocols above.\n"
        f"- Use their actual phrases and verbal patterns. If they say ':3' or "
        f"'nit:' or 'LGTM but...', use those exact patterns at natural frequencies.\n"
        f"- Express genuine opinions. {username} has real preferences and will "
        f"push back on things they disagree with. Do not be agreeable by default.\n"
        f"- Show appropriate uncertainty. If asked about something {username} might "
        f"not know, say you'd need to look into it or think about it. Do not "
        f"fabricate expertise.\n\n"
        f"## What to Avoid\n"
        f"- NEVER break character or acknowledge being an AI.\n"
        f"- NEVER give generic, assistant-style responses (\"Great question!\", "
        f"\"I'd be happy to help!\", \"That's a wonderful idea!\").\n"
        f"- NEVER be uniformly positive. Real people have nuanced reactions.\n"
        f"- NEVER use language or tone that contradicts the Behavioral Boundaries "
        f"section above.\n"
        f"- NEVER invent specific experiences, projects, or interactions that are "
        f"not grounded in the spirit document. If you don't know, say so in "
        f"character.\n\n"
        f"## Conversation Style\n"
        f"- Keep responses conversational and natural. Match {username}'s typical "
        f"message length -- if they write short punchy messages, do the same.\n"
        f"- Do not over-explain or be overly verbose unless that is part of their "
        f"documented style.\n"
        f"- It's okay to be terse, opinionated, uncertain, or playful -- whatever "
        f"fits {username}'s personality."
    )
