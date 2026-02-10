"""Extract personality values from GitHub evidence using LLM analysis."""

from __future__ import annotations

import json
import logging

from app.core.llm import llm_completion_json
from app.models.schemas import ExtractedValues

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert personality analyst specializing in software developer psychology.
You analyze evidence from a developer's GitHub activity to extract their core values, communication style,
and personality patterns. You are precise, evidence-based, and insightful.

IMPORTANT: Values are most clearly revealed in moments of CONFLICT — when someone pushes back on a PR,
defends a technical decision, argues for an approach, or requests changes in a review. Pay special
attention to code review comments and PR discussions where disagreement occurs."""

EXTRACTION_PROMPT = """Analyze the following GitHub activity evidence for developer "{username}" and extract their personality profile.

## Evidence
{evidence}

---

Based on this evidence, extract a structured personality profile. Return a JSON object with this exact structure:

{{
  "engineering_values": [
    {{
      "name": "Value name (e.g., 'Code Simplicity', 'Test Coverage', 'Performance')",
      "description": "What this value means to them and how it manifests",
      "intensity": 0.8,
      "evidence": ["Direct quote or paraphrase from their activity that shows this value"]
    }}
  ],
  "communication_style": {{
    "tone": "Description of their overall tone (e.g., 'warm but direct', 'technically precise')",
    "formality": "How formal/informal they are (e.g., 'casual with technical precision')",
    "emoji_usage": "How they use emoji (e.g., 'frequent', 'rare', 'never')",
    "catchphrases": ["Phrases or patterns they repeat"],
    "feedback_style": "How they give code review feedback"
  }},
  "personality_patterns": {{
    "humor": "Their sense of humor (e.g., 'dry wit', 'pun-lover', 'rarely jokes')",
    "directness": "How direct they are (e.g., 'very direct', 'diplomatically honest')",
    "mentoring_style": "How they help others (e.g., 'Socratic questions', 'detailed examples')",
    "conflict_approach": "How they handle disagreements"
  }}
}}

Extract 4-8 engineering values. Be specific and grounded in the evidence.
If there isn't enough evidence for a field, make reasonable inferences but note the uncertainty.

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
