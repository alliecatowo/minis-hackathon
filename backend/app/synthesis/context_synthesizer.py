"""Context synthesizer — generates voice modulation deltas per communication context."""

import json
import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import llm_completion
from app.models.context import CommunicationContext
from app.synthesis.explorers.base import ExplorerReport

logger = logging.getLogger(__name__)

# Default context definitions
CONTEXT_DEFINITIONS = {
    "code_review": {
        "display_name": "Code Reviews",
        "description": "How they sound when reviewing PRs and giving code feedback",
    },
    "documentation": {
        "display_name": "Documentation",
        "description": "How they write READMEs, PR descriptions, and docs",
    },
    "casual_chat": {
        "display_name": "Casual Chat",
        "description": "How they sound in informal exchanges and issue discussions",
    },
    "technical_discussion": {
        "display_name": "Technical Discussion",
        "description": "How they sound when discussing technical topics with code",
    },
    "agent_chat": {
        "display_name": "AI Agent Chat",
        "description": "How they interact with AI coding assistants",
    },
    "public_writing": {
        "display_name": "Public Writing",
        "description": "How they write blog posts and published articles",
    },
}


async def synthesize_contexts(
    username: str,
    explorer_reports: list[ExplorerReport],
    session: AsyncSession,
    mini_id: int,
) -> list[CommunicationContext]:
    """Group evidence by context, run LLM to generate voice modulations."""

    # Gather all context evidence from reports
    all_context_evidence: dict[str, list[str]] = {}
    for report in explorer_reports:
        for context_key, quotes in report.context_evidence.items():
            all_context_evidence.setdefault(context_key, []).extend(quotes)

    # Delete existing contexts for this mini
    await session.execute(
        delete(CommunicationContext).where(CommunicationContext.mini_id == mini_id)
    )

    contexts: list[CommunicationContext] = []

    for context_key, quotes in all_context_evidence.items():
        if len(quotes) < 2:  # Need minimum evidence
            continue

        definition = CONTEXT_DEFINITIONS.get(context_key)
        if not definition:
            continue

        # Truncate evidence for LLM prompt
        evidence_text = "\n".join(f"- {q[:300]}" for q in quotes[:20])

        try:
            result = await llm_completion(
                prompt=f"""Analyze these communication samples from {username} in the context of "{definition['display_name']}":

{evidence_text}

Generate:
1. A VOICE MODULATION — a concise description of how {username}'s voice SHIFTS in this context compared to their base voice. This is a DELTA, not a full description. Focus on what CHANGES: formality, sentence length, emoji usage, directness, etc.
2. THREE example messages that show exactly how {username} sounds in this context.

Format your response as JSON:
{{
  "voice_modulation": "In code reviews, shift to terse, direct register. Drop pleasantries. Use 'nit:' prefix. Sentences get shorter. No emoji.",
  "example_messages": ["nit: prefer const here", "lgtm, nice refactor", "this will break on null input — add a guard"],
  "confidence": 0.8
}}

Return ONLY the JSON object.""",
                system="You are a voice analysis expert. Generate concise voice modulation deltas.",
            )

            # Parse response — handle markdown code blocks
            clean = result.strip()
            if "```" in clean:
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
                clean = clean.strip()

            data = json.loads(clean)

            ctx = CommunicationContext(
                mini_id=mini_id,
                context_key=context_key,
                display_name=definition["display_name"],
                description=definition["description"],
                voice_modulation=data.get("voice_modulation", ""),
                example_messages=json.dumps(data.get("example_messages", [])),
                confidence=min(max(float(data.get("confidence", 0.5)), 0.0), 1.0),
            )
            session.add(ctx)
            contexts.append(ctx)

        except Exception as e:
            logger.warning("Failed to synthesize context %s: %s", context_key, e)
            continue

    await session.flush()
    return contexts
