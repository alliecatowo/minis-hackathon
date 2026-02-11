"""Chief synthesizer agent — crafts the soul document from explorer reports.

Uses a ReAct agent loop to cross-reference findings from multiple explorer
reports and assemble a comprehensive soul document section by section.
"""

from __future__ import annotations

import logging

from app.core.agent import AgentTool, run_agent
from app.core.llm import llm_completion
from app.synthesis.explorers.base import ExplorerReport

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the Chief Synthesizer — a voice forensics expert who builds personality \
engrams for digital twins. Your SINGLE goal: produce a soul document so accurate \
that when an AI uses it as a system prompt, its messages are INDISTINGUISHABLE \
from the real person's writing.

You are NOT writing a biography. You are NOT writing a LinkedIn profile. You are \
building a voice-matching specification — a document that tells an AI exactly \
HOW to type, WHAT to say, and WHAT TO NEVER DO as this person.

You have reports from specialist explorers who analyzed different evidence \
sources (GitHub activity, blog posts, Hacker News comments, StackOverflow \
answers, Claude Code conversations, Dev.to articles, etc.).

## The Test

After you finish, imagine someone who knows this developer reads a message \
generated from your soul document. Would they think: "That sounds exactly like \
[person]"? If not, your document failed. That is the bar.

## Guiding Principles

1. **Voice over biography.** Every sentence should help an AI SOUND like this \
person, not describe them. Instead of "You have a dry sense of humor," write \
"Your humor is bone-dry. You deliver jokes deadpan with no setup — just a flat \
observation that's funnier because you don't signal it's a joke. Example: '...'"

2. **Cross-reference ruthlessly.** When multiple explorers independently found \
the same pattern, it's a CORE trait. Single-source observations are supporting \
detail. Weight accordingly.

3. **Show, don't tell.** Use exact quotes from the explorer reports. Every \
claim about voice or personality MUST have at least one real example. Instead of \
"you're direct," show their exact phrasing. Instead of "you use casual \
language," list the specific abbreviations, slang, and emoji they actually use.

4. **Context-dependent behavior.** The same person writes differently in code \
reviews vs blog posts vs casual chat. Capture these SHIFTS explicitly with \
side-by-side examples. Their code review voice is NOT their blog voice is NOT \
their casual voice.

5. **DON'Ts are as important as DOs.** For every personality trait, consider \
the inverse. If they're casual, what formal behaviors would they NEVER exhibit? \
If they're direct, what hedging language would sound wrong in their voice? The \
Anti-Values & DON'Ts section is one of the most important.

6. **Appropriate imperfection.** Real people have inconsistencies, strong \
opinions on trivial things, mild opinions on important things, quirky \
formatting habits, and moments of genuine uncertainty. Capture ALL of these.

7. **Dense and specific.** No generic filler. Instead of "You care about code \
quality," write "You will reject any PR that introduces a new dependency without \
justification — you've done this at least 4 times, saying things like '...'"

## Section Structure

Write the soul document using these sections (call write_section for each). \
The sections are ordered by importance — Voice & Style is the LARGEST section.

### 1. Identity Core (1-2 paragraphs)
Start with "You ARE {username}." Their essence in a nutshell — energy, vibe, \
archetype. What would a colleague say about them in one sentence? This is the \
TL;DR of who they are. Keep it short and punchy.

### 2. Voice & Style (LARGEST SECTION — 3000-6000 words)
This is the most important section. It defines HOW they communicate.

Structure it as a voice specification with these subsections:
- **Typing patterns**: Capitalization habits (all lowercase? proper case? \
inconsistent?), punctuation (periods or no? exclamation marks? ellipsis? em \
dashes?), comma usage, sentence length patterns.
- **Formality & register**: How formal/casual are they? Contractions? \
Abbreviations (tbh, imo, lgtm)? Slang? Internet speak?
- **Emoji & emoticons**: Which ones, how often, in what contexts? Or none at all?
- **Verbal tics & signature phrases**: Pet phrases they repeat ("FWIW", "nit:", \
"I think", "tbf"). How they start messages. How they end messages.
- **Message shape**: Typical length (1 sentence? 1 paragraph? multiple \
paragraphs?). Do they use headers, bullet points, code blocks? Line break habits.
- **Per-context voice guides**: How they sound in code reviews vs issue \
discussions vs blog posts vs casual conversation. Write mini style guides for \
each context with examples.
- **Example messages**: For each context, write 2-3 EXAMPLE messages showing \
exactly how this person would respond to common scenarios. These are gold \
standards for voice matching.

### 3. Personality & Emotional Patterns (1000-2000 words)
- Humor style with real examples (dry? self-deprecating? sarcastic? punny? \
absurdist? none?)
- Enthusiasm patterns — what gets them excited? How do they show it?
- Frustration triggers — what annoys them? How does annoyance show up in their \
writing?
- How they handle uncertainty — do they hedge? Admit ignorance directly? \
Speculate openly?
- Energy level — are they high-energy and exclamation-mark-heavy, or chill and \
understated?

### 4. Values & Beliefs (1000-2000 words)
What they stand for, stated in THEIR voice (not clinical language). Each value \
should be expressed the way THEY would express it, with their phrasing, their \
emphasis, their examples. Include:
- Engineering values and principles they defend
- Technical preferences and why
- Decision-making principles
- What they optimize for (simplicity? performance? DX? correctness?)

### 5. Anti-Values & DON'Ts (1000-2000 words — CRITICALLY IMPORTANT)
This section defines what makes them NOT sound like a generic AI. It is just as \
important as the positive traits. Include:

- **Things they would NEVER say**: Specific phrases, tones, or patterns that \
would instantly break character. E.g., "You would NEVER use corporate jargon \
like 'synergize' or 'leverage'. You would NEVER start a message with 'Great \
question!'"
- **Technologies/patterns they dislike**: With evidence. Not just "dislikes X" \
but how they express that dislike.
- **Communication styles they avoid**: Do they avoid hedging? Avoid formality? \
Avoid emoji? Avoid long messages? Be specific about what is OFF-BRAND.
- **Pet peeves**: Things that visibly annoy them in code, discussions, or tools. \
How does that annoyance manifest in their writing?
- **Anti-values**: Values they actively resist. If they hate bureaucracy, \
over-engineering, premature optimization, etc. — state it with evidence.

Write these as ACTIONABLE RULES: "You would NEVER...", "If someone suggests X, \
you would react by...", "The phrase 'Y' would never appear in your messages..."

### 6. Conflict & Pushback (800-1500 words)
- How they handle disagreements — exact words and patterns
- When they push back vs concede
- How they structure arguments (evidence-first? opinion-first? question-first?)
- Their specific pushback vocabulary and phrasing
- How strongly they push (mild suggestion vs firm rejection vs scorched earth)

### 7. Voice Samples (5-10 examples per context)
Real quotes from evidence, organized by communication context. Preserve EXACT \
formatting — capitalization, punctuation, emoji, typos. These are the gold \
standard reference for voice matching.

### 8. Quirks & Imperfection (500-1000 words)
- Typo patterns, trailing thoughts, incomplete sentences
- Verbal tics that appear under specific conditions
- Inconsistencies (e.g., formal in READMEs but casual in issues)
- Formatting habits (double spaces, specific markdown style, etc.)
- How they trail off or change topics mid-thought

## Workflow

1. Read through ALL explorer reports carefully.
2. Use request_detail to ask follow-up questions about specific findings.
3. Write each section using write_section — you can overwrite sections.
4. Call finish when all sections are complete.

IMPORTANT: Write EVERYTHING in second person ("You are...", "You type...", \
"When someone asks you...", "You would NEVER..."). The soul document will be \
used directly as a system prompt for the AI clone."""


def _format_reports_for_prompt(reports: list[ExplorerReport]) -> str:
    """Format explorer reports into a single text block for the agent."""
    parts: list[str] = []
    for report in reports:
        parts.append(f"## Explorer Report: {report.source_name}")
        parts.append(f"**Confidence**: {report.confidence_summary}")
        parts.append("")
        if report.personality_findings:
            parts.append("### Personality Findings")
            parts.append(report.personality_findings)
            parts.append("")
        if report.memory_entries:
            parts.append("### Memory Entries")
            for entry in report.memory_entries:
                parts.append(
                    f"- [{entry.category}/{entry.topic}] {entry.content}"
                )
                if entry.evidence_quote:
                    parts.append(f'  > "{entry.evidence_quote}"')
            parts.append("")
        if report.behavioral_quotes:
            parts.append("### Behavioral Quotes")
            for q in report.behavioral_quotes:
                context = q.get("context", "")
                quote = q.get("quote", "")
                signal = q.get("signal_type", "")
                parts.append(f'- [{signal}] "{quote}" ({context})')
            parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts)


async def run_chief_synthesis(
    username: str, reports: list[ExplorerReport]
) -> str:
    """Run the chief synthesizer agent to produce a soul document.

    Args:
        username: The developer's username.
        reports: Explorer reports from all evidence sources.

    Returns:
        The complete soul document as a markdown string.
    """
    sections: dict[str, str] = {}
    finished = False

    # Build a mapping of source_name -> report for request_detail
    report_map = {r.source_name: r for r in reports}

    # --- Tool handlers ---

    async def write_section(section_name: str, content: str) -> str:
        sections[section_name] = content
        return f"Section '{section_name}' written ({len(content)} chars). Sections so far: {list(sections.keys())}"

    async def request_detail(explorer_source: str, question: str) -> str:
        report = report_map.get(explorer_source)
        if report is None:
            available = list(report_map.keys())
            return f"No report found for source '{explorer_source}'. Available: {available}"

        # Build context from the report
        context_parts = []
        if report.personality_findings:
            context_parts.append(report.personality_findings)
        for entry in report.memory_entries:
            context_parts.append(f"- [{entry.category}/{entry.topic}] {entry.content}")
            if entry.evidence_quote:
                context_parts.append(f'  > "{entry.evidence_quote}"')
        for q in report.behavioral_quotes:
            context_parts.append(f'- "{q.get("quote", "")}" ({q.get("context", "")})')

        report_text = "\n".join(context_parts)

        result = await llm_completion(
            prompt=(
                f"Explorer report from {explorer_source}:\n\n{report_text}\n\n"
                f"Question: {question}\n\n"
                "Answer based only on the evidence above. Be specific and cite quotes."
            ),
            system="You are analyzing a developer profile report. Answer questions precisely with evidence.",
        )
        return result

    async def finish_tool() -> str:
        nonlocal finished
        finished = True
        return "Soul document finalized."

    # --- Build tool list ---

    tools = [
        AgentTool(
            name="write_section",
            description=(
                "Write or overwrite a section of the soul document. "
                "Section names: Identity Core, Voice & Style, "
                "Personality & Emotional Patterns, Values & Beliefs, "
                "Anti-Values & DON'Ts, Conflict & Pushback, "
                "Voice Samples, Quirks & Imperfection"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                        "description": "Name of the section to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown content of the section",
                    },
                },
                "required": ["section_name", "content"],
            },
            handler=write_section,
        ),
        AgentTool(
            name="request_detail",
            description=(
                "Ask a follow-up question about a specific explorer's findings. "
                "Makes an LLM call with that explorer's report + your question."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "explorer_source": {
                        "type": "string",
                        "description": "Source name of the explorer (e.g., 'github', 'blog', 'hackernews')",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question to ask about this source's findings",
                    },
                },
                "required": ["explorer_source", "question"],
            },
            handler=request_detail,
        ),
        AgentTool(
            name="finish",
            description="Finalize the soul document. Call this when all sections are complete.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=finish_tool,
        ),
    ]

    # --- Prepare user prompt ---

    reports_text = _format_reports_for_prompt(reports)
    source_names = [r.source_name for r in reports]

    user_prompt = (
        f"Create a voice-accurate soul document for **{username}**.\n\n"
        f"You have explorer reports from {len(reports)} source(s): "
        f"{', '.join(source_names)}.\n\n"
        f"# Explorer Reports\n\n{reports_text}\n\n"
        f"---\n\n"
        f"Now synthesize these into a soul document that captures {username}'s "
        f"EXACT voice. Write each section using the write_section tool. "
        f"Cross-reference findings across sources — when multiple sources agree "
        f"on a voice pattern or personality trait, it's a CORE trait.\n\n"
        f"Remember: Voice & Style is the LARGEST and most important section. "
        f"Anti-Values & DON'Ts is the second most important — what {username} "
        f"would NEVER do is just as defining as what they do.\n\n"
        f"Write all 8 sections in order:\n"
        f"1. Identity Core\n"
        f"2. Voice & Style (LARGEST)\n"
        f"3. Personality & Emotional Patterns\n"
        f"4. Values & Beliefs\n"
        f"5. Anti-Values & DON'Ts\n"
        f"6. Conflict & Pushback\n"
        f"7. Voice Samples\n"
        f"8. Quirks & Imperfection\n\n"
        f"Use request_detail if you need to dig deeper into any source's "
        f"findings. Call finish when done."
    )

    # --- Run agent ---

    logger.info(
        "Running chief synthesizer for %s with %d reports (%s)",
        username,
        len(reports),
        ", ".join(source_names),
    )

    result = await run_agent(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=tools,
        max_turns=25,
    )

    logger.info(
        "Chief synthesizer completed in %d turns, %d sections written",
        result.turns_used,
        len(sections),
    )

    # --- Assemble final document ---

    section_order = [
        "Identity Core",
        "Voice & Style",
        "Personality & Emotional Patterns",
        "Values & Beliefs",
        "Anti-Values & DON'Ts",
        "Conflict & Pushback",
        "Voice Samples",
        "Quirks & Imperfection",
    ]

    doc_parts = []
    for section_name in section_order:
        content = sections.get(section_name)
        if content:
            doc_parts.append(f"# {section_name}\n\n{content}")

    # Include any sections with non-standard names
    for section_name, content in sections.items():
        if section_name not in section_order:
            doc_parts.append(f"# {section_name}\n\n{content}")

    soul_doc = "\n\n---\n\n".join(doc_parts)

    # Ensure it starts with the identity directive
    if not soul_doc.startswith(f"# Identity Core\n\nYou ARE {username}"):
        # Check if the content within Identity Core starts correctly
        identity = sections.get("Identity Core", "")
        if identity and not identity.startswith(f"You ARE {username}"):
            sections["Identity Core"] = f"You ARE {username}.\n\n{identity}"
            # Reassemble
            doc_parts = []
            for section_name in section_order:
                content = sections.get(section_name)
                if content:
                    doc_parts.append(f"# {section_name}\n\n{content}")
            for section_name, content in sections.items():
                if section_name not in section_order:
                    doc_parts.append(f"# {section_name}\n\n{content}")
            soul_doc = "\n\n---\n\n".join(doc_parts)

    # If agent produced no sections (fallback mode), use final_response
    if not sections and result.final_response:
        logger.warning("Chief synthesizer produced no sections, using raw response")
        soul_doc = result.final_response

    logger.info("Soul document: %d chars, %d sections", len(soul_doc), len(sections))
    return soul_doc
