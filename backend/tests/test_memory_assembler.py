"""Tests for backend/app/synthesis/memory_assembler.py."""

from __future__ import annotations

import json

from app.synthesis.memory_assembler import (
    _dedup_key,
    _extract_roles_keyword,
    _extract_skills_keyword,
    _extract_traits_keyword,
    _merge_entries,
    _normalize_category,
    assemble_memory,
    extract_values_json,
)
from tests.conftest import make_memory, make_report


# ── _normalize_category ──────────────────────────────────────────────


class TestNormalizeCategory:
    def test_voice_pattern_aliases(self):
        assert _normalize_category("voice_pattern") == "voice_patterns"
        assert _normalize_category("voice_patterns") == "voice_patterns"
        assert _normalize_category("voice pattern") == "voice_patterns"
        assert _normalize_category("typing_patterns") == "voice_patterns"
        assert _normalize_category("typing patterns") == "voice_patterns"

    def test_communication_aliases(self):
        assert _normalize_category("communication_style") == "communication_style"
        assert _normalize_category("comm_style") == "communication_style"
        assert _normalize_category("personality") == "communication_style"

    def test_project_aliases(self):
        assert _normalize_category("projects") == "projects"
        assert _normalize_category("project") == "projects"
        assert _normalize_category("open_source") == "projects"

    def test_expertise_aliases(self):
        assert _normalize_category("expertise") == "expertise"
        assert _normalize_category("technical_expertise") == "expertise"
        assert _normalize_category("skills") == "expertise"
        assert _normalize_category("technologies") == "expertise"

    def test_values_aliases(self):
        assert _normalize_category("values") == "values"
        assert _normalize_category("engineering_values") == "values"
        assert _normalize_category("tradeoffs") == "values"

    def test_anti_values_aliases(self):
        assert _normalize_category("anti_values") == "anti_values"
        assert _normalize_category("dislikes") == "anti_values"
        assert _normalize_category("pet_peeves") == "anti_values"
        assert _normalize_category("don'ts") == "anti_values"

    def test_opinion_aliases(self):
        assert _normalize_category("opinions") == "opinions"
        assert _normalize_category("technical_opinions") == "opinions"
        assert _normalize_category("stances") == "opinions"

    def test_decision_aliases(self):
        assert _normalize_category("decision_patterns") == "decision_patterns"
        assert _normalize_category("decisions") == "decision_patterns"
        assert _normalize_category("patterns") == "decision_patterns"

    def test_experience_aliases(self):
        assert _normalize_category("experiences") == "experiences"
        assert _normalize_category("notable_experiences") == "experiences"
        assert _normalize_category("background") == "experiences"

    def test_workflow_aliases(self):
        assert _normalize_category("workflow") == "workflow"
        assert _normalize_category("tools") == "workflow"
        assert _normalize_category("workflow_and_tools") == "workflow"
        assert _normalize_category("workflow & tools") == "workflow"

    def test_unknown_defaults_to_experiences(self):
        assert _normalize_category("random_junk") == "experiences"
        assert _normalize_category("") == "experiences"
        assert _normalize_category("something_totally_new") == "experiences"

    def test_case_insensitive(self):
        assert _normalize_category("VOICE_PATTERN") == "voice_patterns"
        assert _normalize_category("Expertise") == "expertise"

    def test_strips_whitespace(self):
        assert _normalize_category("  expertise  ") == "expertise"


# ── _dedup_key ───────────────────────────────────────────────────────


class TestDedupKey:
    def test_normalizes_category_and_lowercases_topic(self):
        entry = make_memory(category="voice_pattern", topic="Emoji Usage")
        key = _dedup_key(entry)
        assert key == "voice_patterns:emoji usage"

    def test_strips_topic_whitespace(self):
        entry = make_memory(category="expertise", topic="  Python  ")
        key = _dedup_key(entry)
        assert key == "expertise:python"

    def test_same_key_for_aliases(self):
        e1 = make_memory(category="dislikes", topic="Tabs")
        e2 = make_memory(category="anti_values", topic="tabs")
        assert _dedup_key(e1) == _dedup_key(e2)


# ── _merge_entries ───────────────────────────────────────────────────


class TestMergeEntries:
    def test_single_entry_returns_unchanged(self):
        entry = make_memory(content="Uses Rust.", confidence=0.8)
        result = _merge_entries([entry])
        assert result.content == "Uses Rust."
        assert result.confidence == 0.8

    def test_multiple_entries_keeps_highest_confidence(self):
        e1 = make_memory(
            content="Loves Python.",
            confidence=0.6,
            source_type="blog",
            evidence_quote="python is great",
        )
        e2 = make_memory(
            content="Uses Python extensively.",
            confidence=0.95,
            source_type="github",
            evidence_quote="I use python daily",
        )
        result = _merge_entries([e1, e2])
        assert result.confidence == 0.95
        assert result.source_type == "github"

    def test_multiple_entries_annotates_cross_source(self):
        e1 = make_memory(
            content="Prefers simplicity.",
            confidence=0.7,
            source_type="blog",
            evidence_quote="keep it simple",
        )
        e2 = make_memory(
            content="Simplicity is key.",
            confidence=0.9,
            source_type="github",
            evidence_quote="simple is better",
        )
        result = _merge_entries([e1, e2])
        assert "(also confirmed in blog evidence)" in result.content

    def test_multiple_entries_merges_evidence_quotes(self):
        e1 = make_memory(evidence_quote="quote A", confidence=0.8, source_type="a")
        e2 = make_memory(evidence_quote="quote B", confidence=0.7, source_type="b")
        result = _merge_entries([e1, e2])
        assert "quote A" in result.evidence_quote
        assert "quote B" in result.evidence_quote
        assert " | " in result.evidence_quote


# ── assemble_memory ──────────────────────────────────────────────────


class TestAssembleMemory:
    def test_empty_reports_returns_empty_string(self):
        assert assemble_memory([]) == ""

    def test_sections_have_correct_headers(self):
        entries = [
            make_memory(category="expertise", topic="Rust", content="Uses Rust."),
            make_memory(category="values", topic="Simplicity", content="Prefers simple code."),
            make_memory(category="voice_patterns", topic="Emoji", content="Uses emoji."),
        ]
        report = make_report(memory_entries=entries)
        result = assemble_memory([report], username="testuser")

        assert "# testuser's Unified Memory" in result
        assert "## Voice & Typing Patterns" in result
        assert "## Technical Expertise" in result
        assert "## Engineering Values & Tradeoffs" in result

    def test_sections_appear_in_canonical_order(self):
        entries = [
            make_memory(category="workflow", topic="Neovim", content="Uses Neovim."),
            make_memory(category="voice_patterns", topic="Caps", content="Uses ALL CAPS."),
            make_memory(category="expertise", topic="Go", content="Expert in Go."),
        ]
        report = make_report(memory_entries=entries)
        result = assemble_memory([report])

        voice_pos = result.index("Voice & Typing Patterns")
        expertise_pos = result.index("Technical Expertise")
        workflow_pos = result.index("Workflow & Tools")
        assert voice_pos < expertise_pos < workflow_pos

    def test_dedup_merges_across_sources(self):
        e1 = make_memory(
            category="expertise",
            topic="Python",
            content="Loves Python.",
            confidence=0.9,
            source_type="github",
        )
        e2 = make_memory(
            category="expertise",
            topic="Python",
            content="Uses Python daily.",
            confidence=0.8,
            source_type="blog",
        )
        r1 = make_report(source_name="github", memory_entries=[e1])
        r2 = make_report(source_name="blog", memory_entries=[e2])
        result = assemble_memory([r1, r2])

        # Should appear only once in output with cross-source annotation
        assert result.count("**Python**") == 1
        assert "also confirmed in blog evidence" in result

    def test_behavioral_quotes_section(self):
        report = make_report(
            behavioral_quotes=[
                {"quote": "LGTM but needs tests", "context": "PR review", "signal_type": "values"},
            ]
        )
        result = assemble_memory([report])
        assert "## Behavioral Quotes" in result
        assert "LGTM but needs tests" in result

    def test_source_summary_at_end(self):
        report = make_report(
            source_name="github",
            memory_entries=[make_memory()],
        )
        result = assemble_memory([report])
        assert "Assembled from 1 source(s): github" in result

    def test_no_username_title(self):
        report = make_report(memory_entries=[make_memory()])
        result = assemble_memory([report])
        assert "# Unified Memory" in result


# ── extract_values_json ──────────────────────────────────────────────


class TestExtractValuesJson:
    def test_point_budget_sums_to_approximately_50(self):
        entries = [
            make_memory(
                category="expertise",
                topic="Testing",
                content="Writes comprehensive tests with good coverage.",
                evidence_quote="always write tests first, test coverage is important",
            ),
            make_memory(
                category="values",
                topic="Simplicity",
                content="Prefers simple pragmatic solutions over perfect ones.",
                evidence_quote="ship fast, iterate, good enough for MVP",
            ),
            make_memory(
                category="communication_style",
                topic="Documentation",
                content="Documents everything thoroughly with detailed READMEs.",
                evidence_quote="the readme tutorial explains how to use it",
            ),
            make_memory(
                category="projects",
                topic="Open source",
                content="Active open source contributor and maintainer.",
                evidence_quote="open source community contributor upstream",
            ),
        ]
        report = make_report(memory_entries=entries)
        result_json = extract_values_json([report])
        data = json.loads(result_json)
        values = data["engineering_values"]
        total = sum(v["intensity"] for v in values)
        # Allow tolerance since rounding and clamping can cause slight deviation
        assert 45 <= total <= 55, f"Point budget total was {total}, expected ~50"

    def test_empty_evidence_returns_defaults(self):
        report = make_report()
        result_json = extract_values_json([report])
        data = json.loads(result_json)
        values = data["engineering_values"]
        assert len(values) == 8
        # All should be equal when no evidence
        intensities = [v["intensity"] for v in values]
        assert len(set(intensities)) == 1  # All the same

    def test_has_exactly_8_traits(self):
        report = make_report(memory_entries=[make_memory()])
        result_json = extract_values_json([report])
        data = json.loads(result_json)
        assert len(data["engineering_values"]) == 8

    def test_traits_have_required_fields(self):
        report = make_report(memory_entries=[make_memory()])
        result_json = extract_values_json([report])
        data = json.loads(result_json)
        for val in data["engineering_values"]:
            assert "name" in val
            assert "description" in val
            assert "intensity" in val
            assert isinstance(val["intensity"], (int, float))

    def test_no_score_below_minimum(self):
        entries = [
            make_memory(
                category="expertise",
                topic="Rust",
                content="Systems programmer writing Rust for low-level code.",
                evidence_quote="rust kernel driver embedded bare metal",
            ),
        ]
        report = make_report(memory_entries=entries)
        result_json = extract_values_json([report])
        data = json.loads(result_json)
        for val in data["engineering_values"]:
            assert val["intensity"] >= 2.0, (
                f"{val['name']} scored below minimum: {val['intensity']}"
            )


# ── extract_roles ────────────────────────────────────────────────────


class TestExtractRoles:
    def test_returns_json_with_primary_and_secondary(self):
        entries = [
            make_memory(
                category="expertise",
                topic="ML",
                content="Builds machine learning models with PyTorch and deep learning.",
                evidence_quote="ai neural transformer pytorch model",
            ),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_roles_keyword([report]))
        assert "primary" in result
        assert "secondary" in result
        assert isinstance(result["primary"], str)
        assert isinstance(result["secondary"], list)

    def test_empty_evidence_returns_developer(self):
        report = make_report()
        result = json.loads(_extract_roles_keyword([report]))
        assert result["primary"] == "Developer"
        assert result["secondary"] == []

    def test_identifies_matching_role(self):
        entries = [
            make_memory(
                category="expertise",
                topic="React",
                content="Builds React frontends with Next.js and Tailwind CSS.",
                evidence_quote="frontend react vue angular css html ui ux tailwind next.js svelte component browser",
            ),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_roles_keyword([report]))
        assert result["primary"] == "Frontend Developer"


# ── extract_skills ───────────────────────────────────────────────────


class TestExtractSkills:
    def test_returns_json_array_of_strings(self):
        entries = [
            make_memory(
                category="expertise",
                topic="Stack",
                content="Uses Python, TypeScript, and Docker.",
                evidence_quote="Python TypeScript Docker",
            ),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_skills_keyword([report]))
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_finds_known_technologies(self):
        entries = [
            make_memory(
                category="expertise",
                topic="Stack",
                content="Uses Python and FastAPI with PostgreSQL and Redis.",
                evidence_quote="Python FastAPI PostgreSQL Redis",
            ),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_skills_keyword([report]))
        assert "Python" in result
        assert "FastAPI" in result
        assert "PostgreSQL" in result
        assert "Redis" in result

    def test_max_15_skills(self):
        # Create evidence with many technology mentions
        tech_text = " ".join(
            [
                "Python TypeScript JavaScript Rust Go Java C++ Ruby PHP Swift Kotlin",
                "React Vue Angular Svelte Next.js Docker Kubernetes Terraform",
            ]
        )
        entries = [
            make_memory(content=tech_text, evidence_quote=tech_text),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_skills_keyword([report]))
        assert len(result) <= 15

    def test_empty_evidence_returns_empty(self):
        report = make_report()
        result = json.loads(_extract_skills_keyword([report]))
        assert result == []


# ── extract_traits ───────────────────────────────────────────────────


class TestExtractTraits:
    def test_returns_json_array_of_strings(self):
        entries = [
            make_memory(
                category="voice_patterns",
                topic="Humor",
                content="Uses humor and jokes in reviews with playful lighthearted tone.",
                evidence_quote="lol haha that's funny, humor joke wit sarcas playful",
            ),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_traits_keyword([report]))
        assert isinstance(result, list)
        assert all(isinstance(t, str) for t in result)

    def test_max_8_traits(self):
        # Provide evidence that triggers many trait patterns
        big_text = (
            "casual informal lol haha emoji conversational relaxed "
            "blunt direct harsh critical nack reject straightforward "
            "ai llm gpt copilot machine learning automat claude "
            "humor funny joke wit sarcas playful lightheart "
            "simple minimal kiss less is more clean elegant "
            "document readme tutorial explain write-up blog rfc "
            "opinionat strong opinion disagree pushback prefer "
            "mentor teach guide onboard help newcomer beginner "
        )
        entries = [
            make_memory(
                category="voice_patterns",
                topic="All",
                content=big_text,
                evidence_quote=big_text,
            ),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_traits_keyword([report]))
        assert len(result) <= 8

    def test_empty_evidence_returns_empty(self):
        report = make_report()
        result = json.loads(_extract_traits_keyword([report]))
        assert result == []

    def test_requires_minimum_2_keyword_hits(self):
        # Only one keyword hit per trait should not be enough
        entries = [
            make_memory(
                category="communication_style",
                topic="Tone",
                content="Is casual.",
                evidence_quote="casual",
            ),
        ]
        report = make_report(memory_entries=entries)
        result = json.loads(_extract_traits_keyword([report]))
        # "Casual communicator" needs >= 2 keyword hits; only "casual" matches once
        assert "Casual communicator" not in result
