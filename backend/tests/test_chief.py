"""Tests for backend/app/synthesis/chief.py — constants and prompt integrity."""

from __future__ import annotations

from app.synthesis.chief import (
    AUTHENTICITY_LOOP_SYNTHESIS_BLOCK,
    CHIEF_FINAL_SYNTHESIS_PROMPT,
    NARRATIVE_ASPECTS,
    SECTION_ORDER,
    SYSTEM_PROMPT,
)


class TestSectionOrder:
    def test_contains_eight_sections(self):
        assert len(SECTION_ORDER) == 8

    def test_known_sections_present(self):
        expected = [
            "Identity Core",
            "Voice & Style",
            "Personality & Emotional Patterns",
            "Values & Beliefs",
            "Anti-Values & DON'Ts",
            "Conflict & Pushback",
            "VOICE FRAMEWORK",
            "Quirks & Imperfection",
        ]
        assert SECTION_ORDER == expected

    def test_identity_core_is_first(self):
        assert SECTION_ORDER[0] == "Identity Core"

    def test_voice_style_is_second(self):
        assert SECTION_ORDER[1] == "Voice & Style"


class TestNarrativeAspects:
    def test_all_aspects_are_strings(self):
        assert all(isinstance(a, str) for a in NARRATIVE_ASPECTS)

    def test_voice_signature_present(self):
        assert "voice_signature" in NARRATIVE_ASPECTS

    def test_no_duplicate_aspects(self):
        assert len(NARRATIVE_ASPECTS) == len(set(NARRATIVE_ASPECTS))


class TestSystemPrompt:
    def test_system_prompt_is_non_empty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_mentions_second_person_writing(self):
        assert "second person" in SYSTEM_PROMPT.lower() or "You ARE" in SYSTEM_PROMPT

    def test_mentions_forgery_manual_anchor(self):
        assert "Forgery Manual" in SYSTEM_PROMPT or "forgery manual" in SYSTEM_PROMPT.lower()

    def test_prompts_include_authenticity_loop(self):
        assert "AUTHENTICITY LOOP" in AUTHENTICITY_LOOP_SYNTHESIS_BLOCK
        assert "{authenticity_loop_block}" in SYSTEM_PROMPT or "AUTHENTICITY LOOP" in SYSTEM_PROMPT
        assert "{authenticity_loop_block}" in CHIEF_FINAL_SYNTHESIS_PROMPT

    def test_prompts_avoid_absolute_style_bans(self):
        assert "Never use em-dashes" not in SYSTEM_PROMPT
        assert "Never use em-dashes" not in CHIEF_FINAL_SYNTHESIS_PROMPT

    def test_system_prompt_uses_abductive_filtering_not_brittle_banned_phrase_list(self):
        assert "BANNED PHRASES" not in SYSTEM_PROMPT
        assert "Brittle denylists are not the method." in SYSTEM_PROMPT

    def test_system_prompt_requires_no_meta_labels_when_evidence_is_thin(self):
        assert "do not emit a meta-label; mark it as unknown/uncertain" in SYSTEM_PROMPT
