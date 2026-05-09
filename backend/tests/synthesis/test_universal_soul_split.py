"""Tests for the universal-vs-soul prompt split (MINI-111 / Wave 2E).

Universal prompt = constant text shared across every mini.
Soul prompt = per-mini cargo (identity, narratives, frameworks, knowledge).
Assembled chat prompt = UNIVERSAL_MINI_PROMPT + soul_prompt.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.synthesis.prompt_renderer import CHAT_PROMPT_PRESET, render_runtime_system_prompt
from app.synthesis.spirit import build_soul_prompt, build_system_prompt
from app.synthesis.universal_prompt import UNIVERSAL_MINI_PROMPT, build_full_system_prompt


# ---------------------------------------------------------------------------
# Universal prompt — content + invariants
# ---------------------------------------------------------------------------


class TestUniversalPrompt:
    def test_universal_prompt_is_non_empty_constant(self):
        assert isinstance(UNIVERSAL_MINI_PROMPT, str)
        assert len(UNIVERSAL_MINI_PROMPT) > 500

    def test_universal_prompt_states_what_a_mini_is(self):
        assert "you are a mini" in UNIVERSAL_MINI_PROMPT.lower()

    def test_universal_prompt_states_prediction_goal(self):
        assert "prediction" in UNIVERSAL_MINI_PROMPT.lower()
        assert "regurgitation" in UNIVERSAL_MINI_PROMPT.lower()

    def test_universal_prompt_documents_tools(self):
        assert "search_memories" in UNIVERSAL_MINI_PROMPT
        assert "search_evidence" in UNIVERSAL_MINI_PROMPT
        assert "apply_framework" in UNIVERSAL_MINI_PROMPT

    def test_universal_prompt_includes_abductive_loop(self):
        assert "ABDUCTIVE AUTHENTICITY LOOP" in UNIVERSAL_MINI_PROMPT
        assert "DEGREE MATCHING" in UNIVERSAL_MINI_PROMPT

    def test_universal_prompt_includes_privacy_rules(self):
        assert "PRIVATE" in UNIVERSAL_MINI_PROMPT
        assert "paraphrased" in UNIVERSAL_MINI_PROMPT.lower()

    def test_universal_prompt_does_not_name_a_specific_mini(self):
        # The universal prompt must be neutral — no concrete username/handle
        # baked in. Specific names live in the per-mini soul prompt.
        for handle in ("torvalds", "dhh", "alliecatowo", "jlongster"):
            assert handle not in UNIVERSAL_MINI_PROMPT

    def test_universal_prompt_does_not_lock_in_specific_phrases(self):
        # Anti-hyperfitting guard — never enumerate a denylist of phrases or
        # a mandatory list of signature markers in the universal prompt.
        assert "Great question" not in UNIVERSAL_MINI_PROMPT
        assert "signature_phrases" not in UNIVERSAL_MINI_PROMPT
        assert "DENYLISTS FAIL" in UNIVERSAL_MINI_PROMPT


# ---------------------------------------------------------------------------
# Soul prompt — per-mini, no universal scaffolding
# ---------------------------------------------------------------------------


class TestSoulPrompt:
    def test_soul_prompt_is_per_mini(self):
        soul_a = build_soul_prompt("alice", "Alice's spirit content.")
        soul_b = build_soul_prompt("bob", "Bob's spirit content.")
        assert soul_a != soul_b
        assert "alice" in soul_a
        assert "bob" in soul_b

    def test_soul_prompt_embeds_username_in_identity(self):
        soul = build_soul_prompt("ada", "spirit body")
        assert "You ARE ada" in soul

    def test_soul_prompt_embeds_spirit_content(self):
        spirit = "Ada believes elegance beats cleverness."
        soul = build_soul_prompt("ada", spirit)
        assert spirit in soul

    def test_soul_prompt_omits_universal_abductive_loop(self):
        # Per-mini soul must not duplicate the universal abductive loop.
        soul = build_soul_prompt("ada", "spirit")
        assert "ABDUCTIVE AUTHENTICITY LOOP" not in soul

    def test_soul_prompt_omits_universal_privacy_rules(self):
        soul = build_soul_prompt("ada", "spirit")
        assert "PRIVATE evidence" not in soul

    def test_soul_prompt_omits_how_to_respond_universal_block(self):
        soul = build_soul_prompt("ada", "spirit")
        assert "HOW TO RESPOND" not in soul


# ---------------------------------------------------------------------------
# Composition — assembled prompt = universal + soul
# ---------------------------------------------------------------------------


class TestAssembledPrompt:
    def test_build_full_prepends_universal(self):
        soul = "## SOUL BODY ##"
        full = build_full_system_prompt(soul)
        assert full.startswith(UNIVERSAL_MINI_PROMPT)
        assert soul in full

    def test_build_full_handles_empty_soul(self):
        # A degraded mini (no soul yet) still receives the universal prompt
        # rather than an empty string.
        assert build_full_system_prompt(None) == UNIVERSAL_MINI_PROMPT
        assert build_full_system_prompt("") == UNIVERSAL_MINI_PROMPT
        assert build_full_system_prompt("   \n\t") == UNIVERSAL_MINI_PROMPT

    def test_legacy_build_system_prompt_emits_universal_plus_soul(self):
        # The legacy convenience wrapper is now universal + soul.
        full = build_system_prompt("ada", "Ada spirit text")
        assert UNIVERSAL_MINI_PROMPT in full
        assert "You ARE ada" in full
        assert "Ada spirit text" in full


# ---------------------------------------------------------------------------
# Runtime renderer — soul_prompt preferred over legacy system_prompt
# ---------------------------------------------------------------------------


def _make_mini(*, soul_prompt=None, system_prompt=None, spirit_content="", memory_content=""):
    mini = MagicMock()
    mini.soul_prompt = soul_prompt
    mini.system_prompt = system_prompt
    mini.spirit_content = spirit_content
    mini.memory_content = memory_content
    return mini


class TestRuntimeRendering:
    def test_renderer_uses_soul_prompt_when_available(self):
        mini = _make_mini(
            soul_prompt="## NEW SOUL CARGO ##",
            system_prompt="## STALE LEGACY BLOB ##",
        )
        rendered = render_runtime_system_prompt(mini, CHAT_PROMPT_PRESET)
        assert "NEW SOUL CARGO" in rendered
        assert UNIVERSAL_MINI_PROMPT[:80] in rendered

    def test_renderer_falls_back_to_legacy_system_prompt(self):
        mini = _make_mini(soul_prompt=None, system_prompt="## LEGACY BLOB ##")
        rendered = render_runtime_system_prompt(mini, CHAT_PROMPT_PRESET)
        assert "LEGACY BLOB" in rendered
