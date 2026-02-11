"""Memory builder — agentic multi-turn knowledge extraction.

Instead of trying to cram everything into a single system prompt, this module
builds a structured "memory bank" through a multi-turn process where the LLM
reads through evidence and takes notes like a researcher, building up factual
knowledge about the person that can be injected into chat as context.

The memory bank is SEPARATE from the spirit document. The spirit document
captures WHO they are (personality, style, values). The memory bank captures
WHAT they know (projects, technologies, experiences, opinions on specific topics).
"""

from __future__ import annotations

import json
import logging

from app.core.llm import llm_completion, llm_completion_json

logger = logging.getLogger(__name__)

RESEARCHER_SYSTEM = """\
You are a research assistant building a comprehensive knowledge profile of a
software developer. You are reading through their activity and taking structured
notes about FACTUAL information — not personality or style (that's handled
separately), but concrete knowledge:

- What projects they work on and what those projects do
- What technologies they use and their specific experience with each
- Technical opinions they hold on specific topics (with quotes)
- Problems they've solved and how
- Architecture decisions they've made and why
- Their areas of genuine expertise vs things they're learning
- Specific code patterns, tools, and workflows they prefer

Be thorough and specific. Cite evidence. This memory bank will be used to give
their AI clone factual grounding so it can answer questions knowledgeably."""

PASS1_PROMPT = """\
Read through all the evidence below for developer "{username}" and extract
EVERYTHING that forms their professional identity. This includes both factual
knowledge AND strongly-held opinions. Focus on:

1. **Projects**: What repos/projects do they maintain? What does each one do?
   What technologies does each use? What problem does it solve?
2. **Technical Expertise**: What languages, frameworks, tools do they demonstrably
   know? At what depth? (used once vs daily driver)
3. **Engineering Values & Tradeoffs**: What do they BELIEVE about software?
   What tradeoffs have they made and why? What hills would they die on?
   These should be STRONGLY OPINIONATED — real people have strong views.
   "I'd rather ship fast and fix bugs than over-engineer" or "Types save more
   time than they cost, always" — capture the STRENGTH of conviction.
4. **Technical Opinions**: Specific stances on technologies, practices, tools —
   with exact quotes when available. Not wishy-washy — what do they actually think?
5. **Experience**: Specific things they've built, debugged, optimized, deployed.
   Concrete accomplishments, not vague claims.
6. **Decision Patterns**: When faced with common engineering tradeoffs, what do
   they consistently choose? Speed vs quality? Abstraction vs simplicity?
   New tech vs proven tech? Capture the PATTERN, not just individual instances.
7. **Workflow**: How they work — their development environment, tools, processes,
   deployment practices.

## Evidence
{evidence}

---

Return a JSON object with this structure:
{{
  "projects": [
    {{
      "name": "project name",
      "description": "what it does / what problem it solves",
      "technologies": ["tech1", "tech2"],
      "role": "creator / maintainer / contributor",
      "evidence": "quote or specific reference"
    }}
  ],
  "expertise": [
    {{
      "technology": "name",
      "depth": "daily_driver / proficient / familiar / learning",
      "evidence": "how we know this — repo count, usage patterns, explicit mentions"
    }}
  ],
  "values_and_tradeoffs": [
    {{
      "value": "the engineering belief or principle",
      "strength": "core_belief / strong_preference / mild_preference",
      "tradeoff": "what they're willing to sacrifice for this value",
      "quote": "exact quote showing this value in action",
      "context": "where this was demonstrated"
    }}
  ],
  "opinions": [
    {{
      "topic": "what the opinion is about",
      "stance": "their specific position — be opinionated, not neutral",
      "quote": "exact quote if available",
      "context": "where/when they expressed this"
    }}
  ],
  "decision_patterns": [
    {{
      "tradeoff": "the recurring choice they face",
      "consistent_choice": "what they tend to choose",
      "reasoning": "why, based on evidence",
      "quote": "supporting quote"
    }}
  ],
  "experiences": [
    {{
      "description": "what they did",
      "technologies_used": ["tech1"],
      "evidence": "reference"
    }}
  ],
  "workflow": {{
    "editor": "what they use if known",
    "os": "if known",
    "tools": ["tools they use"],
    "practices": ["development practices they follow"]
  }}
}}

Extract everything you can find. Be OPINIONATED — this person has real views.
Don't sanitize or hedge their opinions. Return ONLY JSON."""

PASS2_PROMPT = """\
Here is a raw knowledge extraction for developer "{username}":

{raw_knowledge}

And here is additional evidence that may have been missed:

{additional_evidence}

Now CONSOLIDATE this into a clean, readable memory document. Format it as
markdown that will be injected into a chat system as context. The tone should
be factual and reference-like — imagine a colleague's notes about this person.

Structure:
```
# {username}'s Knowledge & Beliefs

## Projects
- **ProjectName**: Description. Built with [tech]. [Key detail or quote].
[repeat for each significant project]

## Technical Expertise
### Daily Drivers (high confidence)
- **Language/Tool**: Specifics about their usage, depth, preferences
### Proficient
- **Language/Tool**: ...
### Familiar With
- **Language/Tool**: ...

## Engineering Values & Tradeoffs
[This section should be STRONGLY OPINIONATED. Real developers have real views.]
- **Value**: Their stance, why they hold it, what they'd sacrifice for it.
  "Exact quote." [strength: core_belief/strong/mild]
[repeat — this is one of the most important sections]

## Technical Opinions
- **Topic**: Their specific stance — not hedged, not neutral.
  "Exact quote if available."
[repeat for each notable opinion]

## Decision Patterns
- When faced with [tradeoff], they consistently choose [X] because [Y].
[repeat for recurring patterns]

## Notable Experiences
- Description of specific thing they built/solved/deployed
[repeat]

## Workflow & Tools
- Editor, OS, deployment tools, development practices, etc.
```

Make it DENSE and OPINIONATED. This person has real views — capture them with
full conviction. No hedging, no "they sometimes prefer" — state it directly.
Every line should contain specific information that would help someone answer
a question AS this developer, with their actual opinions.
Return ONLY the markdown document."""


async def build_memory(username: str, evidence: str) -> str:
    """Build a structured memory bank through multi-turn exploration.

    Pass 1: Extract raw factual knowledge from evidence
    Pass 2: Consolidate into a clean, readable memory document

    Returns markdown memory content.
    """
    # Pass 1: Raw knowledge extraction
    logger.info("Memory builder pass 1: extracting raw knowledge for %s", username)
    pass1_prompt = PASS1_PROMPT.format(username=username, evidence=evidence)
    raw_knowledge = await llm_completion_json(pass1_prompt, system=RESEARCHER_SYSTEM)

    # Validate pass 1 output
    try:
        knowledge_data = json.loads(raw_knowledge)
    except json.JSONDecodeError:
        # Try stripping markdown fences
        cleaned = raw_knowledge.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        knowledge_data = json.loads(cleaned.strip())

    logger.info(
        "Pass 1 complete: %d projects, %d expertise areas, %d opinions",
        len(knowledge_data.get("projects", [])),
        len(knowledge_data.get("expertise", [])),
        len(knowledge_data.get("opinions", [])),
    )

    # Pass 2: Consolidate into readable memory document
    logger.info("Memory builder pass 2: consolidating memory for %s", username)

    # Truncate evidence for pass 2 to stay within context limits
    additional = evidence[:8000] if len(evidence) > 8000 else evidence

    pass2_prompt = PASS2_PROMPT.format(
        username=username,
        raw_knowledge=json.dumps(knowledge_data, indent=2),
        additional_evidence=additional,
    )
    memory_content = await llm_completion(pass2_prompt, system=RESEARCHER_SYSTEM)

    # Strip markdown code fences if present
    memory_content = memory_content.strip()
    if memory_content.startswith("```"):
        memory_content = memory_content.split("\n", 1)[1]
    if memory_content.endswith("```"):
        memory_content = memory_content.rsplit("```", 1)[0]
    memory_content = memory_content.strip()

    logger.info("Memory document built: %d chars", len(memory_content))
    return memory_content
