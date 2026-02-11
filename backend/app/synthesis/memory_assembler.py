"""Memory assembler — pure Python, no LLM calls.

Takes a list of ExplorerReports, deduplicates memory entries,
annotates cross-source confirmations, and formats into structured markdown.
"""

from __future__ import annotations

import json
from collections import defaultdict

from app.synthesis.explorers.base import ExplorerReport, MemoryEntry

# Canonical section ordering
SECTIONS = [
    "voice_patterns",
    "communication_style",
    "projects",
    "expertise",
    "values",
    "anti_values",
    "opinions",
    "decision_patterns",
    "experiences",
    "workflow",
]

SECTION_TITLES = {
    "voice_patterns": "Voice & Typing Patterns",
    "communication_style": "Communication Style",
    "projects": "Projects & Open Source",
    "expertise": "Technical Expertise",
    "values": "Engineering Values & Tradeoffs",
    "anti_values": "Anti-Values & Dislikes",
    "opinions": "Technical Opinions",
    "decision_patterns": "Decision Patterns",
    "experiences": "Notable Experiences",
    "workflow": "Workflow & Tools",
}


def _normalize_category(category: str) -> str:
    """Map various category names to canonical section keys."""
    c = category.lower().strip()
    mapping = {
        "voice_pattern": "voice_patterns",
        "voice_patterns": "voice_patterns",
        "voice pattern": "voice_patterns",
        "voice patterns": "voice_patterns",
        "typing_patterns": "voice_patterns",
        "typing patterns": "voice_patterns",
        "communication_style": "communication_style",
        "communication style": "communication_style",
        "comm_style": "communication_style",
        "personality": "communication_style",
        "projects": "projects",
        "project": "projects",
        "open_source": "projects",
        "open source": "projects",
        "expertise": "expertise",
        "technical_expertise": "expertise",
        "technical expertise": "expertise",
        "technologies": "expertise",
        "skills": "expertise",
        "values": "values",
        "engineering_values": "values",
        "engineering values": "values",
        "values_and_tradeoffs": "values",
        "tradeoffs": "values",
        "anti_values": "anti_values",
        "anti-values": "anti_values",
        "anti values": "anti_values",
        "dislikes": "anti_values",
        "pet_peeves": "anti_values",
        "pet peeves": "anti_values",
        "donts": "anti_values",
        "don'ts": "anti_values",
        "opinions": "opinions",
        "technical_opinions": "opinions",
        "technical opinions": "opinions",
        "stances": "opinions",
        "decision_patterns": "decision_patterns",
        "decision patterns": "decision_patterns",
        "decisions": "decision_patterns",
        "patterns": "decision_patterns",
        "experiences": "experiences",
        "notable_experiences": "experiences",
        "notable experiences": "experiences",
        "experience": "experiences",
        "background": "experiences",
        "workflow": "workflow",
        "tools": "workflow",
        "workflow_and_tools": "workflow",
        "workflow & tools": "workflow",
    }
    return mapping.get(c, "experiences")  # Default to experiences


def _dedup_key(entry: MemoryEntry) -> str:
    """Create a deduplication key from category + topic."""
    return f"{_normalize_category(entry.category)}:{entry.topic.lower().strip()}"


def _merge_entries(entries: list[MemoryEntry]) -> MemoryEntry:
    """Merge duplicate entries, keeping the highest-confidence version."""
    if len(entries) == 1:
        return entries[0]

    # Sort by confidence descending, use the best one as base
    entries.sort(key=lambda e: e.confidence, reverse=True)
    best = entries[0]

    # Collect all source types
    sources = {e.source_type for e in entries}

    # Build cross-source annotation
    other_sources = sources - {best.source_type}
    annotation = ""
    if other_sources:
        source_list = ", ".join(sorted(other_sources))
        annotation = f" (also confirmed in {source_list} evidence)"

    # Merge content: use best content + annotation
    merged_content = best.content.rstrip(".") + annotation + "."

    # Combine evidence quotes
    all_quotes = [e.evidence_quote for e in entries if e.evidence_quote]
    merged_quote = " | ".join(dict.fromkeys(all_quotes))  # Deduplicate preserving order

    return MemoryEntry(
        category=best.category,
        topic=best.topic,
        content=merged_content,
        confidence=best.confidence,
        source_type=best.source_type,
        evidence_quote=merged_quote,
    )


def assemble_memory(reports: list[ExplorerReport], username: str = "") -> str:
    """Assemble explorer reports into a structured memory markdown document.

    Deduplicates memory entries by topic, annotates cross-source confirmations,
    and formats into canonical sections.
    """
    if not reports:
        return ""

    # Collect all memory entries
    all_entries: list[MemoryEntry] = []
    for report in reports:
        all_entries.extend(report.memory_entries)

    # Group by dedup key
    grouped: dict[str, list[MemoryEntry]] = defaultdict(list)
    for entry in all_entries:
        key = _dedup_key(entry)
        grouped[key].append(entry)

    # Merge duplicates
    merged: list[MemoryEntry] = [_merge_entries(entries) for entries in grouped.values()]

    # Organize by section
    sections: dict[str, list[MemoryEntry]] = defaultdict(list)
    for entry in merged:
        section = _normalize_category(entry.category)
        sections[section].append(entry)

    # Sort entries within each section by confidence descending
    for entries in sections.values():
        entries.sort(key=lambda e: e.confidence, reverse=True)

    # Build markdown
    title = f"{username}'s Knowledge & Beliefs" if username else "Knowledge & Beliefs"
    lines = [f"# {title}", ""]

    for section_key in SECTIONS:
        entries = sections.get(section_key)
        if not entries:
            continue

        section_title = SECTION_TITLES[section_key]
        lines.append(f"## {section_title}")
        lines.append("")

        for entry in entries:
            # Format entry as bullet point
            line = f"- **{entry.topic}**: {entry.content}"
            if entry.evidence_quote:
                # Truncate very long quotes
                quote = entry.evidence_quote
                if len(quote) > 200:
                    quote = quote[:197] + "..."
                line += f'\n  > "{quote}"'
            lines.append(line)

        lines.append("")

    # Add behavioral quotes section if any
    all_quotes: list[dict] = []
    for report in reports:
        for q in report.behavioral_quotes:
            q_with_source = {**q, "source": report.source_name}
            all_quotes.append(q_with_source)

    if all_quotes:
        lines.append("## Behavioral Quotes")
        lines.append("")
        # Deduplicate by quote text
        seen_quotes: set[str] = set()
        for q in all_quotes:
            quote_text = q.get("quote", "")
            if quote_text in seen_quotes:
                continue
            seen_quotes.add(quote_text)
            context = q.get("context", "")
            signal = q.get("signal_type", "")
            source = q.get("source", "")
            line = f'- "{quote_text}"'
            meta_parts = []
            if context:
                meta_parts.append(context)
            if signal:
                meta_parts.append(f"signal: {signal}")
            if source:
                meta_parts.append(f"from: {source}")
            if meta_parts:
                line += f"\n  *{'; '.join(meta_parts)}*"
            lines.append(line)
        lines.append("")

    # Source summary
    source_names = [r.source_name for r in reports]
    lines.append("---")
    lines.append(
        f"*Assembled from {len(reports)} source(s): {', '.join(source_names)}. "
        f"{len(merged)} unique memory entries.*"
    )
    lines.append("")

    return "\n".join(lines)



# ── Standardized developer traits for radar chart ──────────────────────

# Fixed trait definitions: every mini is scored on the same axes.
# Each trait has a key, display name, category, description, and keywords
# used to match against explorer memory entries.

TRAIT_DEFINITIONS: list[dict[str, str | list[str]]] = [
    # Personality traits
    {
        "key": "collaboration",
        "name": "Collaboration",
        "category": "Personality",
        "description": "Team player who actively involves others",
        "keywords": ["collaborat", "team", "pair program", "co-author",
                      "together", "we ", "group", "collective"],
    },
    {
        "key": "mentoring",
        "name": "Mentoring",
        "category": "Personality",
        "description": "Teaches, guides, and uplifts other developers",
        "keywords": ["mentor", "teach", "guide", "explain", "onboard",
                      "newcomer", "beginner", "junior", "help others",
                      "education", "tutorial", "documentation"],
    },
    {
        "key": "directness",
        "name": "Directness",
        "category": "Personality",
        "description": "Blunt and straightforward communicator",
        "keywords": ["direct", "blunt", "honest", "straightforward",
                      "frank", "no-nonsense", "opinionat", "strong opinion",
                      "disagree", "pushback", "nack", "reject"],
    },
    {
        "key": "humor",
        "name": "Humor",
        "category": "Personality",
        "description": "Uses humor and wit in technical contexts",
        "keywords": ["humor", "funny", "joke", "wit", "sarcas", "lol",
                      "haha", "emoji", "playful", "lightheart"],
    },
    # Coding traits
    {
        "key": "systems",
        "name": "Systems",
        "category": "Coding",
        "description": "Low-level systems programming (C, Rust, OS, firmware)",
        "keywords": ["systems", "kernel", "driver", "firmware", "embedded",
                      "low-level", "assembly", "memory manage", "c lang",
                      " c ", "rust", "os ", "operating system", "linux kernel",
                      "bare metal", "real-time"],
    },
    {
        "key": "web",
        "name": "Web",
        "category": "Coding",
        "description": "Web development, frontend and backend",
        "keywords": ["web", "frontend", "backend", "react", "vue", "angular",
                      "next.js", "node", "django", "flask", "fastapi", "html",
                      "css", "javascript", "typescript", "api", "rest",
                      "graphql", "http", "browser"],
    },
    {
        "key": "devops",
        "name": "DevOps",
        "category": "Coding",
        "description": "Infrastructure, CI/CD, and deployment",
        "keywords": ["devops", "ci/cd", "deploy", "docker", "kubernetes",
                      "terraform", "aws", "cloud", "infrastructure",
                      "pipeline", "github actions", "jenkins", "monitoring",
                      "sre", "reliability", "scaling"],
    },
    {
        "key": "ai_ml",
        "name": "AI/ML",
        "category": "Coding",
        "description": "AI, machine learning, LLMs, and data science",
        "keywords": ["machine learning", "ml ", "ai ", "deep learning",
                      "neural", "llm", "gpt", "transformer", "model",
                      "training", "inference", "pytorch", "tensorflow",
                      "data science", "nlp", "computer vision"],
    },
    # Engineering traits
    {
        "key": "code_quality",
        "name": "Code Quality",
        "category": "Engineering",
        "description": "Cares deeply about testing, reviews, and clean code",
        "keywords": ["test", "review", "clean code", "quality", "lint",
                      "refactor", "readab", "maintainab", "solid",
                      "coverage", "ci", "type safe", "static analysis"],
    },
    {
        "key": "pragmatism",
        "name": "Pragmatism",
        "category": "Engineering",
        "description": "Ships fast, favors practical solutions over perfection",
        "keywords": ["pragmat", "ship", "practical", "mvp", "good enough",
                      "trade-off", "tradeoff", "iterate", "prototype",
                      "hack", "workaround", "quick", "velocity", "done"],
    },
    {
        "key": "open_source",
        "name": "Open Source",
        "category": "Engineering",
        "description": "Active contributor to open source community",
        "keywords": ["open source", "oss", "contributor", "maintain",
                      "community", "foss", "upstream", "patch",
                      "pull request", "public repo", "license"],
    },
    {
        "key": "breadth",
        "name": "Breadth",
        "category": "Engineering",
        "description": "Works across many domains and technologies",
        "keywords": ["breadth", "polyglot", "full-stack", "fullstack",
                      "generalist", "versatil", "diverse", "multiple lang",
                      "cross-functional", "many project", "wide range"],
    },
]

# Default score for traits with zero evidence (avoids empty-looking charts)
_DEFAULT_SCORE = 2.0
# Maximum possible score
_MAX_SCORE = 10.0


def _score_trait(
    trait: dict[str, str | list[str]],
    all_text: str,
    entry_texts: list[str],
) -> tuple[float, str]:
    """Score a single trait on 0-10 by counting keyword matches in evidence.

    Returns (score, description) where description summarizes the evidence found.
    """
    keywords: list[str] = trait["keywords"]  # type: ignore[assignment]
    all_text_lower = all_text.lower()

    # Count how many unique keywords match anywhere in the corpus
    matched_keywords: list[str] = []
    for kw in keywords:
        if kw.lower() in all_text_lower:
            matched_keywords.append(kw)

    # Count how many individual entries mention at least one keyword
    entry_hits = 0
    for text in entry_texts:
        text_lower = text.lower()
        if any(kw.lower() in text_lower for kw in keywords):
            entry_hits += 1

    if not matched_keywords:
        return _DEFAULT_SCORE, str(trait["description"])

    # Score formula: base + keyword breadth + entry depth (capped at 10)
    # - Base: 3 (we found something)
    # - Keyword breadth: up to 4 points (more distinct keywords = broader evidence)
    # - Entry depth: up to 3 points (more entries mentioning this = stronger signal)
    keyword_score = min(len(matched_keywords) / max(len(keywords) * 0.3, 1), 1.0) * 4.0
    depth_score = min(entry_hits / 5.0, 1.0) * 3.0
    score = 3.0 + keyword_score + depth_score
    score = round(min(score, _MAX_SCORE), 1)

    return score, str(trait["description"])


def extract_values_json(reports: list[ExplorerReport]) -> str:
    """Score standardized developer traits from explorer reports for the radar chart.

    Scores every developer on the same 12 fixed traits (personality, coding,
    engineering) on a 0-10 scale based on keyword evidence in memory entries
    and findings. Traits without evidence get a low default score (2), not 0.
    Returns JSON matching the MiniDetail.parse_values() schema.
    """
    # Build a corpus of searchable text from all reports
    all_entries: list[MemoryEntry] = []
    all_findings: list[str] = []
    for report in reports:
        all_entries.extend(report.memory_entries)
        if report.personality_findings:
            all_findings.append(report.personality_findings)
        for q in report.behavioral_quotes:
            quote_text = q.get("quote", "")
            if quote_text:
                all_findings.append(quote_text)

    # Individual text chunks for depth scoring
    entry_texts = [
        f"{e.category} {e.topic} {e.content} {e.evidence_quote}"
        for e in all_entries
    ]
    entry_texts.extend(all_findings)

    # Combined corpus for keyword presence checks
    all_text = " ".join(entry_texts)

    if not all_text.strip():
        # No evidence at all — return defaults
        values = [
            {
                "name": t["name"],
                "description": str(t["description"]),
                "intensity": _DEFAULT_SCORE,
            }
            for t in TRAIT_DEFINITIONS
        ]
        return json.dumps({"engineering_values": values})

    # Score each trait
    values = []
    for trait in TRAIT_DEFINITIONS:
        score, description = _score_trait(trait, all_text, entry_texts)
        values.append({
            "name": str(trait["name"]),
            "description": description,
            "intensity": score,
        })

    return json.dumps({"engineering_values": values})
