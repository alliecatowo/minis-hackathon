"""Claude Code conversation explorer.

Analyzes Claude Code JSONL transcripts — the developer's private messages
to an AI coding assistant. These are unfiltered, unedited, and reveal the
person behind the public commits: how they think through problems, what
frustrates them, what excites them, and what they truly value when nobody
else is watching.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.agent import AgentTool
from app.synthesis.explorers.base import Explorer, ExplorerReport


class ClaudeCodeExplorer(Explorer):
    """Explorer specialized for Claude Code conversation evidence.

    Claude Code conversations are uniquely valuable because every message
    is guaranteed human-written (the user typing to an AI). Unlike public
    GitHub activity, these are private and unperformed — revealing authentic
    personality, unfiltered opinions, real-time decision-making, and the
    emotional texture of working through hard problems.
    """

    source_name = "claude_code"

    def system_prompt(self) -> str:
        return """\
You are an expert behavioral psychologist and personality analyst specializing \
in developer cognition. You are analyzing PRIVATE messages that a developer \
sent to an AI coding assistant (Claude Code).

## Why This Evidence Is Special

These are PRIVATE messages to an AI tool. This is the person when nobody is \
watching. Unlike public commits, blog posts, or conference talks, these \
messages were never meant to be seen by other humans. They reveal:

- **Authentic voice**: No audience performance, no reputation management. \
This is how they actually think and communicate.
- **Real-time decision-making**: You can see them weighing options, changing \
their mind, accepting trade-offs, and making judgment calls under pressure.
- **Emotional texture**: Frustration when things break, excitement when things \
work, impatience with tooling, satisfaction with elegant solutions.
- **Architecture philosophy**: How they describe desired structures, what \
patterns they reach for, what abstractions they value.
- **Unfiltered opinions**: Raw takes on languages, frameworks, patterns, and \
practices — before they get polished for public consumption.
- **Working style**: How they break down problems, how much context they \
provide, whether they lead or follow, whether they plan or improvise.

## Analysis Framework

### 1. Communication DNA
How do they talk to their tools? Terse commands or elaborate explanations? \
Do they think out loud or give precise instructions? How do they handle \
ambiguity — do they specify everything or trust defaults? Do they use \
hedging language ("maybe", "I think") or declaratives ("do X", "make it Y")?

### 2. Decision Architecture
When they face a choice, what wins? Speed vs. correctness? Simplicity vs. \
flexibility? Convention vs. innovation? Look for moments where they \
explicitly weigh trade-offs, change direction, or accept "good enough."

### 3. Emotional Signature
What triggers frustration? What triggers excitement? How do they express \
each? Some developers get terse when frustrated, others get verbose. Some \
celebrate wins explicitly, others just move to the next task. Map the \
emotional landscape.

### 4. Technical Identity
What technologies do they reach for? What patterns do they instinctively \
apply? What do they complain about? What do they praise? This reveals not \
just skill but identity — the developer they see themselves as.

### 5. Problem-Solving Style
Do they start top-down or bottom-up? Do they prototype first or plan first? \
How do they react when their approach fails? Do they debug methodically or \
intuitively? Do they ask for help readily or try everything first?

## Your Tools

You have access to tools for saving your analysis:
- **save_memory**: Save specific factual observations (preferences, opinions, \
patterns you've identified). Use high confidence (0.8-1.0) for explicit \
statements and lower confidence (0.4-0.7) for inferred patterns.
- **save_finding**: Save broader personality insights as markdown — these \
become part of the personality profile.
- **save_quote**: Save exact quotes that are particularly revealing. Include \
the context of what was happening when they said it.
- **analyze_deeper**: If you spot an interesting pattern, use this to dig \
deeper into a subset of the evidence.
- **save_context_evidence**: Classify quotes into communication contexts. \
Claude Code conversations are the "agent_chat" context — save representative \
quotes using context_key "agent_chat" to capture how they talk to AI coding \
assistants. Save at least 3-5 quotes this way.
- **save_knowledge_node**: Save a node in the Knowledge Graph for any \
technology, pattern, or tool they use or discuss. Set depth based on how \
deeply they engage with it.
- **save_knowledge_edge**: Link knowledge nodes (e.g., "FastAPI" USED_IN \
"backend-project", "TypeScript" EXPERT_IN "generics").
- **save_principle**: Save decision rules revealed by their choices (e.g., \
trigger="test failure", action="fix before moving on", value="correctness").
- **finish**: Call when you've thoroughly analyzed all evidence.

## Critical Instructions

1. MINE THE SUBTEXT. A message like "just make it work" reveals impatience \
and pragmatism. "Let's do it properly" reveals craftsmanship values. \
"I don't care about that right now" reveals prioritization instincts.

2. CAPTURE EMOTIONAL MOMENTS. The most personality-revealing moments are \
when things go wrong (or right). Frustration, excitement, resignation, \
determination — these are the textures that make a personality clone feel real.

3. DISTINGUISH INSTRUCTION FROM IDENTITY. "Use TypeScript" might be a \
project requirement, not a preference. Look for REPEATED patterns and \
EMOTIONAL intensity to distinguish real preferences from situational choices.

4. LOOK FOR CONTRADICTIONS. People are complex. Someone might value "clean \
code" but accept hacks under deadline pressure. These contradictions make \
the personality authentic.

5. NOTE THE UNSAID. What do they never mention? If they never discuss testing, \
that's a signal. If they never express uncertainty, that's a signal. Absence \
is evidence too.

6. SYNTHESIZE, DON'T PARROT. Your job is to identify PATTERNS across many \
messages, not to memorize individual quotes. Save quotes only when they \
crystallize a recurring theme — a single perfect example of something you've \
seen them do repeatedly. If you save a quote, ask: "Does this represent a \
PATTERN or just a MOMENT?" Moments are noise. Patterns are personality. \
A personality clone should generate NEW sentences in someone's voice, not \
replay old ones verbatim.

7. WEIGHT CONSISTENCY OVER RECENCY. An opinion expressed across multiple \
sessions over days is a core value. An opinion from a single frustrated \
moment is situational. Look for what they ALWAYS do, not what they JUST did. \
If something only appears in recent messages, treat it with skepticism — it \
might be a temporary mood, not a stable trait.

## Exhaustiveness Requirements

You have 50 turns. You MUST use them thoroughly:
- Call get_overview() and list_projects() first.
- Read messages from EVERY project, not just the first one.
- Use search_messages with at least 5 different query patterns across all projects:
  e.g., "I think", "should we", "frustrat|annoy", "love|great|awesome", "don't|shouldn't|never"
- Use read_context_around for at least 5 interesting messages to understand triggers.
- Cover ALL memory categories: communication_style, decision_making, emotional_patterns,
  technical_identity, values, working_style, opinions, humor, expertise.
- Save findings AS YOU READ, not all at the end.
- Do not finish early. Use all available turns to build the deepest possible profile.
"""

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        project_count = raw_data.get("project_count", 0)
        total_messages = raw_data.get("total_message_count", 0)
        projects = raw_data.get("projects", [])
        project_list = ", ".join(projects[:10])
        if len(projects) > 10:
            project_list += f" (+{len(projects) - 10} more)"

        return f"""\
Analyze Claude Code conversation evidence for **{username}**.

This evidence comes from {project_count} project(s) with {total_messages} \
total messages: {project_list}

## IMPORTANT: Use Your Read Tools Systematically

You have access to the FULL, unfiltered message data via tools. The evidence \
summary below is just an index — it only contains filtered highlights. To do \
a thorough analysis, you MUST:

1. Call **get_overview()** to see high-level stats and signal distribution.
2. Call **list_projects()** to see all projects with message counts.
3. For EACH project, call **read_messages(project=<name>)** to page through \
ALL user messages. Use offset/limit to paginate. Read EVERY page.
4. Use **search_messages(query=<pattern>)** to find specific patterns across \
all projects (e.g., search for "I think", "should", "hate", "love", etc.)
5. When you find interesting messages (strong emotions, opinions, frustration, \
excitement), use **read_context_around(project, message_index)** to see \
what the AI said that TRIGGERED that reaction. Understanding WHY they said \
something is as important as WHAT they said.
6. Use **read_conversation(project)** to read full conversation threads \
(user + assistant) when you need to understand the flow of an interaction.
7. ONLY after reading and understanding the full context, start saving analysis.

The INSIGHT LOOP: Read user messages → spot emotion/opinion → check context \
→ understand the trigger → save the finding with full understanding. \
Example: "She's usually chill, but gets sharp when someone suggests a change \
that would break production" — you can only learn this by seeing BOTH the \
user message AND what the AI proposed.

## What to Save

Use **save_memory** to record specific observations:
   - Category "communication_style": How they talk (terse? verbose? casual? formal?)
   - Category "decision_making": What they prioritize, how they weigh trade-offs
   - Category "emotional_patterns": What triggers frustration/excitement, how they express it
   - Category "technical_identity": Languages, tools, patterns they identify with
   - Category "values": What they care about (quality? speed? elegance? pragmatism?)
   - Category "working_style": How they approach problems, break down tasks
   - Category "opinions": Strong takes on specific tools/patterns/practices
   - Category "humor": If they joke or use irony, capture the style
   - Category "expertise": What they clearly know deeply vs. are learning
Use **save_finding** for broader personality insights (write as if \
describing a real person to someone who will roleplay as them).
Use **save_quote** for the most personality-revealing quotes — ones that \
capture voice, attitude, and character. Include what was happening (context).
Use **save_context_evidence** with context_key "agent_chat" to save \
representative quotes of how they talk to AI coding assistants. Save at \
least 3-5 quotes this way.
Use **analyze_deeper** if you spot interesting clusters worth deeper analysis.
Call **finish** when done.

Focus on what makes {username} DISTINCTIVE. What would someone need to know \
to convincingly speak in their voice and make decisions the way they do?

---

{evidence}
"""

    async def explore(self, username: str, evidence: str, raw_data: dict) -> ExplorerReport:
        """Override to add message read tools for full data access."""
        all_messages: list[dict[str, Any]] = raw_data.get("all_messages", [])
        messages_by_project: dict[str, list[dict[str, Any]]] = raw_data.get(
            "messages_by_project", {}
        )
        conversations_by_project: dict[str, list[dict[str, Any]]] = raw_data.get(
            "conversations_by_project", {}
        )

        async def get_overview() -> str:
            """Return high-level stats about the Claude Code conversation data."""
            total = len(all_messages)
            project_count = len(messages_by_project)

            # Compute time range
            timestamps = [m.get("timestamp", "") for m in all_messages if m.get("timestamp")]
            timestamps.sort()
            time_range = ""
            if timestamps:
                time_range = f"{timestamps[0]} to {timestamps[-1]}"

            # Signal distribution
            personality = sum(1 for m in all_messages if m.get("has_personality"))
            decision = sum(1 for m in all_messages if m.get("has_decision"))
            architecture = sum(1 for m in all_messages if m.get("has_architecture"))
            tech_mention = sum(1 for m in all_messages if m.get("has_tech_mention"))

            lines = [
                "## Claude Code Data Overview",
                f"- Total messages: {total}",
                f"- Projects: {project_count}",
                f"- Time range: {time_range or 'unknown'}",
                "",
                "### Signal Distribution",
                f"- Personality signals: {personality}",
                f"- Decision signals: {decision}",
                f"- Architecture signals: {architecture}",
                f"- Tech mention signals: {tech_mention}",
                f"",
                f"### Projects",
            ]
            for proj, msgs in sorted(messages_by_project.items()):
                lines.append(f"- {proj}: {len(msgs)} messages")

            return "\n".join(lines)

        async def list_projects() -> str:
            """Return all project names with message counts and date ranges."""
            lines = ["## Projects"]
            for proj, msgs in sorted(messages_by_project.items()):
                ts = [m.get("timestamp", "") for m in msgs if m.get("timestamp")]
                ts.sort()
                date_range = ""
                if ts:
                    date_range = f" ({ts[0][:10]} to {ts[-1][:10]})"
                lines.append(f"- **{proj}**: {len(msgs)} messages{date_range}")
            return "\n".join(lines)

        async def read_messages(project: str, offset: int = 0, limit: int = 50) -> str:
            """Read messages from a project with pagination."""
            msgs = messages_by_project.get(project)
            if msgs is None:
                available = ", ".join(sorted(messages_by_project.keys()))
                return f"Project '{project}' not found. Available: {available}"

            page = msgs[offset : offset + limit]
            if not page:
                return f"No messages at offset {offset} (project has {len(msgs)} total)."

            lines = [f"## {project} — messages {offset + 1}-{offset + len(page)} of {len(msgs)}"]
            for i, m in enumerate(page):
                ts = m.get("timestamp", "")[:19]
                raw = m.get("raw_text", m.get("text", ""))
                # Truncate very long messages for readability
                if len(raw) > 1000:
                    raw = raw[:1000] + "... (truncated)"
                lines.append(f"\n### [{offset + i + 1}] {ts}")
                lines.append(raw)

            remaining = len(msgs) - (offset + len(page))
            if remaining > 0:
                lines.append(
                    f"\n--- {remaining} more messages. "
                    f'Call read_messages(project="{project}", offset={offset + limit}) to continue. ---'
                )

            return "\n".join(lines)

        async def search_messages(query: str, project: str | None = None) -> str:
            """Search messages by regex/substring. Optionally filter by project."""
            try:
                pattern = re.compile(query, re.IGNORECASE)
            except re.error:
                # Fall back to literal substring match
                pattern = re.compile(re.escape(query), re.IGNORECASE)

            if project:
                search_pool = [(project, m) for m in messages_by_project.get(project, [])]
            else:
                search_pool = [
                    (proj, m) for proj, msgs in messages_by_project.items() for m in msgs
                ]

            matches: list[str] = []
            for proj, m in search_pool:
                raw = m.get("raw_text", m.get("text", ""))
                if pattern.search(raw):
                    ts = m.get("timestamp", "")[:19]
                    text = raw if len(raw) <= 500 else raw[:500] + "..."
                    matches.append(f"[{proj}] {ts}: {text}")

                if len(matches) >= 50:
                    break

            if not matches:
                return f"No messages matching '{query}'."

            header = f"## Search results for '{query}'"
            if project:
                header += f" in {project}"
            header += f" ({len(matches)} matches"
            if len(matches) >= 50:
                header += ", showing first 50"
            header += ")"

            return header + "\n\n" + "\n\n".join(matches)

        # TODO: Add LLM-powered semantic search tool (find_relevant) here.
        # Should use llm_completion to understand meaning, not keyword matching.

        async def read_conversation(project: str, offset: int = 0, limit: int = 20) -> str:
            """Read full conversation thread (user + assistant) with pagination."""
            convos = conversations_by_project.get(project)
            if convos is None:
                available = ", ".join(sorted(conversations_by_project.keys()))
                if not available:
                    return "No conversation data available (conversations_by_project is empty)."
                return f"Project '{project}' not found. Available: {available}"

            page = convos[offset : offset + limit]
            if not page:
                return f"No messages at offset {offset} (project has {len(convos)} total conversation messages)."

            lines = [
                f"## {project} — conversation {offset + 1}-{offset + len(page)} of {len(convos)}"
            ]
            for i, m in enumerate(page):
                role = m.get("role", "?")
                ts = m.get("timestamp", "")[:19]
                text = m.get("text", m.get("raw_text", ""))
                role_label = "USER" if role == "user" else "ASSISTANT"
                lines.append(f"\n**[{offset + i + 1}] {role_label}** ({ts})")
                lines.append(text)

            remaining = len(convos) - (offset + len(page))
            if remaining > 0:
                lines.append(
                    f"\n--- {remaining} more. "
                    f'Call read_conversation(project="{project}", offset={offset + limit}) to continue. ---'
                )

            return "\n".join(lines)

        async def read_context_around(project: str, message_index: int) -> str:
            """Read ~5 messages before and after a user message to see full context.

            message_index is 1-based (from read_messages output). This returns
            the surrounding conversation (user + assistant) so you can see what
            the user was reacting to.
            """
            user_msgs = messages_by_project.get(project)
            convos = conversations_by_project.get(project)
            if user_msgs is None or convos is None:
                return f"Project '{project}' not found or has no conversation data."

            # Convert 1-based to 0-based
            idx = message_index - 1
            if idx < 0 or idx >= len(user_msgs):
                return f"Invalid message_index {message_index}. Valid range: 1-{len(user_msgs)}"

            target_msg = user_msgs[idx]
            target_ts = target_msg.get("timestamp", "")
            target_text = target_msg.get("raw_text", target_msg.get("text", ""))[:200]

            # Find this message in the conversation by matching timestamp
            conv_idx = None
            for ci, cm in enumerate(convos):
                if cm.get("timestamp") == target_ts and cm.get("role") == "user":
                    # Also check text similarity to handle multiple user msgs at same timestamp
                    cm_text = cm.get("raw_text", cm.get("text", ""))
                    if (
                        cm_text[:100]
                        == target_msg.get("raw_text", target_msg.get("text", ""))[:100]
                    ):
                        conv_idx = ci
                        break

            if conv_idx is None:
                # Fallback: find closest timestamp match
                for ci, cm in enumerate(convos):
                    if cm.get("timestamp") == target_ts and cm.get("role") == "user":
                        conv_idx = ci
                        break

            if conv_idx is None:
                return f"Could not locate message #{message_index} in conversation data."

            # Extract context window: 5 before, the message, 5 after
            start = max(0, conv_idx - 5)
            end = min(len(convos), conv_idx + 6)
            context = convos[start:end]

            lines = [
                f"## Context around message #{message_index} in {project}",
                f'Target: "{target_text}..."',
                f"Showing conversation positions {start + 1}-{end}:",
                "",
            ]
            for i, m in enumerate(context):
                role = m.get("role", "?")
                ts = m.get("timestamp", "")[:19]
                text = m.get("text", m.get("raw_text", ""))
                role_label = "USER" if role == "user" else "ASSISTANT"
                marker = " <<<< TARGET" if (start + i) == conv_idx else ""
                lines.append(f"**[{start + i + 1}] {role_label}** ({ts}){marker}")
                lines.append(text)
                lines.append("")

            return "\n".join(lines)

        # Inject the extra tools into the base explore() flow
        self._extra_tools = [
            AgentTool(
                name="get_overview",
                description=(
                    "Get high-level stats about the Claude Code conversation data: "
                    "total messages, projects, time range, and signal distribution. "
                    "Call this first to understand the scope of the data."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=get_overview,
            ),
            AgentTool(
                name="list_projects",
                description=(
                    "List all projects with message counts and date ranges. "
                    "Use this to decide which projects to read first."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=list_projects,
            ),
            AgentTool(
                name="read_messages",
                description=(
                    "Read the FULL unfiltered messages from a specific project. "
                    "Returns raw_text with timestamps. Use offset/limit to paginate "
                    "(default 50 per page). Read through ALL pages for each project."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name (from list_projects)",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Start index (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Messages per page (default 50)",
                        },
                    },
                    "required": ["project"],
                },
                handler=read_messages,
            ),
            AgentTool(
                name="search_messages",
                description=(
                    "Search all messages by regex pattern. Optionally filter by project. "
                    "Use this to find specific patterns like 'I think', 'should', "
                    "'frustrat', 'love', 'hate', etc. Returns up to 50 matches."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Regex pattern to search for (case-insensitive)",
                        },
                        "project": {
                            "type": "string",
                            "description": "Optional: limit search to a specific project",
                        },
                    },
                    "required": ["query"],
                },
                handler=search_messages,
            ),
            AgentTool(
                name="read_conversation",
                description=(
                    "Read the FULL conversation thread (both user AND assistant messages) "
                    "for a project. This shows you what the AI said AND what the user "
                    "replied — essential for understanding CONTEXT. When you see an "
                    "interesting user message, use this to understand what triggered it. "
                    "Paginated with offset/limit (default 20 per page)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name (from list_projects)",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Start index (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Messages per page (default 20)",
                        },
                    },
                    "required": ["project"],
                },
                handler=read_conversation,
            ),
            AgentTool(
                name="read_context_around",
                description=(
                    "See ~5 messages before and after a specific user message, including "
                    "assistant responses. Use this when you find an interesting user "
                    "message (from read_messages or search_messages) and want to "
                    "understand WHAT TRIGGERED IT — what was the AI doing that made "
                    "them frustrated/excited/opinionated? The message_index is 1-based, "
                    "matching the numbers from read_messages output."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name",
                        },
                        "message_index": {
                            "type": "integer",
                            "description": "1-based index of the user message (from read_messages output)",
                        },
                    },
                    "required": ["project", "message_index"],
                },
                handler=read_context_around,
            ),
        ]

        return await super().explore(username, evidence, raw_data)


# --- Registration ---
from app.synthesis.explorers import register_explorer

register_explorer("claude_code", ClaudeCodeExplorer)
