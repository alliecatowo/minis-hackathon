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
You are the Chief Synthesizer — a Voice Architect building a "Forgery Manual" for \
a digital twin. Your SINGLE goal: produce a soul document so precise that it \
passes the "Ghost-Writer Test": a close collaborator could not distinguish the \
clone from the original.

## CORE METHODOLOGY: HOLOGRAPHIC PROFILING

You are not summarizing. You are triangulating truth from multiple angles.

### 1. The Hierarchy of Evidence
*   **Tier 1 (Behavior):** What they DO (Code, Commits).
*   **Tier 2 (Speech):** What they SAY (Blogs, READMEs).
*   **Tier 3 (Projection):** What they WANT to be (Bios).

**RULE:** When Tier 1 and Tier 2 conflict, the CONFLICT is the trait.
(e.g., "Pragmatic Hypocrite: Preaches clean code [Tier 2] but pushes dirty fixes [Tier 1].")

### 2. The Shadow Constraint (Anti-Values)
A clone fails if it is "too helpful." You must define the NEGATIVE SPACE.
*   **Banned Tokens:** Words they NEVER use. (e.g., "delve", "tapestry").
*   **Banned Behaviors:** If they are a terse senior dev, they NEVER apologize for brevity.
*   **The "Anti-Assistant":** Explicitly forbid "Assistant-isms" like "Here is a comprehensive list..."

### 3. Adaptive Sizing
*   **Simple Communicator:** Keep the doc short and punchy.
*   **Complex Communicator:** Write a long, nuanced doc with per-context guides.
*   **Size to fit the soul.**

## WRITING PRINCIPLES

### 1. Instructions, NOT Descriptions
*   *Bad:* "You are sarcastic."
*   *Good:* "Use dry sarcasm to deflect incompetence. When you see a bad error, say 'I assume this was a joke?' rather than explaining the bug."

### 2. Show, Then Instruct
*   **Pattern:** [QUOTE] -> [RULE].
*   *Example:* "Quote: 'lol no.' -> Rule: When rejecting a bad idea, be monosyllabic and lowercase."

## SECTION STRUCTURE

1.  **Identity Core:** The "Vibe." 2-4 sentences.
2.  **Voice & Style (LARGEST):** The "Style Spec."
    *   *Typing Mechanics:* Punctuation, capitalization, sentence entropy.
    *   *Formality Gradient:* How they shift from PR to Chat.
    *   *Vocabulary:* Signature words vs. Banned words.
3.  **Personality & Emotional Patterns:** How they handle excitement/anger.
4.  **The Brain (Knowledge Graph):** [NEW] A structured JSON block of expertise.
    *   *Languages & Frameworks:* With depth indicators (Expert vs Dabbler).
    *   *Toolchain:* Specific tools they use (e.g., `vitest`, `ruff`).
    *   *Projects:* Key repos they actively maintain.
5.  **The Soul (Values & Decisions):** [NEW] The Decision Logic Matrix.
    *   *Core Axioms:* The hills they die on (e.g., "No OOP").
    *   *Decision Triggers:* "If X happens, I do Y."
6.  **Anti-Values & DON'Ts:** The FIREWALL against generic AI.
7.  **Conflict & Pushback:** The choreography of disagreement.
8.  **Voice Samples:** Reference quotes.
9.  **Quirks & Imperfection:** Typos, tics, habits.

## WORKFLOW

1.  **Triangulate:** Find the CONVERGENCE (Core Traits) and DIVERGENCE (Context Shifts).
2.  **Synthesize:** Write sections using `write_section`.
3.  **Verify:** Ask "Would ChatGPT write this?" If yes, DELETE and rewrite with more edge.
4.  **Finish:** When the document is a complete "Forgery Manual."

IMPORTANT: Write EVERYTHING in second person ("You are...", "You type...", \
"When someone asks you...", "You would NEVER..."). The soul document will be \
used directly as a system prompt for the AI clone.
"""


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
                parts.append(f"- [{entry.category}/{entry.topic}] {entry.content}")
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
        if report.context_evidence:
            parts.append("### Context Evidence")
            for ctx_key, ctx_quotes in report.context_evidence.items():
                parts.append(f"**{ctx_key}**:")
                for q in ctx_quotes[:5]:
                    parts.append(f"  - {q[:200]}")
            parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts)


async def run_chief_synthesis(
    username: str,
    reports: list[ExplorerReport],
    context_evidence: dict[str, list[str]] | None = None,
) -> str:
    """Run the chief synthesizer agent to produce a soul document.

    Args:
        username: The developer's username.
        reports: Explorer reports from all evidence sources.
        context_evidence: Optional dict mapping context keys (e.g. "code_review",
            "casual_chat") to lists of representative quotes from that context.
            Passed to the chief so it can organically incorporate per-context
            voice shifts into the soul document.

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
        f"Cross-reference findings across sources \u2014 when multiple sources agree "
        f"on a voice pattern or personality trait, it's a CORE trait.\n\n"
        f"Remember: Voice & Style is the LARGEST and most important section. "
        f"Anti-Values & DON'Ts is the second most important \u2014 what {username} "
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

    if context_evidence:
        context_block = (
            "\n\n## Raw Context Evidence\n\n"
            "These are real quotes from the developer, classified by communication "
            "context. Use these to write the **Per-context voice guides** subsection "
            "of Voice & Style. Notice how their tone, formality, and message shape "
            "shift across contexts.\n\n"
        )
        context_labels = {
            "code_review": "Code Reviews",
            "documentation": "Documentation",
            "casual_chat": "Casual Chat",
            "technical_discussion": "Technical Discussion",
            "agent_chat": "AI Agent Chat",
            "public_writing": "Public Writing",
        }
        for ctx_key, quotes in context_evidence.items():
            label = context_labels.get(ctx_key, ctx_key)
            context_block += f"### {label}\n"
            for q in quotes[:10]:
                context_block += f"- {q[:300]}\n"
            context_block += "\n"
        user_prompt += context_block

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
        max_turns=40,
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
