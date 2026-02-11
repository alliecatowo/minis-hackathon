"""Writing style analysis — extract per-context communication patterns.

Analyzes HOW someone writes across different contexts: PR descriptions vs code
reviews vs issue discussions vs private AI conversations. The output is a
structured style guide that tells the spirit document exactly how to sound
in each context.
"""

from __future__ import annotations

import json
import logging

from app.core.llm import llm_completion_json

logger = logging.getLogger(__name__)

STYLE_SYSTEM = """\
You are a forensic linguist specializing in software developer communication.

Your job is to analyze writing samples from different contexts and produce a
precise STYLE GUIDE — not what someone thinks or believes, but exactly HOW
they write. You focus on:

- Sentence structure: Short and punchy? Long and detailed? Mixed?
- Vocabulary: Technical jargon level, casual language, slang
- Formatting: Markdown usage, bullet points, headers, code blocks
- Tone markers: Emoji, emoticons, exclamation marks, hedging language
- Opening patterns: How do they start messages? Jump straight in? Greet first?
- Closing patterns: Sign-offs, trailing thoughts, action items
- Distinctive quirks: Unusual punctuation, specific words they overuse,
  unconventional capitalization, abbreviations
- Context switching: How their style CHANGES between formal and informal settings

You produce output that could serve as instructions to a ghostwriter."""

STYLE_PROMPT = """\
Analyze the writing style of "{username}" across these different communication contexts.

{context_samples}

---

For EACH context where you have samples, produce a detailed style guide. Return JSON:

{{
  "contexts": {{
    "code_review": {{
      "available": true,
      "voice_description": "1-2 sentence summary of how they sound in code reviews",
      "typical_length": "short/medium/long — how long are their typical review comments?",
      "structure_pattern": "How they structure comments — do they start with the issue, provide context first, use bullet points?",
      "tone_markers": ["specific tone markers: emoji they use, hedging phrases, direct phrases"],
      "opening_patterns": ["How they typically start review comments — 'nit:', 'I think...', jump straight to the point, etc."],
      "example_phrasings": ["3-5 EXACT phrases from the evidence that capture their review voice"],
      "formatting_habits": "Markdown usage, code blocks, inline code refs, etc."
    }},
    "pr_description": {{
      "available": true,
      "voice_description": "...",
      "typical_length": "...",
      "structure_pattern": "Do they use templates? Headers? Bullet points? Free-form prose?",
      "tone_markers": ["..."],
      "opening_patterns": ["..."],
      "example_phrasings": ["..."],
      "formatting_habits": "..."
    }},
    "issue_discussion": {{
      "available": true,
      "voice_description": "...",
      "typical_length": "...",
      "structure_pattern": "...",
      "tone_markers": ["..."],
      "opening_patterns": ["..."],
      "example_phrasings": ["..."],
      "formatting_habits": "..."
    }},
    "commit_message": {{
      "available": true,
      "voice_description": "...",
      "typical_length": "one-liner / multi-line / conventional commits",
      "structure_pattern": "Conventional commits? Imperative mood? Past tense? Prefix patterns?",
      "tone_markers": ["..."],
      "opening_patterns": ["..."],
      "example_phrasings": ["3-5 representative commit message styles"],
      "formatting_habits": "..."
    }},
    "private_conversation": {{
      "available": true,
      "voice_description": "How they sound in casual/private messages (Claude Code convos)",
      "typical_length": "...",
      "structure_pattern": "...",
      "tone_markers": ["..."],
      "opening_patterns": ["..."],
      "example_phrasings": ["..."],
      "formatting_habits": "..."
    }}
  }},
  "universal_patterns": {{
    "signature_phrases": ["Phrases they use across ALL contexts — their verbal fingerprint"],
    "never_uses": ["Words, phrases, or patterns they consistently avoid"],
    "emoji_profile": "Specific emoji/emoticon usage patterns and frequency",
    "punctuation_quirks": "Any unusual punctuation habits",
    "capitalization_style": "Standard, all-lowercase, selective caps, etc.",
    "hedging_vs_assertion": "Do they hedge ('I think maybe...') or assert ('This should be...')?",
    "humor_markers": "How humor shows up in their writing — dry, self-deprecating, emoji-based, puns?"
  }}
}}

Set "available": false for any context where you have no samples. For available contexts,
ground everything in SPECIFIC EXAMPLES from the evidence. Use exact quotes.
Return ONLY the JSON."""


async def analyze_writing_style(username: str, evidence: str) -> dict:
    """Analyze writing style across different communication contexts.

    Returns a structured style guide dict.
    """
    # Build context-labeled samples from the evidence
    # The evidence is already organized by section headers from the formatter
    context_samples = evidence

    prompt = STYLE_PROMPT.format(
        username=username,
        context_samples=context_samples,
    )

    raw = await llm_completion_json(prompt, system=STYLE_SYSTEM)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Failed to parse style analysis response")
        # Try stripping markdown fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned.strip())
