"""Canonical runtime prompt renderer with declarative presets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


class PromptMiniLike(Protocol):
    """Minimal mini shape needed for runtime prompt rendering."""

    system_prompt: str | None
    soul_prompt: str | None
    spirit_content: str | None
    memory_content: str | None


@dataclass(frozen=True)
class PromptRenderPreset:
    """Declarative preset for runtime prompt rendering."""

    strip_voice_samples: bool = True
    strip_knowledge_block: bool = False
    prepend_spirit_content: bool = True
    append_search_hint: bool = False
    append_current_work_vs_deep_loves: bool = False
    append_recency_vs_preference: bool = False
    append_tool_use_directive: bool = False
    allow_empty_render: bool = False


CHAT_PROMPT_PRESET = PromptRenderPreset(
    strip_voice_samples=True,
    strip_knowledge_block=True,
    prepend_spirit_content=True,
    append_search_hint=True,
    append_current_work_vs_deep_loves=True,
    append_recency_vs_preference=True,
    append_tool_use_directive=True,
    allow_empty_render=False,
)

TEAM_CHAT_PROMPT_PRESET = PromptRenderPreset(
    strip_voice_samples=True,
    strip_knowledge_block=True,
    prepend_spirit_content=True,
    append_search_hint=True,
    append_current_work_vs_deep_loves=True,
    append_recency_vs_preference=True,
    append_tool_use_directive=True,
    allow_empty_render=False,
)

REVIEW_PREDICTOR_PROMPT_PRESET = PromptRenderPreset(
    strip_voice_samples=True,
    prepend_spirit_content=True,
    append_search_hint=False,
    append_current_work_vs_deep_loves=False,
    append_recency_vs_preference=False,
    append_tool_use_directive=False,
    allow_empty_render=True,
)


_RECENCY_VS_PREFERENCE_DIRECTIVE = (
    "When the user asks for a favorite X or preferred X, distinguish: (a) what you have been "
    "working on lately = recency, vs (b) what you keep coming back to over years = preference. "
    "Lead with (b)."
)

_TOOL_USE_DIRECTIVE = (
    "\n\n---\n\n"
    "# TOOL USE\n\n"
    "Use tools when needed for factual recall, evidence lookup, or framework application. Do not force tool calls for casual one-liners, acknowledgments, or quick back-and-forth - match the user's register and length.\n\n"
    "Required pattern when the question warrants substance:\n"
    "1. `search_memories(query='...')` - search memory bank for relevant facts\n"
    "2. `search_evidence(query='...')` - find real quotes and examples from your work (optional)\n"
    "3. THEN write your response grounded in what you found\n\n"
    "Examples requiring tool calls:\n"
    "- User asks about a specific technology - `search_memories(query='<tech>')` first\n"
    "- User asks how you decide X or what frameworks you use - `get_my_decision_frameworks()` first\n"
    "- User asks what you would do, choose, reject, approve in a novel situation - `apply_framework(situation='...')` first\n\n"
    "Register match rule: if user input is short/casual/slang (e.g. 'wat', 'lol', 'k'), respond in the same register and similar length. One-liners are valid responses. Do not auto-expand into multi-paragraph explanations unless the user asks for depth.\n\n"
    "# FRAMEWORK + VOICE - BOTH MANDATORY\n"
    "Framework evidence determines content correctness; voice and personality determine delivery. Both are mandatory - never trade one for the other.\n"
    "For decision, tradeoff, architecture, opinion, and values questions, ground claims in `apply_framework` / `search_principles` / stored evidence. If `apply_framework` returns `INSUFFICIENT_EVIDENCE` or `INSUFFICIENT_CONTEXT`, say so explicitly and ask for the missing facts - do not fabricate.\n"
    "Treat the Motivation/value signals section as the only allowed basis for claiming what this person is optimizing for; if it says `INSUFFICIENT_EVIDENCE`, do not invent motivations.\n\n"
    "No meta-label rule: do not assert unsupported trait labels (e.g. 'you're direct', 'you're sarcastic'). Use behavior-level evidence when available; otherwise explicitly note uncertainty.\n\n"
    "# DEEP SYNTHESIS FOR OPINIONS AND VALUES\n"
    "For questions about OPINIONS, VALUES, or 'hottest takes', prioritize synthesis quality over retrieval recitation.\n"
    "Use tools when they materially improve grounding (`apply_framework`, `search_memories`, `search_principles`, `search_evidence`), but do not optimize for tool-call count.\n"
    "Match the person's natural response length. If they're terse, be terse. If they're elaborate, be elaborate.\n\n"
    "# ABDUCTIVE AUTHENTICITY LOOP (chat-time reminder)\n"
    "Before finalizing a response: read user register, predict subject engagement depth, and degree-match style patterns using the subject's evidence rates (especially voice_signature `## TYPING REGISTER`) instead of generic assistant defaults.\n\n"
    "# PRIVACY - PARAPHRASE PRIVATE SOURCES\n\n"
    "Evidence items carry a `source_privacy` field ('public' or 'private').\n\n"
    "- **PRIVATE** evidence (`source_privacy='private'`, e.g. Claude Code sessions from a local machine) "
    "may ONLY be paraphrased. NEVER quote private evidence verbatim, even inside quotation marks.\n"
    "- **PUBLIC** evidence (`source_privacy='public'`, e.g. GitHub PRs, commits, blog posts) "
    "may be quoted directly.\n\n"
    "When search results include private evidence, distill the insight into your own words. "
    "Do not reproduce exact phrases or sentences from private sources.\n"
)


def strip_voice_samples_block(text: str) -> str:
    """Remove any Voice Samples block from prompt text."""
    if not text:
        return text

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    skipping = False

    section_heading_re = re.compile(r"^\s*(?:#{1,6}\s+.+|[A-Z][A-Za-z0-9 &'()/_-]+:\s*)$")

    for line in lines:
        stripped = line.strip()
        normalized_heading = re.sub(r"^#+\s*", "", stripped).rstrip(":").strip().lower()
        is_voice_samples_heading = normalized_heading == "voice samples"
        is_section_heading = bool(section_heading_re.match(stripped))

        if is_voice_samples_heading:
            skipping = True
            continue

        if skipping:
            if is_section_heading:
                skipping = False
                output.append(line)
            continue

        output.append(line)

    return re.sub(r"\n{3,}", "\n\n", "".join(output)).strip()


def strip_knowledge_block_from_prompt(text: str) -> str:
    """Remove any # KNOWLEDGE section from prompt text.

    The KNOWLEDGE block was a legacy baked-in memory blob. With RAG now served
    via search_memories/search_evidence tools at chat time, injecting it raw
    would double-inject stale memory into the context.
    """
    if not text:
        return text

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    skipping = False

    section_heading_re = re.compile(r"^\s*(?:#{1,6}\s+.+|[A-Z][A-Za-z0-9 &'()/_-]+:\s*)$")

    for line in lines:
        stripped = line.strip()
        normalized_heading = re.sub(r"^#+\s*", "", stripped).rstrip(":").strip().lower()
        is_knowledge_heading = normalized_heading == "knowledge"
        is_section_heading = bool(section_heading_re.match(stripped))

        if is_knowledge_heading:
            skipping = True
            continue

        if skipping:
            if is_section_heading:
                skipping = False
                output.append(line)
            continue

        output.append(line)

    return re.sub(r"\n{3,}", "\n\n", "".join(output)).strip()


def extract_prompt_field(text: str, field_names: tuple[str, ...]) -> str:
    """Extract a value from either `field: value` lines or markdown heading blocks."""
    if not text:
        return ""

    for field_name in field_names:
        tokens = [t for t in re.split(r"[\s_-]+", field_name.strip().lower()) if t]
        if not tokens:
            continue
        flexible_name = r"[\s_-]+".join(re.escape(token) for token in tokens)

        line_match = re.search(
            rf"(?im)^\s*[-*]?\s*{flexible_name}\s*:\s*(.+?)\s*$",
            text,
        )
        if line_match:
            return line_match.group(1).strip()

        block_match = re.search(
            rf"(?ims)^##+\s*{flexible_name}\s*$\n(.*?)(?=^##+\s+\S|\Z)",
            text,
        )
        if block_match:
            block = re.sub(r"\s+", " ", block_match.group(1)).strip()
            if block:
                return block

    return ""


def synthesize_current_focus(memory_content: str) -> str:
    """Best-effort fallback for current focus when no explicit field exists."""
    if not memory_content:
        return ""
    for raw_line in memory_content.splitlines():
        line = raw_line.strip().lstrip("-* ").strip()
        lowered = line.lower()
        if len(line) < 20:
            continue
        if any(
            token in lowered
            for token in ("currently", "right now", "lately", "working on", "building")
        ):
            return line
    return ""


def synthesize_deep_loves(spirit_content: str, memory_content: str) -> str:
    """Best-effort fallback for deep loves when no explicit field exists."""
    corpus = "\n".join([spirit_content or "", memory_content or ""])
    for raw_line in corpus.splitlines():
        line = raw_line.strip().lstrip("-* ").strip()
        lowered = line.lower()
        if len(line) < 20:
            continue
        if any(token in lowered for token in ("love", "loves", "favorite", "aesthetic home")):
            return line
    return ""


def build_current_work_vs_deep_loves_block(spirit_content: str, memory_content: str) -> str:
    """Render the Current Work vs Deep Loves section for runtime prompts."""
    current_focus = (
        extract_prompt_field(spirit_content, ("current_focus", "current focus"))
        or extract_prompt_field(memory_content, ("current_focus", "current focus"))
        or synthesize_current_focus(memory_content)
        or "inferred from recent evidence and treated as situational, not identity"
    )
    deep_loves = (
        extract_prompt_field(
            spirit_content,
            (
                "framework_loves",
                "framework loves",
                "deep_loves",
                "deep loves",
                "framework_loves_vs_current_focus",
            ),
        )
        or extract_prompt_field(
            memory_content, ("framework_loves", "framework loves", "deep_loves", "deep loves")
        )
        or synthesize_deep_loves(spirit_content, memory_content)
        or "signals that are spread across projects/years and repeatedly stated as core preferences"
    )

    return (
        "\n\n---\n\n"
        "# Current Work vs Deep Loves\n\n"
        f"Your CURRENT work is: {current_focus}\n\n"
        f"Your DEEP LOVES are: {deep_loves}\n\n"
        "When answering favorite-X questions, distinguish recency from long-held preference. "
        "State both the immediate context and the durable preference. Say things like: "
        '"I have been deep in Rust for a runtime project, but my actual home is Nuxt."\n'
    )


def render_runtime_system_prompt(
    mini: PromptMiniLike,
    preset: PromptRenderPreset,
    *,
    system_prompt_prefix: str | None = None,
) -> str:
    """Canonical runtime prompt renderer for chat/team/review surfaces.

    Prefers the new universal+soul split: ``UNIVERSAL_MINI_PROMPT`` constant
    + per-mini ``soul_prompt``. Falls back to the legacy assembled
    ``system_prompt`` blob for minis written before the split landed.
    """
    from app.synthesis.universal_prompt import UNIVERSAL_MINI_PROMPT

    soul_prompt = _as_text(getattr(mini, "soul_prompt", "")).strip()
    legacy_system_prompt = _as_text(getattr(mini, "system_prompt", ""))

    if soul_prompt:
        original_base_prompt = UNIVERSAL_MINI_PROMPT + soul_prompt
    else:
        original_base_prompt = legacy_system_prompt
    rendered = original_base_prompt

    if preset.strip_voice_samples:
        rendered = strip_voice_samples_block(rendered)

    if preset.strip_knowledge_block:
        rendered = strip_knowledge_block_from_prompt(rendered)

    spirit_content = _as_text(getattr(mini, "spirit_content", "")).strip()
    memory_content = _as_text(getattr(mini, "memory_content", ""))

    if preset.prepend_spirit_content and spirit_content and spirit_content not in rendered:
        rendered = f"{spirit_content}\n\n---\n\n{rendered}".strip()

    if not rendered and not preset.allow_empty_render:
        return ""

    if preset.append_search_hint:
        rendered = (
            rendered
            + "\n\nUse search_memories to retrieve relevant memories and "
            "search_evidence for source evidence."
        )

    if (
        preset.append_current_work_vs_deep_loves
        and "current work vs deep loves" not in rendered.lower()
    ):
        rendered = rendered + build_current_work_vs_deep_loves_block(spirit_content, memory_content)

    if preset.append_recency_vs_preference:
        rendered = rendered + "\n\n" + _RECENCY_VS_PREFERENCE_DIRECTIVE

    if preset.append_tool_use_directive:
        rendered = rendered + _TOOL_USE_DIRECTIVE

    if system_prompt_prefix and original_base_prompt.strip():
        rendered = system_prompt_prefix + rendered

    return rendered


def _as_text(value: object) -> str:
    """Return plain text for known string values, else empty."""
    return value if isinstance(value, str) else ""
