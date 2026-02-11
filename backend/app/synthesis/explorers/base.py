"""Explorer base class and schemas for agentic evidence exploration."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from app.core.agent import AgentTool, run_agent
from app.core.llm import llm_completion

logger = logging.getLogger(__name__)


# --- Schemas ---


class MemoryEntry(BaseModel):
    """A single factual memory extracted from evidence."""

    category: str
    topic: str
    content: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_type: str
    evidence_quote: str = ""


class ExplorerReport(BaseModel):
    """Output of an explorer's analysis of a single evidence source."""

    source_name: str
    personality_findings: str  # Markdown
    memory_entries: list[MemoryEntry] = Field(default_factory=list)
    behavioral_quotes: list[dict] = Field(default_factory=list)
    # Each dict has keys: context, quote, signal_type
    confidence_summary: str = ""


# --- Explorer ABC ---


class Explorer(ABC):
    """Base class for evidence explorers.

    Subclasses define system_prompt() and user_prompt() to specialize the agent
    for a particular evidence source (GitHub, Claude Code, etc.). The concrete
    explore() method handles agent orchestration.
    """

    source_name: str = "base"

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this explorer's agent."""
        ...

    @abstractmethod
    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        """Return the user prompt for this explorer's agent."""
        ...

    async def explore(
        self, username: str, evidence: str, raw_data: dict
    ) -> ExplorerReport:
        """Run the explorer agent and collect results into an ExplorerReport."""
        # Local accumulators
        memories: list[MemoryEntry] = []
        findings: list[str] = []
        quotes: list[dict] = []
        finished = False

        # --- Tool handlers ---

        async def save_memory(
            category: str,
            topic: str,
            content: str,
            confidence: float,
            evidence_quote: str = "",
        ) -> str:
            entry = MemoryEntry(
                category=category,
                topic=topic,
                content=content,
                confidence=confidence,
                source_type=self.source_name,
                evidence_quote=evidence_quote,
            )
            memories.append(entry)
            return f"Saved memory: {category}/{topic}"

        async def save_finding(finding: str) -> str:
            findings.append(finding)
            return "Finding saved."

        async def save_quote(
            context: str, quote: str, signal_type: str
        ) -> str:
            quotes.append(
                {"context": context, "quote": quote, "signal_type": signal_type}
            )
            return "Quote saved."

        async def analyze_deeper(subset: str, question: str) -> str:
            result = await llm_completion(
                prompt=(
                    f"Given this evidence subset:\n\n{subset}\n\n"
                    f"Answer this question: {question}\n\n"
                    "Be specific and cite evidence."
                ),
                system="You are an expert at analyzing developer behavior from code artifacts.",
            )
            return result

        async def finish(summary: str = "") -> str:
            nonlocal finished
            finished = True
            return "Exploration complete."

        # --- Build tool list ---

        tools = [
            AgentTool(
                name="save_memory",
                description="Save a factual memory entry about the developer.",
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Category (e.g., projects, expertise, values, opinions, workflow)",
                        },
                        "topic": {
                            "type": "string",
                            "description": "Specific topic within the category",
                        },
                        "content": {
                            "type": "string",
                            "description": "The factual content of this memory",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence level 0.0-1.0",
                        },
                        "evidence_quote": {
                            "type": "string",
                            "description": "Exact quote from evidence supporting this memory",
                        },
                    },
                    "required": ["category", "topic", "content", "confidence"],
                },
                handler=save_memory,
            ),
            AgentTool(
                name="save_finding",
                description="Save a personality or behavioral finding as markdown text.",
                parameters={
                    "type": "object",
                    "properties": {
                        "finding": {
                            "type": "string",
                            "description": "Markdown-formatted personality finding",
                        },
                    },
                    "required": ["finding"],
                },
                handler=save_finding,
            ),
            AgentTool(
                name="save_quote",
                description="Save a behavioral quote with context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "string",
                            "description": "Where/when this quote appeared",
                        },
                        "quote": {
                            "type": "string",
                            "description": "The exact quote",
                        },
                        "signal_type": {
                            "type": "string",
                            "description": "What this quote signals (e.g., communication_style, technical_opinion, humor)",
                        },
                    },
                    "required": ["context", "quote", "signal_type"],
                },
                handler=save_quote,
            ),
            AgentTool(
                name="analyze_deeper",
                description="Make a secondary LLM call to analyze a subset of evidence in more depth.",
                parameters={
                    "type": "object",
                    "properties": {
                        "subset": {
                            "type": "string",
                            "description": "The evidence subset to analyze",
                        },
                        "question": {
                            "type": "string",
                            "description": "Specific question to answer about this evidence",
                        },
                    },
                    "required": ["subset", "question"],
                },
                handler=analyze_deeper,
            ),
            AgentTool(
                name="finish",
                description="Signal that exploration is complete. Call this when you have thoroughly analyzed all evidence.",
                parameters={
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Brief summary of findings",
                        },
                    },
                    "required": [],
                },
                handler=finish,
            ),
        ]

        # Include any extra tools from subclasses
        extra = getattr(self, "_extra_tools", [])
        if extra:
            tools.extend(extra)

        # --- Run agent ---

        logger.info(
            "Running %s explorer for %s (%d chars evidence, %d tools)",
            self.source_name,
            username,
            len(evidence),
            len(tools),
        )

        result = await run_agent(
            system_prompt=self.system_prompt(),
            user_prompt=self.user_prompt(username, evidence, raw_data),
            tools=tools,
            max_turns=25,
        )

        logger.info(
            "%s explorer completed in %d turns: %d memories, %d findings, %d quotes",
            self.source_name,
            result.turns_used,
            len(memories),
            len(findings),
            len(quotes),
        )

        # If fallback produced JSON, try to parse it
        if not memories and not findings and result.final_response:
            try:
                data = json.loads(result.final_response)
                if isinstance(data.get("personality_findings"), str):
                    findings.append(data["personality_findings"])
                for entry in data.get("memory_entries", []):
                    try:
                        entry["source_type"] = self.source_name
                        # Fill in defaults for fields the LLM might omit
                        entry.setdefault("confidence", 0.7)
                        entry.setdefault("evidence_quote", "")
                        memories.append(MemoryEntry(**entry))
                    except Exception:
                        # Skip malformed entries
                        continue
                for q in data.get("behavioral_quotes", []):
                    if isinstance(q, dict):
                        quotes.append(q)
            except (json.JSONDecodeError, KeyError, TypeError):
                # Use the raw text as a finding
                if result.final_response:
                    findings.append(result.final_response)

        return ExplorerReport(
            source_name=self.source_name,
            personality_findings="\n\n".join(findings),
            memory_entries=memories,
            behavioral_quotes=quotes,
            confidence_summary=f"Completed in {result.turns_used} turns with {len(memories)} memories extracted.",
        )
