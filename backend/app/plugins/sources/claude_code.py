"""Claude Code conversation ingestion source.

Parses Claude Code JSONL conversation transcripts to extract personality evidence
from how the user communicates, makes decisions, and handles technical problems.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)


class ClaudeCodeSource(IngestionSource):
    """Ingestion source that parses Claude Code JSONL conversation logs."""

    name = "claude_code"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Parse Claude Code conversation files and extract evidence.

        Args:
            identifier: Path to a JSONL file or directory of JSONL files.
        """
        path = Path(identifier)
        conversations = _load_conversations(path)

        evidence = _format_evidence(conversations)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={"conversation_count": len(conversations)},
            stats={
                "conversations_analyzed": len(conversations),
                "total_user_messages": sum(
                    len(c["user_messages"]) for c in conversations
                ),
                "evidence_length": len(evidence),
            },
        )


def _load_conversations(path: Path) -> list[dict[str, Any]]:
    """Load JSONL conversation files from a path."""
    files: list[Path] = []
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(path.glob("*.jsonl"))
    else:
        logger.warning("Claude Code path not found: %s", path)
        return []

    conversations: list[dict[str, Any]] = []
    for f in files[:50]:  # Cap at 50 files
        try:
            conv = _parse_jsonl(f)
            if conv["user_messages"]:
                conversations.append(conv)
        except Exception as e:
            logger.warning("Failed to parse %s: %s", f, e)

    return conversations


def _parse_jsonl(filepath: Path) -> dict[str, Any]:
    """Parse a single JSONL transcript into structured data."""
    user_messages: list[str] = []
    tool_uses: list[str] = []

    with open(filepath) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = entry.get("type", "")

            # Extract user messages (the human side of the conversation)
            if msg_type == "human" or entry.get("role") == "user":
                content = entry.get("content", "")
                if isinstance(content, str) and content.strip():
                    user_messages.append(content.strip())
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "").strip()
                            if text:
                                user_messages.append(text)

            # Track tool usage patterns
            if msg_type == "tool_use" or (
                isinstance(entry.get("content"), list)
                and any(
                    b.get("type") == "tool_use"
                    for b in entry.get("content", [])
                    if isinstance(b, dict)
                )
            ):
                tool_uses.append(entry.get("name", "unknown"))

    return {
        "file": str(filepath),
        "user_messages": user_messages,
        "tool_uses": tool_uses,
    }


def _format_evidence(conversations: list[dict[str, Any]]) -> str:
    """Format parsed conversations into evidence text for LLM analysis."""
    if not conversations:
        return ""

    sections: list[str] = []

    sections.append(
        "## Claude Code Conversations\n"
        "(These reveal how the developer communicates with AI, their decision-making "
        "style, how they describe problems, and what they prioritize)\n"
    )

    for conv in conversations[:30]:
        messages = conv["user_messages"]
        if not messages:
            continue

        sections.append(f"### Conversation ({len(messages)} messages)")
        for msg in messages[:20]:  # Cap per conversation
            # Truncate very long messages
            if len(msg) > 600:
                msg = msg[:600] + "..."
            sections.append(f"> {msg}")
        sections.append("")

    return "\n".join(sections)
