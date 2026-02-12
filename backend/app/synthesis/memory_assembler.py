"""Memory assembler — deduplicates explorer reports and formats structured markdown.

Also provides LLM-based extraction for skills, traits, and roles (with keyword
fallbacks).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

import litellm

from app.core.config import settings
from app.synthesis.explorers.base import ExplorerReport, MemoryEntry

logger = logging.getLogger(__name__)

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

# Fixed trait definitions: every mini is scored on the same 8 axes.
# Uses a POINT BUDGET system — total across all axes sums to ~50,
# forcing real trade-offs between traits.

TRAIT_DEFINITIONS: list[dict[str, str | list[str]]] = [
    {
        "key": "collaboration",
        "name": "Collaboration",
        "description": "Team player who actively involves others",
        "keywords": ["collaborat", "team", "pair program", "co-author",
                      "together", "we ", "group", "collective", "mentor",
                      "teach", "guide", "onboard", "help others"],
    },
    {
        "key": "directness",
        "name": "Directness",
        "description": "Blunt and straightforward communicator",
        "keywords": ["direct", "blunt", "honest", "straightforward",
                      "frank", "no-nonsense", "opinionat", "strong opinion",
                      "disagree", "pushback", "nack", "reject"],
    },
    {
        "key": "pragmatism",
        "name": "Pragmatism",
        "description": "Ships fast, favors practical solutions over perfection",
        "keywords": ["pragmat", "ship", "practical", "mvp", "good enough",
                      "trade-off", "tradeoff", "iterate", "prototype",
                      "hack", "workaround", "quick", "velocity", "done"],
    },
    {
        "key": "code_quality",
        "name": "Code Quality",
        "description": "Cares deeply about testing, reviews, and clean code",
        "keywords": ["test", "review", "clean code", "quality", "lint",
                      "refactor", "readab", "maintainab", "solid",
                      "coverage", "ci", "type safe", "static analysis"],
    },
    {
        "key": "breadth",
        "name": "Breadth",
        "description": "Works across many domains and technologies",
        "keywords": ["breadth", "polyglot", "full-stack", "fullstack",
                      "generalist", "versatil", "diverse", "multiple lang",
                      "cross-functional", "many project", "wide range"],
    },
    {
        "key": "creativity",
        "name": "Creativity",
        "description": "Innovative thinker, experiments with novel approaches",
        "keywords": ["creativ", "innovat", "experiment", "novel", "unconventional",
                      "unique approach", "hack", "prototype", "side project",
                      "fun", "playful", "humor", "joke", "wit"],
    },
    {
        "key": "communication",
        "name": "Communication",
        "description": "Clear, thorough communicator in docs, PRs, and issues",
        "keywords": ["document", "explain", "comment", "readme", "tutorial",
                      "write-up", "blog", "article", "rfc", "proposal",
                      "description", "thorough", "detailed", "clear"],
    },
    {
        "key": "open_source",
        "name": "Open Source",
        "description": "Active contributor to open source community",
        "keywords": ["open source", "oss", "contributor", "maintain",
                      "community", "foss", "upstream", "patch",
                      "pull request", "public repo", "license"],
    },
]

TRAIT_ORDER = [t["key"] for t in TRAIT_DEFINITIONS]

# Point budget: total across all 8 axes should sum to this
_POINT_BUDGET = 50.0
# Min score per trait (avoids empty-looking charts)
_MIN_SCORE = 2.0
# Maximum possible score
_MAX_SCORE = 10.0


def _raw_score_trait(
    trait: dict[str, str | list[str]],
    all_text: str,
    entry_texts: list[str],
) -> float:
    """Compute a raw (unnormalized) score for a single trait."""
    keywords: list[str] = trait["keywords"]  # type: ignore[assignment]
    all_text_lower = all_text.lower()

    matched_keywords: list[str] = []
    for kw in keywords:
        if kw.lower() in all_text_lower:
            matched_keywords.append(kw)

    entry_hits = 0
    for text in entry_texts:
        text_lower = text.lower()
        if any(kw.lower() in text_lower for kw in keywords):
            entry_hits += 1

    if not matched_keywords:
        return 0.0

    # keyword breadth (0-4) + entry depth (0-3) + base (3)
    keyword_score = min(len(matched_keywords) / max(len(keywords) * 0.3, 1), 1.0) * 4.0
    depth_score = min(entry_hits / 5.0, 1.0) * 3.0
    return 3.0 + keyword_score + depth_score


def extract_values_json(reports: list[ExplorerReport]) -> str:
    """Score standardized developer traits with a point-budget constraint.

    Scores every developer on 8 fixed traits on a 0-10 scale. Total points
    across all axes are normalized to sum to ~50 (avg 6.25), forcing real
    trade-offs. Traits without evidence get the minimum score (2).
    """
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

    entry_texts = [
        f"{e.category} {e.topic} {e.content} {e.evidence_quote}"
        for e in all_entries
    ]
    entry_texts.extend(all_findings)
    all_text = " ".join(entry_texts)

    if not all_text.strip():
        values = [
            {
                "name": t["name"],
                "description": str(t["description"]),
                "intensity": _POINT_BUDGET / len(TRAIT_DEFINITIONS),
            }
            for t in TRAIT_DEFINITIONS
        ]
        return json.dumps({"engineering_values": values})

    # Raw scores
    raw_scores = [_raw_score_trait(t, all_text, entry_texts) for t in TRAIT_DEFINITIONS]

    # Normalize: distribute _POINT_BUDGET across traits proportionally,
    # but ensure each trait gets at least _MIN_SCORE
    total_raw = sum(raw_scores)
    if total_raw == 0:
        normalized = [_POINT_BUDGET / len(TRAIT_DEFINITIONS)] * len(TRAIT_DEFINITIONS)
    else:
        # First pass: scale proportionally
        budget_after_mins = _POINT_BUDGET - (_MIN_SCORE * len(TRAIT_DEFINITIONS))
        normalized = []
        for raw in raw_scores:
            scaled = _MIN_SCORE + (raw / total_raw) * budget_after_mins
            normalized.append(round(min(scaled, _MAX_SCORE), 1))

    values = []
    for i, trait in enumerate(TRAIT_DEFINITIONS):
        values.append({
            "name": str(trait["name"]),
            "description": str(trait["description"]),
            "intensity": normalized[i],
        })

    return json.dumps({"engineering_values": values})


# ── Metadata extraction: roles, skills, traits ─────────────────────────

# Role keywords mapping
_ROLE_KEYWORDS: dict[str, list[str]] = {
    "AI Engineer": ["ai", "machine learning", "ml ", "llm", "deep learning",
                    "neural", "gpt", "transformer", "pytorch", "tensorflow",
                    "model", "nlp", "computer vision", "inference"],
    "Frontend Developer": ["frontend", "react", "vue", "angular", "css",
                           "html", "ui", "ux", "tailwind", "next.js",
                           "svelte", "component", "browser"],
    "Backend Developer": ["backend", "api", "rest", "graphql", "fastapi",
                          "django", "flask", "express", "server", "database",
                          "sql", "microservice"],
    "Full-Stack Developer": ["full-stack", "fullstack", "full stack",
                             "frontend and backend", "end-to-end"],
    "Systems Programmer": ["systems", "kernel", "driver", "firmware",
                           "embedded", "low-level", "assembly", "os ",
                           "operating system", "rust", "c lang", "bare metal"],
    "DevOps Engineer": ["devops", "ci/cd", "deploy", "docker", "kubernetes",
                        "terraform", "aws", "cloud", "infrastructure",
                        "pipeline", "sre", "reliability"],
    "Data Scientist": ["data science", "analytics", "pandas", "jupyter",
                       "statistics", "visualization", "data pipeline",
                       "etl", "sql", "r lang"],
    "Mobile Developer": ["mobile", "ios", "android", "swift", "kotlin",
                         "react native", "flutter", "app store"],
    "Security Engineer": ["security", "vulnerability", "penetration",
                          "cryptograph", "auth", "oauth", "encryption"],
    "Open Source Maintainer": ["maintainer", "open source", "oss", "foss",
                               "upstream", "community", "contributor"],
    "Hardware Hacker": ["hardware", "arduino", "raspberry pi", "iot",
                        "sensor", "circuit", "pcb", "fpga", "3d print"],
    "Game Developer": ["game", "unity", "unreal", "godot", "opengl",
                       "vulkan", "shader", "gamedev"],
}


def _extract_roles_keyword(reports: list[ExplorerReport]) -> str:
    """Keyword-based fallback for role extraction.

    Analyzes expertise and project memory entries to identify roles.
    Returns JSON: {"primary": "...", "secondary": ["...", "..."]}
    """
    relevant_sections = {"expertise", "projects", "workflow", "experiences"}
    text_chunks: list[str] = []

    for report in reports:
        for entry in report.memory_entries:
            cat = _normalize_category(entry.category)
            if cat in relevant_sections:
                text_chunks.append(f"{entry.topic} {entry.content} {entry.evidence_quote}")
        if report.personality_findings:
            text_chunks.append(report.personality_findings)

    all_text = " ".join(text_chunks).lower()

    if not all_text.strip():
        return json.dumps({"primary": "Developer", "secondary": []})

    # Score each role by keyword hits
    role_scores: dict[str, int] = {}
    for role, keywords in _ROLE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in all_text)
        if hits > 0:
            role_scores[role] = hits

    if not role_scores:
        return json.dumps({"primary": "Developer", "secondary": []})

    ranked = sorted(role_scores.items(), key=lambda x: x[1], reverse=True)
    primary = ranked[0][0]
    secondary = [r[0] for r in ranked[1:4] if r[1] >= 2]  # Top 2-3 with min 2 hits

    return json.dumps({"primary": primary, "secondary": secondary})


# Common technology names to look for in evidence
_KNOWN_TECHNOLOGIES = [
    # Languages
    "Python", "TypeScript", "JavaScript", "Rust", "Go", "Java", "C++", "C#",
    "Ruby", "PHP", "Swift", "Kotlin", "Scala", "Elixir", "Haskell", "Lua",
    "Zig", "Nim", "OCaml", "Clojure", "R",
    # Frontend
    "React", "Vue", "Angular", "Svelte", "Next.js", "Nuxt", "Tailwind",
    "HTMX", "Astro",
    # Backend
    "FastAPI", "Django", "Flask", "Express", "Spring", "Rails", "Laravel",
    "Actix", "Axum", "Gin", "Echo", "Phoenix",
    # Data / ML
    "PyTorch", "TensorFlow", "Pandas", "NumPy", "scikit-learn", "Jupyter",
    "Hugging Face", "LangChain",
    # Databases
    "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "DynamoDB",
    "Elasticsearch", "Neo4j", "Cassandra",
    # DevOps / Infra
    "Docker", "Kubernetes", "Terraform", "AWS", "GCP", "Azure", "Vercel",
    "Cloudflare", "Nginx", "GitHub Actions", "Jenkins",
    # Tools
    "Git", "Vim", "Neovim", "VS Code", "Emacs", "tmux", "Nix", "mise",
    "GraphQL", "gRPC", "Kafka", "RabbitMQ",
]


def _extract_skills_keyword(reports: list[ExplorerReport]) -> str:
    """Keyword-based fallback for skill extraction.

    Returns JSON array of up to 15 technology names found in evidence.
    """
    text_chunks: list[str] = []
    for report in reports:
        for entry in report.memory_entries:
            text_chunks.append(f"{entry.topic} {entry.content} {entry.evidence_quote}")
        if report.personality_findings:
            text_chunks.append(report.personality_findings)

    all_text = " ".join(text_chunks)
    all_text_lower = all_text.lower()

    # Match technologies (case-insensitive)
    found: list[tuple[str, int]] = []
    for tech in _KNOWN_TECHNOLOGIES:
        count = all_text_lower.count(tech.lower())
        if count > 0:
            found.append((tech, count))

    # Sort by frequency, take top 15
    found.sort(key=lambda x: x[1], reverse=True)
    skills = [tech for tech, _ in found[:15]]

    return json.dumps(skills)


# Trait patterns to match against personality/communication evidence
_TRAIT_PATTERNS: dict[str, list[str]] = {
    "Casual communicator": ["casual", "informal", "lol", "haha", "emoji",
                            "conversational", "relaxed"],
    "Blunt reviewer": ["blunt", "direct", "harsh", "critical", "nack",
                       "reject", "no-nonsense", "straightforward"],
    "AI-forward": ["ai", "llm", "gpt", "copilot", "machine learning",
                   "automat", "claude", "chatgpt"],
    "Humor in reviews": ["humor", "funny", "joke", "wit", "sarcas",
                         "playful", "lightheart", "lol"],
    "Prefers simplicity": ["simple", "minimal", "kiss", "less is more",
                           "straightforward", "clean", "elegant"],
    "Thorough documenter": ["document", "readme", "tutorial", "explain",
                            "write-up", "blog", "rfc", "thorough"],
    "Strong opinions": ["opinionat", "strong opinion", "disagree",
                        "pushback", "prefer", "always use", "never use"],
    "Mentor figure": ["mentor", "teach", "guide", "onboard", "help",
                      "newcomer", "beginner", "patient"],
    "Performance-focused": ["performance", "optimi", "fast", "benchmark",
                            "latency", "throughput", "efficient", "speed"],
    "Detail-oriented": ["detail", "careful", "thorough", "meticulous",
                        "precise", "correct", "edge case", "corner case"],
    "Open source advocate": ["open source", "oss", "community", "foss",
                             "upstream", "contributor", "public"],
    "Perfectionist": ["perfect", "polish", "refactor", "clean code",
                      "best practice", "standard", "proper"],
    "Rapid prototyper": ["prototype", "hack", "mvp", "quick", "ship",
                         "iterate", "experiment", "try"],
    "Team player": ["team", "collaborat", "pair", "together", "we ",
                    "group", "collective"],
}


def _extract_traits_keyword(reports: list[ExplorerReport]) -> str:
    """Keyword-based fallback for trait extraction.

    Focuses on voice_patterns, communication_style, and personality entries.
    Returns JSON array of up to 8 trait labels.
    """
    relevant_sections = {"voice_patterns", "communication_style", "values",
                         "opinions", "decision_patterns"}
    text_chunks: list[str] = []

    for report in reports:
        for entry in report.memory_entries:
            cat = _normalize_category(entry.category)
            if cat in relevant_sections:
                text_chunks.append(f"{entry.topic} {entry.content} {entry.evidence_quote}")
        if report.personality_findings:
            text_chunks.append(report.personality_findings)
        for q in report.behavioral_quotes:
            quote_text = q.get("quote", "")
            if quote_text:
                text_chunks.append(quote_text)

    all_text = " ".join(text_chunks).lower()

    if not all_text.strip():
        return json.dumps([])

    # Score each trait pattern
    trait_scores: dict[str, int] = {}
    for trait_label, keywords in _TRAIT_PATTERNS.items():
        hits = sum(1 for kw in keywords if kw.lower() in all_text)
        if hits >= 2:  # Require at least 2 keyword matches
            trait_scores[trait_label] = hits

    ranked = sorted(trait_scores.items(), key=lambda x: x[1], reverse=True)
    traits = [label for label, _ in ranked[:8]]

    return json.dumps(traits)


# ── LLM-based extraction functions ──────────────────────────────────────

def _combine_report_text(reports: list[ExplorerReport], include_entries: bool = True) -> str:
    """Build combined text from explorer reports for LLM extraction."""
    parts: list[str] = []
    for report in reports:
        if report.personality_findings:
            parts.append(report.personality_findings)
        if include_entries:
            for entry in report.memory_entries:
                parts.append(f"{entry.topic}: {entry.content}")
    return "\n".join(parts)


def _parse_llm_json(content: str | None) -> str:
    """Extract JSON from LLM response, handling markdown code blocks."""
    content = content or ""
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return content.strip()


async def extract_skills_llm(reports: list[ExplorerReport]) -> str:
    """Use LLM to extract technical skills from explorer reports."""
    combined_text = _combine_report_text(reports, include_entries=True)
    if not combined_text.strip():
        return json.dumps([])

    try:
        response = await litellm.acompletion(
            model=settings.default_llm_model,
            messages=[{
                "role": "user",
                "content": f"""Extract technical skills from this developer profile. Return ONLY a JSON array of skill strings.

Rules:
- Only include skills the developer actively uses (not just mentions)
- "I migrated away from X" does NOT mean they use X
- Use proper casing: "Python" not "python", "TypeScript" not "typescript"
- No single-letter skills unless they're actual languages (e.g., "R", "C")
- Be specific: "React" not "frontend", "PostgreSQL" not "databases"
- Max 20 skills, ordered by proficiency/usage

Developer profile:
{combined_text[:4000]}

Return ONLY a JSON array like: ["Python", "TypeScript", "React", "PostgreSQL"]"""
            }],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        return _parse_llm_json(content)
    except Exception:
        logger.warning("LLM skill extraction failed, falling back to keyword matching")
        return _extract_skills_keyword(reports)


async def extract_traits_llm(reports: list[ExplorerReport]) -> str:
    """Use LLM to extract personality traits from explorer reports."""
    combined_text = _combine_report_text(reports, include_entries=False)
    if not combined_text.strip():
        return json.dumps([])

    try:
        response = await litellm.acompletion(
            model=settings.default_llm_model,
            messages=[{
                "role": "user",
                "content": f"""Extract personality traits from this developer profile. Return ONLY a JSON array of trait strings.

Rules:
- Short descriptive phrases (2-4 words each)
- Focus on engineering personality, not personal life
- Examples: "detail-oriented", "pragmatic problem solver", "strong opinions loosely held"
- Max 10 traits

Developer profile:
{combined_text[:4000]}

Return ONLY a JSON array like: ["pragmatic", "detail-oriented", "collaborative"]"""
            }],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        return _parse_llm_json(content)
    except Exception:
        logger.warning("LLM trait extraction failed, falling back to keyword matching")
        return _extract_traits_keyword(reports)


async def extract_roles_llm(reports: list[ExplorerReport]) -> str:
    """Use LLM to extract developer roles from explorer reports."""
    combined_text = _combine_report_text(reports, include_entries=True)
    if not combined_text.strip():
        return json.dumps({"primary": "Software Engineer", "secondary": []})

    try:
        response = await litellm.acompletion(
            model=settings.default_llm_model,
            messages=[{
                "role": "user",
                "content": f"""Determine this developer's roles from their profile. Return ONLY a JSON object.

Rules:
- primary: Their main role (e.g., "Backend Engineer", "Full-Stack Developer", "DevOps Engineer")
- secondary: Up to 4 secondary roles they also fill
- Be specific about domain when possible

Developer profile:
{combined_text[:4000]}

Return ONLY JSON like: {{"primary": "Backend Engineer", "secondary": ["Open Source Maintainer", "Technical Writer"]}}"""
            }],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        return _parse_llm_json(content)
    except Exception:
        logger.warning("LLM role extraction failed, falling back to keyword matching")
        return _extract_roles_keyword(reports)
