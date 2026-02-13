"""Claude Code conversation ingestion source.

Parses Claude Code JSONL conversation transcripts to extract personality evidence
from how the user communicates, makes decisions, and handles technical problems.

Claude Code conversations are a gold mine for personality analysis because user
messages are guaranteed human-written (unlike commits which may be AI-generated).
They reveal communication style, problem-solving approach, technical priorities,
and emotional patterns.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)

# Patterns that indicate a message is just a command or path, not natural language
_COMMAND_PATTERNS = re.compile(
    r"^("
    r"[/~][\w/.@\-]+"  # file paths
    r"|git\s+\w+"  # git commands
    r"|cd\s+\S+"  # cd commands
    r"|ls\b.*"  # ls commands
    r"|cat\s+\S+"  # cat commands
    r"|rm\s+\S+"  # rm commands
    r"|mkdir\s+\S+"  # mkdir commands
    r"|npm\s+\w+"  # npm commands
    r"|pip\s+\w+"  # pip commands
    r"|y|n|yes|no|ok|done|thanks|thank you|sure|right|yep|nope|yea|yeah"
    r")$",
    re.IGNORECASE,
)

# Words/phrases that signal personality: opinions, emotions, decisions
_PERSONALITY_SIGNALS = re.compile(
    r"\b("
    r"i think|i feel|i want|i need|i prefer|i like|i hate|i love"
    r"|don'?t like|don'?t want|don'?t need|don'?t care"
    r"|should|shouldn'?t|must|have to|need to"
    r"|important|priority|focus|critical|essential"
    r"|annoying|frustrating|awful|terrible|amazing|great|perfect|awesome"
    r"|wrong|right|better|worse|best|worst"
    r"|stupid|brilliant|ugly|clean|elegant|hacky|messy"
    r"|no but|missing the point|that'?s not|actually"
    r"|let'?s|we should|we need|we can"
    r"|honestly|frankly|obviously|clearly|basically"
    r")\b",
    re.IGNORECASE,
)

# Patterns that reveal decision-making and prioritization style
_DECISION_SIGNALS = re.compile(
    r"\b("
    r"let'?s use|let'?s go with|i'?d rather|instead of"
    r"|more important|trade-?off|compromise|ship it|good enough"
    r"|not worth|over-?engineer|yak shav|scope creep|technical debt"
    r"|refactor|rewrite|migrate|deprecate"
    r"|the priority is|we need to focus|that'?s more important"
    r"|pros and cons|weigh|consider|evaluate|worth it"
    r"|keep it simple|kiss|yagni|premature|overkill"
    r")\b",
    re.IGNORECASE,
)

# Patterns that reveal architectural/design thinking
_ARCHITECTURE_SIGNALS = re.compile(
    r"\b("
    r"architect(?:ure)?|structur(?:e|ing)|organiz(?:e|ing|ation)"
    r"|pattern|approach|design|component|module|service|layer"
    r"|separation|coupling|cohesion|abstraction|interface"
    r"|dependency|inject|inversion|encapsulat"
    r"|monolith|microservice|monorepo|hexagonal|domain.driven"
    r"|single.responsib|solid|dry|separation.of.concerns"
    r"|file.structure|project.structure|folder.structure"
    r"|data.model|schema|migration|endpoint|route"
    r")\b",
    re.IGNORECASE,
)

# Technologies/tools that signal technical preferences when mentioned
_TECH_MENTION_PATTERNS = re.compile(
    r"\b(?:python|javascript|typescript|react|vue|angular|svelte|nextjs|next\.js|"
    r"rust|go|golang|java|kotlin|swift|ruby|rails|django|flask|fastapi|express|"
    r"node|deno|bun|docker|kubernetes|k8s|terraform|aws|gcp|azure|"
    r"postgresql|postgres|mysql|sqlite|mongodb|redis|graphql|rest\s?api|"
    r"tailwind|css|html|sass|webpack|vite|turbopack|"
    r"git|github|gitlab|ci/cd|"
    r"neovim|vim|vscode|emacs|jetbrains|"
    r"linux|macos|windows|fedora|ubuntu|arch)\b",
    re.IGNORECASE,
)

# Patterns that look like secrets/keys (redact these)
_SECRET_RE = re.compile(
    r"(?:"
    r"sk-[A-Za-z0-9\-]{20,}"  # OpenAI-style keys
    r"|ctx7sk-[A-Za-z0-9\-]+"  # Context7 keys
    r"|ghp_[A-Za-z0-9]{20,}"  # GitHub PATs
    r"|ghu_[A-Za-z0-9]{20,}"  # GitHub user tokens
    r"|xoxb-[A-Za-z0-9\-]+"  # Slack bot tokens
    r"|xoxp-[A-Za-z0-9\-]+"  # Slack user tokens
    r")"
)

# Fenced code block pattern (```...```)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")

# Inline code pattern (`...`)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")


class ClaudeCodeSource(IngestionSource):
    """Ingestion source that parses Claude Code JSONL conversation logs.

    Accepts either a path to a specific file/directory or ``~/.claude/projects``
    to auto-discover all project conversation data.
    """

    name = "claude_code"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Parse Claude Code conversation files and extract evidence.

        Args:
            identifier: Path to a JSONL file, a directory of JSONL files,
                or the ``~/.claude/projects`` root to auto-discover all projects.
            **config: Optional overrides.
                max_files: Maximum JSONL files to process (default 100).
                max_messages_per_conv: Cap messages per conversation (default 40).
        """
        data_dir = config.get("data_dir")
        if data_dir:
            path = Path(data_dir)
        else:
            path = Path(identifier).expanduser()
        max_files = config.get("max_files", 100)

        projects = _discover_projects(path, max_files=max_files)
        total_raw = sum(len(msgs) for msgs in projects.values())

        # Apply smart filtering
        filtered_projects: dict[str, list[dict[str, Any]]] = {}
        personality_count = 0
        decision_count = 0
        architecture_count = 0
        tech_mention_count = 0
        for proj, messages in projects.items():
            kept = _filter_messages(messages)
            if kept:
                filtered_projects[proj] = kept
                personality_count += sum(1 for m in kept if m.get("has_personality"))
                decision_count += sum(1 for m in kept if m.get("has_decision"))
                architecture_count += sum(1 for m in kept if m.get("has_architecture"))
                tech_mention_count += sum(1 for m in kept if m.get("has_tech_mention"))

        total_kept = sum(len(msgs) for msgs in filtered_projects.values())
        evidence = _format_evidence(filtered_projects)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "project_count": len(filtered_projects),
                "projects": list(filtered_projects.keys()),
            },
            stats={
                "projects_discovered": len(projects),
                "projects_with_evidence": len(filtered_projects),
                "total_user_messages_raw": total_raw,
                "total_user_messages_kept": total_kept,
                "personality_signal_messages": personality_count,
                "decision_signal_messages": decision_count,
                "architecture_signal_messages": architecture_count,
                "tech_mention_messages": tech_mention_count,
                "evidence_length": len(evidence),
            },
        )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_projects(
    path: Path, *, max_files: int = 100
) -> dict[str, list[dict[str, Any]]]:
    """Discover and parse JSONL files, grouped by project.

    Returns a mapping of project name -> list of message dicts.
    """
    jsonl_files: list[tuple[str, Path]] = []

    if path.is_file() and path.suffix == ".jsonl":
        project = _project_name_from_path(path)
        jsonl_files.append((project, path))

    elif path.is_dir():
        # Check if this is the ~/.claude/projects root (contains project dirs)
        subdirs = [d for d in path.iterdir() if d.is_dir() and d.name != "memory"]
        has_jsonl_directly = any(path.glob("*.jsonl"))

        if subdirs and not has_jsonl_directly:
            # This is a root like ~/.claude/projects — recurse into subdirs
            for subdir in sorted(subdirs):
                project = _project_name_from_dir(subdir)
                for f in sorted(subdir.glob("*.jsonl")):
                    jsonl_files.append((project, f))
        else:
            # Single project directory or flat directory of JSONL files
            project = _project_name_from_dir(path)
            for f in sorted(path.glob("*.jsonl")):
                jsonl_files.append((project, f))
    else:
        logger.warning("Claude Code path not found: %s", path)
        return {}

    # Cap total files
    jsonl_files = jsonl_files[:max_files]

    projects: dict[str, list[dict[str, Any]]] = {}
    for project, filepath in jsonl_files:
        try:
            messages = _parse_jsonl(filepath)
            if messages:
                projects.setdefault(project, []).extend(messages)
        except Exception:
            logger.warning("Failed to parse %s", filepath, exc_info=True)

    return projects


def _project_name_from_path(filepath: Path) -> str:
    """Extract a project name from a JSONL file path."""
    return _project_name_from_dir(filepath.parent)


def _project_name_from_dir(dirpath: Path) -> str:
    """Extract a human-readable project name from a Claude Code project directory.

    Directory names encode the full filesystem path with dashes replacing ``/``.
    For example ``-home-Allie-develop-minis-hackathon`` encodes
    ``/home/Allie/develop/minis-hackathon``.

    We reconstruct the path and take the basename.
    """
    name = dirpath.name
    if name.startswith("-"):
        # Try to find the actual directory on disk by reconstructing the path.
        # Naive reconstruction (all dashes -> /) is wrong for multi-segment
        # names like "minis-hackathon", so we probe the filesystem.
        candidate = Path("/" + name[1:].replace("-", "/"))
        if candidate.is_dir():
            return candidate.name
        # Walk backwards, joining segments with dashes, to find the real dir
        parts = name[1:].split("-")
        for i in range(len(parts) - 1, 0, -1):
            base = "/".join(parts[:i])
            rest = "-".join(parts[i:])
            candidate = Path("/" + base) / rest
            if candidate.is_dir():
                return rest
        # Fallback: use the last component of the naive reconstruction
        return candidate.name
    return name


# ---------------------------------------------------------------------------
# JSONL Parsing
# ---------------------------------------------------------------------------


def _parse_jsonl(filepath: Path) -> list[dict[str, Any]]:
    """Parse a single JSONL transcript and extract user messages.

    Returns a list of message dicts with keys:
        text: The natural language content (code blocks stripped)
        raw_text: The original unmodified text
        timestamp: ISO timestamp string
        project_cwd: The working directory from the entry
        has_personality: Whether personality signals were detected
    """
    messages: list[dict[str, Any]] = []

    with open(filepath) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "user":
                continue

            msg = entry.get("message", {})
            if msg.get("role") != "user":
                continue

            timestamp = entry.get("timestamp", "")
            cwd = entry.get("cwd", "")

            # Extract text content from the message
            texts = _extract_text_content(msg.get("content", ""))

            for text in texts:
                if text:
                    stripped = _strip_code_blocks(text)
                    messages.append(
                        {
                            "raw_text": text,
                            "text": stripped,
                            "timestamp": timestamp,
                            "project_cwd": cwd,
                            "has_personality": bool(_PERSONALITY_SIGNALS.search(text)),
                            "has_decision": bool(_DECISION_SIGNALS.search(text)),
                            "has_architecture": bool(_ARCHITECTURE_SIGNALS.search(stripped)),
                            "has_tech_mention": bool(_TECH_MENTION_PATTERNS.search(stripped)),
                        }
                    )

    return messages


def _extract_text_content(content: str | list[Any]) -> list[str]:
    """Extract human-written text from message content.

    Content can be a plain string or a list of content blocks.
    We only extract ``text`` type blocks — ``tool_result`` blocks are
    automated responses and should be skipped.
    """
    if isinstance(content, str):
        stripped = content.strip()
        return [stripped] if stripped else []

    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            # Only extract text blocks — skip tool_result, images, etc.
            if block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    texts.append(text)
        return texts

    return []


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks but keep short inline code mentions.

    Short inline code (< 30 chars) often names technologies, functions, or
    tools that are valuable personality/preference signals (e.g. ``React``,
    ``useEffect``, ``FastAPI``).  Only fenced code blocks and long inline code
    are removed.
    """
    # Remove fenced code blocks
    result = _CODE_BLOCK_RE.sub("", text)
    # Remove long inline code but keep short mentions (tech names, function names)
    result = _INLINE_CODE_RE.sub(
        lambda m: m.group(0) if len(m.group(0)) < 32 else "",  # 32 = 30 + 2 backticks
        result,
    )
    # Redact anything that looks like a secret/API key
    result = _SECRET_RE.sub("[REDACTED]", result)
    # Clean up leftover whitespace
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result


# ---------------------------------------------------------------------------
# Smart Filtering
# ---------------------------------------------------------------------------


_AUTOMATED_PREFIXES = (
    "# Ralph Loop",
    "[Request interrupted",
    "<task-notification",
    "<local-command-",
    "<command-name>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "Base directory for this skill:",
)


def _is_automated_content(text: str) -> bool:
    """Return True if the message looks like automated/system content."""
    if text.startswith(_AUTOMATED_PREFIXES):
        return True
    # XML-tag-heavy messages are usually system injections
    if text.startswith("<") and text.count("<") > text.count(" ") // 3:
        return True
    return False


def _filter_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply smart filtering to keep messages that reveal personality.

    Filters out:
    - Very short messages (< 10 chars after code stripping)
    - Messages that are just file paths or commands
    - Messages that are just automated content (tool results, hook outputs)

    Prioritizes messages with personality signals and samples across time
    to avoid recency bias.
    """
    kept: list[dict[str, Any]] = []

    for msg in messages:
        text = msg["text"]

        # Skip very short messages
        if len(text) < 10:
            continue

        # Skip messages that are just commands or paths
        if _COMMAND_PATTERNS.match(text):
            continue

        # Skip messages that look like automated/hook content or system messages
        if _is_automated_content(text):
            continue

        has_personality = msg.get("has_personality", False)
        has_decision = msg.get("has_decision", False)
        has_architecture = msg.get("has_architecture", False)
        has_tech_mention = msg.get("has_tech_mention", False)

        # Keep if message has any high-value signal
        if has_personality or has_decision or has_architecture or has_tech_mention:
            kept.append(msg)

    # --- Anti-recency-bias: sample evenly across time ---
    # Split into time-based thirds (early, middle, recent) and take
    # proportional samples from each so no single period dominates.
    kept.sort(key=lambda m: m.get("timestamp", ""))
    if len(kept) > 60:
        third = len(kept) // 3
        early = kept[:third]
        middle = kept[third : 2 * third]
        recent = kept[2 * third :]
        # Take up to 30 from each third
        per_bucket = 30
        kept = early[:per_bucket] + middle[:per_bucket] + recent[:per_bucket]

    # Sort: decision/personality signals first, then architecture, then tech,
    # then by timestamp
    kept.sort(key=lambda m: (
        not m.get("has_decision"),
        not m.get("has_personality"),
        not m.get("has_architecture"),
        not m.get("has_tech_mention"),
        m.get("timestamp", ""),
    ))

    return kept


# ---------------------------------------------------------------------------
# Evidence Formatting
# ---------------------------------------------------------------------------


def _format_evidence(projects: dict[str, list[dict[str, Any]]]) -> str:
    """Format filtered messages into evidence text for LLM personality analysis.

    Groups messages by project and highlights personality-revealing content.
    """
    if not projects:
        return ""

    sections: list[str] = [
        "## Claude Code Conversations (Human-Written Messages)\n"
        "(These are guaranteed human-written messages from coding sessions. "
        "They reveal communication style, decision-making, technical opinions, "
        "and personality traits.)\n"
    ]

    for project, messages in sorted(projects.items()):
        if not messages:
            continue

        sections.append(f"### Project: {project}")

        # Categorize messages into distinct evidence buckets.
        # A message can appear in at most one bucket — the highest-priority
        # one it matches — so we don't duplicate evidence.
        decision_msgs: list[dict[str, Any]] = []
        personality_msgs: list[dict[str, Any]] = []
        architecture_msgs: list[dict[str, Any]] = []
        tech_msgs: list[dict[str, Any]] = []
        regular_msgs: list[dict[str, Any]] = []

        for m in messages:
            if m.get("has_decision"):
                decision_msgs.append(m)
            elif m.get("has_personality"):
                personality_msgs.append(m)
            elif m.get("has_architecture"):
                architecture_msgs.append(m)
            elif m.get("has_tech_mention"):
                tech_msgs.append(m)
            else:
                regular_msgs.append(m)

        if decision_msgs:
            sections.append(
                "*Decision-Making & Priorities "
                "(reveals how this person weighs trade-offs and makes choices):*"
            )
            for msg in decision_msgs[:40]:
                text = _truncate(msg["text"], 500)
                sections.append(f'- "{text}"')

        if personality_msgs:
            sections.append(
                "\n*Messages showing opinions, emotions, and personality:*"
            )
            for msg in personality_msgs[:40]:
                text = _truncate(msg["text"], 500)
                sections.append(f'- "{text}"')

        if architecture_msgs:
            sections.append(
                "\n*Architecture & Design Thinking "
                "(project structure, patterns, system design):*"
            )
            for msg in architecture_msgs[:30]:
                text = _truncate(msg["text"], 500)
                sections.append(f'- "{text}"')

        if tech_msgs:
            sections.append(
                "\n*Technical Preferences "
                "(tools, languages, frameworks mentioned):*"
            )
            for msg in tech_msgs[:30]:
                text = _truncate(msg["text"], 400)
                sections.append(f'- "{text}"')

        if regular_msgs:
            sections.append("\n*Other instructions and communication:*")
            for msg in regular_msgs[:20]:
                text = _truncate(msg["text"], 400)
                sections.append(f'- "{text}"')

        sections.append("")

    return "\n".join(sections)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
