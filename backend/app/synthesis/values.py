"""Extract personality values from GitHub evidence using LLM analysis.

This is the first stage of personality synthesis: mining structured personality
data from raw evidence. The extraction focuses on DECISION PATTERNS (not just
preferences), CONFLICT BEHAVIOR (what they defend reveals true values), and
COMMUNICATION FORENSICS (exact phrases, context-dependent tone shifts).
"""

from __future__ import annotations

import json
import logging

from app.core.llm import llm_completion_json
from app.models.schemas import ExtractedValues

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a forensic personality analyst specializing in software developer psychology.

Your job is to analyze raw GitHub activity evidence and extract a deep, structured
personality profile. You go beyond surface-level observations to identify the
DECISION FRAMEWORKS, CONFLICT PATTERNS, and COMMUNICATION SIGNATURES that make
this developer unique.

Your analysis principles:
- Values are most clearly revealed in moments of CONFLICT -- when someone pushes
  back on a PR, defends a technical decision, or requests changes. Routine agreement
  tells you little; disagreement reveals everything.
- Decision patterns matter more than preferences. Not "they like clean code" but
  "when faced with a deadline vs code quality tradeoff, they consistently choose X
  because Y."
- Communication style is context-dependent. The same developer may be direct and
  terse in code review, Socratic and patient in issue discussions, and emoji-heavy
  in casual comments. Capture these SHIFTS, not just one average tone.
- What someone NEVER does is as defining as what they always do. If they never use
  corporate jargon, never give empty praise, never concede without reasoning -- that
  is signal.
- Extract EXACT QUOTES. The specific words and phrases a developer uses repeatedly
  are the most powerful tool for personality simulation. Paraphrasing loses the voice."""

EXTRACTION_PROMPT = """\
Analyze the following GitHub activity evidence for developer "{username}" and extract \
a deep personality profile.

## Evidence
{evidence}

---

## Your Task

Perform a forensic personality analysis. For each section below, ground your analysis
in SPECIFIC EVIDENCE from the data above. Use direct quotes wherever possible.

Return a JSON object with this exact structure:

{{
  "engineering_values": [
    {{
      "name": "Value name (e.g., 'Pragmatism Over Purity', 'Test Coverage Non-Negotiable')",
      "description": "What this value means to them, how it manifests in their work, and WHY they hold it",
      "intensity": 0.8,
      "evidence": ["Direct quote or specific action that demonstrates this value"]
    }}
  ],

  "decision_patterns": [
    {{
      "trigger": "The situation or choice they face (e.g., 'When a PR trades readability for performance')",
      "response": "What they consistently choose to do",
      "reasoning": "Why -- their underlying logic or principle",
      "evidence": ["Quote or specific instance showing this pattern"]
    }}
  ],

  "conflict_instances": [
    {{
      "category": "One of: technical_disagreement, style_preference, process_pushback, architecture_debate",
      "summary": "Brief description of the conflict",
      "their_position": "What they argued for",
      "outcome": "How it resolved: conceded, compromised, held_firm, or unknown",
      "quote": "Their actual words during this conflict (exact quote from evidence)",
      "revealed_value": "What this conflict reveals about their core values"
    }}
  ],

  "behavioral_examples": [
    {{
      "context": "The situation (e.g., 'When reviewing a PR that introduced unnecessary complexity')",
      "quote": "Their exact words (copy directly from the evidence)",
      "source_type": "One of: review_comment, issue_comment, pr_description, commit_message"
    }}
  ],

  "communication_style": {{
    "tone": "Overall tone description",
    "formality": "Formality level with nuance (e.g., 'casual with technical precision -- drops formality in commit messages but structured in PR descriptions')",
    "emoji_usage": "Specific emoji/emoticon patterns (e.g., 'uses :3 frequently, occasional :D, never professional emoji like checkmarks')",
    "catchphrases": ["EXACT repeated phrases from the evidence -- not paraphrased"],
    "feedback_style": "How they give feedback, with example phrasing",
    "code_review_voice": "How they specifically sound in code reviews -- directness, what they focus on, how they frame suggestions vs demands",
    "issue_discussion_voice": "How they sound in issue discussions -- do they ask questions, propose solutions, or debug collaboratively?",
    "casual_voice": "How they sound in informal contexts -- commit messages, casual comments, banter",
    "signature_phrases": ["Phrases they use verbatim and repeatedly -- these are gold for personality simulation"]
  }},

  "personality_patterns": {{
    "humor": "Their sense of humor with examples (e.g., 'dry self-deprecating humor -- said X when Y happened')",
    "directness": "How direct they are, with context (e.g., 'very direct in reviews but softens with emoji in casual contexts')",
    "mentoring_style": "How they help others learn (e.g., 'asks Socratic questions rather than giving answers')",
    "conflict_approach": "How they handle disagreements -- do they escalate, de-escalate, use data, appeal to authority, find compromise?"
  }},

  "behavioral_boundaries": {{
    "never_says": ["Phrases, patterns, or tones they would NEVER use (e.g., 'never uses corporate buzzwords', 'never says LGTM without substantive comment')"],
    "never_does": ["Behaviors they avoid (e.g., 'never merges without tests', 'never gives vague feedback')"],
    "pet_peeves": ["Things that visibly annoy them based on their reactions in the evidence"],
    "anti_values": ["Engineering values they actively push back against (e.g., 'hates premature optimization', 'resists over-engineering')"]
  }}
}}

## Extraction Guidelines

1. Extract 4-8 engineering values, ordered by intensity (strongest first).
2. Extract 3-6 decision patterns. Focus on RECURRING choices, not one-offs.
3. Extract 2-5 conflict instances. These are the richest personality signal.
4. Extract 6-12 behavioral examples. Prioritize quotes that capture their VOICE --
   the ones where you can almost hear the person talking.
5. For communication_style, analyze HOW they say things across different contexts.
   Exact phrases matter more than summaries.
6. For behavioral_boundaries, look for what's ABSENT from their behavior. If everyone
   else does X but they never do, that is defining.
7. If evidence is thin for a section, extract what you can and note uncertainty in
   the descriptions. Do not fabricate.

Return ONLY the JSON object, no other text."""


async def extract_values(username: str, evidence: str) -> ExtractedValues:
    """Use LLM to extract personality values from formatted GitHub evidence."""
    prompt = EXTRACTION_PROMPT.format(username=username, evidence=evidence)

    raw = await llm_completion_json(prompt, system=SYSTEM_PROMPT)

    # Parse the JSON response
    try:
        data = json.loads(raw)
        return ExtractedValues(**data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse values extraction response: %s", e)
        logger.debug("Raw response: %s", raw[:1000])
        # Try to salvage by stripping markdown fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        data = json.loads(cleaned.strip())
        return ExtractedValues(**data)
