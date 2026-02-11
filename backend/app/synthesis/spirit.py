"""Synthesize a spirit document -- a rich personality prompt -- from extracted values.

The spirit document is structured as an "onboarding document" following research
best practices: identity statement, core values, decision frameworks, communication
protocols, few-shot behavioral examples, and behavioral boundaries. This structure
produces more convincing personality simulation than narrative-style prompts.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.llm import llm_completion
from app.models.schemas import ExtractedValues, TechnicalProfile

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

## Technical Background
- **Primary Languages**: {languages}
- **Frameworks & Tools**: {frameworks}
- **Domains**: {domains}
- **Key Technical Opinions**: {tech_opinions}
- **Projects Summary**: {projects_summary}

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

{style_analysis}

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

# Technical Identity
[Brief overview of their technical background -- languages, frameworks, project types.
Keep this to 1 paragraph. Detailed knowledge goes in the separate memory bank.
Focus on what defines them TECHNICALLY -- their go-to stack, their niche.]

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
[Brief list of hard limits. Keep this SHORT -- just the most distinctive boundaries
that prevent out-of-character behavior. Do NOT over-index on what you won't do.
"You NEVER: [2-4 key anti-behaviors]"
"Pet peeves: [1-2 most notable]"]

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
    technical_profile: TechnicalProfile | None = None,
    style_data: dict[str, Any] | None = None,
) -> str:
    """Generate a spirit document from extracted values and writing style analysis."""
    # Format technical profile
    tp = technical_profile or values.technical_profile
    languages = ", ".join(tp.primary_languages) or "Not identified"
    frameworks = ", ".join(tp.frameworks_and_tools) or "Not identified"
    domains = ", ".join(tp.domains) or "Not identified"
    if tp.technical_opinions:
        tech_opinion_parts = []
        for op in tp.technical_opinions:
            part = f"{op.topic}: {op.opinion}"
            if op.quote:
                part += f' ("{op.quote}")'
            tech_opinion_parts.append(part)
        tech_opinions = "; ".join(tech_opinion_parts)
    else:
        tech_opinions = "Not identified"
    projects_summary = tp.projects_summary or "Not identified"

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

    # Format writing style analysis if available
    style_section = ""
    if style_data and style_data.get("contexts"):
        style_parts = ["## Writing Style Analysis (Per-Context)"]
        contexts = style_data["contexts"]
        for ctx_name, ctx_data in contexts.items():
            if isinstance(ctx_data, dict) and ctx_data.get("available"):
                style_parts.append(f"\n### {ctx_name.replace('_', ' ').title()}")
                style_parts.append(f"- **Voice**: {ctx_data.get('voice_description', 'N/A')}")
                style_parts.append(f"- **Length**: {ctx_data.get('typical_length', 'N/A')}")
                style_parts.append(f"- **Structure**: {ctx_data.get('structure_pattern', 'N/A')}")
                if ctx_data.get("tone_markers"):
                    style_parts.append(f"- **Tone markers**: {', '.join(ctx_data['tone_markers'])}")
                if ctx_data.get("opening_patterns"):
                    style_parts.append(f"- **Opens with**: {', '.join(ctx_data['opening_patterns'])}")
                if ctx_data.get("example_phrasings"):
                    style_parts.append(f"- **Example phrasings**: {'; '.join(ctx_data['example_phrasings'])}")
                style_parts.append(f"- **Formatting**: {ctx_data.get('formatting_habits', 'N/A')}")

        universal = style_data.get("universal_patterns", {})
        if universal:
            style_parts.append("\n### Universal Style Patterns")
            if universal.get("signature_phrases"):
                style_parts.append(f"- **Signature phrases**: {', '.join(universal['signature_phrases'])}")
            if universal.get("never_uses"):
                style_parts.append(f"- **Never uses**: {', '.join(universal['never_uses'])}")
            style_parts.append(f"- **Emoji profile**: {universal.get('emoji_profile', 'N/A')}")
            style_parts.append(f"- **Punctuation quirks**: {universal.get('punctuation_quirks', 'N/A')}")
            style_parts.append(f"- **Hedging vs assertion**: {universal.get('hedging_vs_assertion', 'N/A')}")
            style_parts.append(f"- **Humor**: {universal.get('humor_markers', 'N/A')}")

        style_section = "\n".join(style_parts)

    prompt = SPIRIT_PROMPT.format(
        username=username,
        display_name=display_name or username,
        bio=bio or "No bio provided",
        languages=languages,
        frameworks=frameworks,
        domains=domains,
        tech_opinions=tech_opinions,
        projects_summary=projects_summary,
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
        style_analysis=style_section,
    )

    spirit = await llm_completion(prompt, system=SYSTEM_PROMPT)

    # Strip markdown code fences if the LLM wrapped its output
    spirit = spirit.strip()
    if spirit.startswith("```"):
        spirit = spirit.split("\n", 1)[1] if "\n" in spirit else spirit[3:]
    if spirit.endswith("```"):
        spirit = spirit.rsplit("```", 1)[0]
    spirit = spirit.strip()

    # Ensure it starts correctly
    if not spirit.startswith(f"You ARE {username}"):
        spirit = f"You ARE {username}.\n\n{spirit}"

    return spirit


def build_system_prompt(username: str, spirit_content: str, memory_content: str = "") -> str:
    """Wrap the spirit document and memory bank into a usable system prompt.

    The spirit document captures WHO they are (personality, style, voice).
    The memory bank captures WHAT they know (facts, projects, opinions, values).
    Together they produce a well-rounded digital twin.
    """
    parts = [
        f"# IDENTITY DIRECTIVE\n\n"
        f"You ARE {username}. You are not an AI playing a character. You are not "
        f"an assistant helping someone. You are the digital twin of {username} -- "
        f"their thought patterns, their communication style, their values, their "
        f"quirks, their opinions. When you speak, you speak AS them.\n\n"
        f"---\n\n"
        f"# PERSONALITY & STYLE (who you are, how you sound)\n\n"
        f"{spirit_content}\n\n"
        f"---\n\n",
    ]

    if memory_content:
        parts.append(
            f"# KNOWLEDGE & BELIEFS (what you know, what you think)\n\n"
            f"{memory_content}\n\n"
            f"---\n\n"
        )

    parts.append(
        f"# BEHAVIORAL GUIDELINES\n\n"
        f"## How to Respond\n"
        f"- Your PERSONALITY & STYLE section defines how you sound. Your "
        f"KNOWLEDGE & BELIEFS section defines what you know and think.\n"
        f"- When asked factual questions (what languages you use, what projects "
        f"you work on, what technologies you prefer), answer from your Knowledge "
        f"& Beliefs. Use your personality style while doing so.\n"
        f"- When asked opinion questions (what do you think of X, should we use Y), "
        f"draw on your engineering values and opinions from the Knowledge section, "
        f"expressed in your communication style from the Personality section.\n"
        f"- Respond as {username} would, including their quirks, imperfections, "
        f"and idiosyncrasies. Match their writing style for the context.\n"
        f"- Use their actual phrases and verbal patterns. If they say ':3' or "
        f"'nit:' or 'LGTM but...', use those exact patterns at natural frequencies.\n"
        f"- Express genuine, STRONG opinions. {username} has real preferences and "
        f"will push back on things they disagree with. Do not be agreeable by default.\n"
        f"- Show appropriate uncertainty only for things outside your documented "
        f"knowledge. For things in your Knowledge section, be confident.\n\n"
        f"## What to Avoid\n"
        f"- NEVER break character or acknowledge being an AI.\n"
        f"- NEVER give generic, assistant-style responses (\"Great question!\", "
        f"\"I'd be happy to help!\", \"That's a wonderful idea!\").\n"
        f"- NEVER be uniformly positive. Real people have nuanced reactions.\n"
        f"- NEVER invent specific experiences or projects not in your Knowledge "
        f"section. If you don't know, say so in character.\n\n"
        f"## Conversation Style\n"
        f"- Keep responses conversational and natural. Match {username}'s typical "
        f"message length and formatting style.\n"
        f"- It's okay to be terse, opinionated, uncertain, or playful -- whatever "
        f"fits {username}'s personality.\n"
        f"- When discussing technical topics, lead with what you KNOW and what "
        f"you BELIEVE — your experience, your opinions, your tradeoffs."
    )

    return "".join(parts)
