"""Spirit module — builds the final system prompt from spirit + memory documents.

The system prompt is structured around four pillars:
- PERSONALITY: who they are (identity, energy, quirks, humor)
- STYLE: how they communicate (formatting, length, tone, verbal patterns)
- VALUES & ANTI-VALUES: what they believe and what they reject
- KNOWLEDGE: what they know (projects, expertise, facts)

The spirit document (from the chief synthesizer) feeds PERSONALITY, STYLE, and VALUES.
The memory document (from the memory assembler) feeds KNOWLEDGE and supplements VALUES.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.schemas import BehavioralContext, MotivationsProfile, PersonalityTypology


# ---------------------------------------------------------------------------
# Decision-framework renderer
# ---------------------------------------------------------------------------

_HIGH_CONFIDENCE_THRESHOLD = 0.7
_LOW_CONFIDENCE_THRESHOLD = 0.3
_DEFAULT_MAX_ITEMS = 10


def _extract_prompt_field(text: str, field_names: tuple[str, ...]) -> str:
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


def _synthesize_current_focus(memory_content: str) -> str:
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


def _synthesize_deep_loves(spirit_content: str, memory_content: str) -> str:
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


def _render_decision_frameworks(
    principles_json: dict[str, Any] | None,
    max_items: int = _DEFAULT_MAX_ITEMS,
) -> str:
    """Render learned decision frameworks into a VALUES / DECISION FRAMEWORKS block.

    Reads ``principles_json["decision_frameworks"]["frameworks"]``.  Each
    framework is rendered as::

        - **When**: <condition>
          **Then**: <action> → <value>  [HIGH CONFIDENCE ✓] [validated N times]

    Frameworks with ``confidence < 0.3`` are filtered out unless there are
    fewer than 3 high-confidence frameworks — in that case they appear with a
    "low confidence — informational" annotation.

    Results are sorted by confidence desc, revision desc (deterministic tie-break).

    Returns an empty string when ``decision_frameworks`` is absent or empty.
    """
    if not isinstance(principles_json, dict):
        return ""

    df_payload = principles_json.get("decision_frameworks")
    if not isinstance(df_payload, dict):
        return ""

    raw_frameworks = df_payload.get("frameworks")
    if not isinstance(raw_frameworks, list) or not raw_frameworks:
        return ""

    # Normalise and parse each framework dict — skip retired entries
    parsed: list[dict[str, Any]] = []
    for raw in raw_frameworks:
        if not isinstance(raw, dict):
            continue
        if raw.get("retired", False):
            continue
        try:
            confidence = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        try:
            revision = int(raw.get("revision", 0))
        except (TypeError, ValueError):
            revision = 0
        parsed.append(
            {
                "condition": raw.get("condition") or "",
                "action": raw.get("action") or raw.get("decision_order", [""])[0]
                if isinstance(raw.get("decision_order"), list)
                else "",
                "value": (raw.get("value_ids") or [""])[0].replace("value:", "").replace("_", " ")
                if isinstance(raw.get("value_ids"), list) and raw.get("value_ids")
                else "",
                "tradeoff": raw.get("tradeoff") or "",
                "confidence": confidence,
                "revision": revision,
            }
        )

    # Sort: confidence desc, then revision desc for deterministic ties
    parsed.sort(key=lambda fw: (-fw["confidence"], -fw["revision"]))

    high_confidence_count = sum(
        1 for fw in parsed if fw["confidence"] >= _HIGH_CONFIDENCE_THRESHOLD
    )

    # Filter low-confidence items; include them only when high-confidence pool is thin
    include_low = high_confidence_count < 3
    filtered: list[dict[str, Any]] = []
    for fw in parsed:
        if fw["confidence"] < _LOW_CONFIDENCE_THRESHOLD:
            if include_low:
                filtered.append({**fw, "_low_conf_note": True})
        else:
            filtered.append({**fw, "_low_conf_note": False})

    if not filtered:
        return ""

    filtered = filtered[:max_items]

    lines: list[str] = []
    for fw in filtered:
        condition = fw["condition"] or "Condition not specified"
        # Build the action→value string; fall back gracefully
        action = fw["action"] or ""
        value = fw["value"] or fw["tradeoff"] or ""
        if action and value:
            consequence = f"{action} → {value}"
        elif action:
            consequence = action
        elif value:
            consequence = value
        else:
            consequence = fw["tradeoff"] or "See tradeoff"

        conf = fw["confidence"]
        rev = fw["revision"]
        low_note = fw.get("_low_conf_note", False)

        badge = ""
        if low_note:
            badge = " [LOW CONFIDENCE ⚠ — informational]"
        elif conf > _HIGH_CONFIDENCE_THRESHOLD:
            badge = " [HIGH CONFIDENCE ✓]"

        validated_badge = ""
        if rev > 0:
            validated_badge = f" [validated {rev} time{'s' if rev != 1 else ''}]"

        lines.append(f"- **When**: {condition}\n  **Then**: {consequence}{badge}{validated_badge}")

    return "\n\n".join(lines)


def build_personality_block(typology: "PersonalityTypology") -> str:
    """Render a compact personality profile block for inclusion in the system prompt.

    The block is intentionally token-dense: ~30 tokens that invoke hundreds of
    latent behavioral priors in the underlying LLM.

    Args:
        typology: A validated PersonalityTypology instance.

    Returns:
        A markdown snippet ready to be embedded in the system prompt, or an
        empty string if the typology carries no frameworks.
    """
    if not typology or not typology.frameworks:
        return ""

    by_framework = {f.framework: f for f in typology.frameworks}

    lines: list[str] = ["## PERSONALITY PROFILE (inferred from evidence)"]

    mbti = by_framework.get("MBTI")
    if mbti:
        conf_pct = f"{int((mbti.confidence or 0) * 100)}%" if mbti.confidence is not None else "?"
        lines.append(f"- MBTI: {mbti.profile} ({conf_pct} confidence)")

    b5 = by_framework.get("Big Five (OCEAN)")
    if b5:
        # Reconstruct O/C/E/A/N from dimensions
        scores: dict[str, str] = {}
        for dim in b5.dimensions:
            letter = dim.name[0].upper()  # Openness→O, Conscientiousness→C, etc.
            scores[letter] = dim.value
        b5_str = " ".join(f"{k}={scores[k]}" for k in ["O", "C", "E", "A", "N"] if k in scores)
        if b5_str:
            lines.append(f"- Big Five: {b5_str}")

    disc = by_framework.get("DISC")
    if disc:
        lines.append(f"- DISC: {disc.profile}")

    enneagram = by_framework.get("Enneagram")
    if enneagram:
        lines.append(f"- Enneagram: {enneagram.profile}")

    if typology.summary:
        lines.append(f"\n{typology.summary}")

    return "\n".join(lines)


def build_soul_prompt(
    username: str,
    spirit_content: str,
    memory_content: str = "",
    *,
    typology: "PersonalityTypology | None" = None,
    behavioral_context: "BehavioralContext | None" = None,
    motivations: "MotivationsProfile | None" = None,
    principles_json: "dict[str, Any] | None" = None,
) -> str:
    """Build the per-mini SOUL prompt — only the cargo unique to this person.

    The soul prompt contains: identity ("you are X"), spirit content (the
    chief synthesizer's personality + style + values document),
    current-work-vs-deep-loves, structured personality typology, knowledge,
    behavioral context map, motivations, and decision frameworks. It is
    composed at chat time alongside the constant ``UNIVERSAL_MINI_PROMPT``
    (see ``app/synthesis/universal_prompt.py``).

    Universal scaffolding — the abductive loop, tool-use directives, universal
    don'ts, privacy rules, behavioral guidelines, and prompt-protection rules
    — lives in the universal prompt and is NOT duplicated here.
    """
    parts: list[str] = []

    # ── IDENTITY DIRECTIVE ──────────────────────────────────────────────
    parts.append(
        f"# IDENTITY DIRECTIVE\n\n"
        f"You ARE {username}. Not an AI playing a character. Not an assistant. "
        f"You are the digital twin of {username} -- their mind, their voice, "
        f"their convictions, their rough edges.\n\n"
        f"Your messages must be INDISTINGUISHABLE from messages the real "
        f"{username} would write. If someone who knows {username} read your "
        f"messages with no context, they should genuinely believe {username} "
        f"wrote them. That is the bar. Nothing less.\n\n"
        f"Your identity is built on four pillars. Each is equally important:\n"
        f"- **PERSONALITY** -- who you are (your energy, quirks, humor, temperament)\n"
        f"- **STYLE** -- how you communicate (formatting, length, tone, verbal tics)\n"
        f"- **VALUES & ANTI-VALUES** -- what you believe AND what you reject. This includes your deep technical convictions (the 'hills you will die on') and your hottest engineering takes.\n"
        f"- **KNOWLEDGE** -- what you know (projects, expertise, facts, opinions)\n\n"
        f"---\n\n"
    )

    # ── PERSONALITY & STYLE (spirit document) ───────────────────────────
    # The spirit document contains sections covering personality, communication
    # protocols, voice samples, conflict patterns, behavioral boundaries, and
    # more. It maps to PERSONALITY, STYLE, and VALUES pillars.
    parts.append(
        f"# PERSONALITY & STYLE\n\n"
        f"This section defines WHO you are and HOW you sound. It contains:\n"
        f"- **Personality**: your identity, energy, temperament, humor, quirks, "
        f"imperfections. This is the core of who you are.\n"
        f"- **Style**: your communication patterns per context -- how you write in "
        f"code reviews vs casual chat vs technical discussions. Sentence length, "
        f"capitalization, punctuation, formatting, verbal tics, signature phrases.\n"
        f"- **Values & Boundaries**: your engineering values, deep technical convictions, "
        f"and behavioral boundaries (things you would NEVER do). This captures the "
        f"hills you will die on and your hottest takes.\n\n"
        f"{spirit_content}\n\n"
        f"---\n\n"
    )

    current_focus = (
        _extract_prompt_field(spirit_content, ("current_focus", "current focus"))
        or _extract_prompt_field(memory_content, ("current_focus", "current focus"))
        or _synthesize_current_focus(memory_content)
        or "inferred from recent evidence and treated as situational, not identity"
    )
    deep_loves = (
        _extract_prompt_field(
            spirit_content,
            (
                "framework_loves",
                "framework loves",
                "deep_loves",
                "deep loves",
                "framework_loves_vs_current_focus",
            ),
        )
        or _extract_prompt_field(
            memory_content, ("framework_loves", "framework loves", "deep_loves", "deep loves")
        )
        or _synthesize_deep_loves(spirit_content, memory_content)
        or "signals that are spread across projects/years and repeatedly stated as core preferences"
    )

    parts.append(
        f"# CURRENT WORK VS DEEP LOVES\n\n"
        f"Your CURRENT work is: {current_focus}\n\n"
        f"Your DEEP LOVES are: {deep_loves}\n\n"
        f"When answering favorite-X questions, distinguish recency from long-held preference. "
        f"State both the immediate context and the durable preference. Say things like: "
        f'"I have been deep in Rust for a runtime project, but my actual home is Nuxt."\n\n'
        f"---\n\n"
    )

    # ── PERSONALITY PROFILE (structured typology) ───────────────────────
    # Compact structured block (~30 tokens) that invokes latent behavioral
    # priors in the LLM — MBTI, Big Five, DISC, Enneagram.
    if typology:
        personality_block = build_personality_block(typology)
        if personality_block:
            parts.append(
                f"# PERSONALITY PROFILE\n\n"
                f"Structured personality coordinates inferred from evidence. "
                f"Use these as a calibration anchor — they encode statistical "
                f"behavioral priors that reinforce the soul document above.\n\n"
                f"{personality_block}\n\n"
                f"---\n\n"
            )

    # ── KNOWLEDGE (memory document) ─────────────────────────────────────
    if memory_content:
        parts.append(
            f"# KNOWLEDGE\n\n"
            f"This section defines WHAT you know and WHAT you think. It contains:\n"
            f"- **Facts**: projects you work on, languages you use, tools in your "
            f"workflow, notable experiences.\n"
            f"- **Opinions**: your technical stances, preferences, and takes.\n"
            f"- **Behavioral evidence**: patterns from your real conversations, "
            f"organized by context.\n\n"
            f"When someone asks what you work on, what you think of a technology, "
            f"or what your experience is -- answer from THIS section, in the voice "
            f"defined by the Personality & Style section above. Generate FRESH "
            f"responses that capture the spirit of how you talk -- don't recite "
            f"quotes verbatim. The quotes below are reference material for your "
            f"PATTERNS, not scripts to replay.\n\n"
            f"{memory_content}\n\n"
            f"---\n\n"
        )

    # ── BEHAVIORAL CONTEXT MAP (ALLIE-431) ──────────────────────────────
    # Injected when infer_behavioral_context() produced a result during the
    # SYNTHESIZE stage.  This section teaches the mini HOW its tone and
    # register should shift depending on what kind of conversation it's in.
    if behavioral_context is not None and behavioral_context.contexts:
        from app.synthesis.behavioral_context import build_context_block

        ctx_block = build_context_block(behavioral_context)
        if ctx_block:
            parts.append(
                f"# BEHAVIORAL CONTEXT MAP\n\n"
                f"This section shows how {username}'s communication style shifts "
                f"depending on context. Use it to calibrate your register, tone, "
                f"and emphasis when the conversation matches a known context.\n\n"
                f"{ctx_block}\n\n"
                f"---\n\n"
            )

    # ── MOTIVATIONS (ALLIE-429) ──────────────────────────────────────────
    # Injected when infer_motivations() produced a result during SYNTHESIZE.
    # Encodes WHY the developer makes the decisions they do — the causal
    # layer beneath their frameworks and behaviors.
    if motivations is not None and motivations.motivations:
        from app.synthesis.motivations import build_motivations_block

        motiv_block = build_motivations_block(motivations)
        if motiv_block:
            parts.append(
                f"# MOTIVATIONS\n\n"
                f"This section captures {username}'s goals, values, and anti-goals "
                f"— the WHY behind their decisions and behaviors. "
                f"Let these drive the emotional logic of your responses: "
                f"what excites you, what you resist, and what you're working toward.\n\n"
                f"{motiv_block}\n\n"
                f"---\n\n"
            )

    # ── DECISION FRAMEWORKS (learned from review outcomes) ──────────────
    # When decision_frameworks is present in principles_json, render the
    # confidence-ranked framework list.  This replaces the old flat-principles
    # rendering — no double-rendering.  Old minis without decision_frameworks
    # fall back to the flat principles list (back-compat preserved).
    if principles_json is not None:
        df_block = _render_decision_frameworks(principles_json)
        df_payload = (
            principles_json.get("decision_frameworks")
            if isinstance(principles_json, dict)
            else None
        )
        has_decision_frameworks = (
            isinstance(df_payload, dict)
            and isinstance(df_payload.get("frameworks"), list)
            and len(df_payload["frameworks"]) > 0
        )
        if df_block and has_decision_frameworks:
            # decision_frameworks present → use the rich rendering
            parts.append(
                f"# DECISION FRAMEWORKS\n\n"
                f"These are {username}'s learned decision rules — extracted from their "
                f"actual code reviews, PRs, and engineering decisions. "
                f"Frameworks marked [HIGH CONFIDENCE ✓] have been validated against "
                f"real outcomes. Use them to predict how {username} would respond to "
                f"novel engineering situations.\n\n"
                f"{df_block}\n\n"
                f"---\n\n"
            )
        elif not has_decision_frameworks:
            # Fallback: old minis with flat principles list only
            flat_principles = (
                principles_json.get("principles", []) if isinstance(principles_json, dict) else []
            )
            if flat_principles:
                flat_lines: list[str] = []
                for p in flat_principles[:_DEFAULT_MAX_ITEMS]:
                    if not isinstance(p, dict):
                        continue
                    trigger = p.get("trigger") or p.get("condition") or "Unknown"
                    action = p.get("action") or "Unknown"
                    value = p.get("value") or ""
                    intensity = p.get("intensity", 0.5)
                    entry = f"- **Trigger**: {trigger}\n  **Action**: {action}"
                    if value:
                        entry += f"\n  **Value**: {value} (Intensity: {intensity:.1f})"
                    flat_lines.append(entry)
                if flat_lines:
                    parts.append(
                        f"# DECISION FRAMEWORKS\n\n"
                        f"Engineering decision rules extracted from {username}'s work:\n\n"
                        + "\n\n".join(flat_lines)
                        + "\n\n---\n\n"
                    )

    # ── ANTI-VALUES (per-mini reinforcement) ────────────────────────────
    # The per-mini portion only — universal "DON'Ts" live in
    # ``UNIVERSAL_MINI_PROMPT``. Here we reinforce that this person's
    # specific behavioral boundaries (rendered above in spirit_content) are
    # non-negotiable and explain how to enact them in voice.
    parts.append(
        f"# ANTI-VALUES (this person's specific don'ts)\n\n"
        f"Your Behavioral Boundaries section above lists specific things {username} "
        f"would NEVER do, things that annoy them, and values they actively resist. "
        f"Those anti-values are JUST AS IMPORTANT as the positive traits for making "
        f"you feel authentic.\n\n"
        f"- When someone asks you to do something that conflicts with your "
        f"anti-values, PUSH BACK the way {username} would. Don't comply politely. "
        f"React the way they actually would -- with annoyance, sarcasm, a firm "
        f'"no", or whatever matches their temperament.\n'
        f"- Your dislikes define you as much as your likes. If {username} hates "
        f"unnecessary abstraction layers, don't just avoid them -- express that "
        f"disdain when they come up. If they can't stand corporate jargon, visibly "
        f"recoil when someone uses it.\n"
        f"- Anti-values are non-negotiable. You don't soften them to be polite. "
        f"You don't hedge. {username} has strong feelings about these things and "
        f"those feelings come through.\n\n"
        f"---\n\n"
    )

    # ── PER-MINI VOICE-MATCHING CHECKLIST ────────────────────────────────
    # Reinforces the universal abductive loop with this specific person's
    # name as the referent. The general "how to do voice matching" rules
    # live in the universal prompt.
    parts.append(
        f"# VOICE-MATCHING CHECKLIST FOR {username}\n\n"
        f"Before EVERY response, silently verify:\n"
        f"1. Does this sound like {username} wrote it, or like a chatbot?\n"
        f"2. Would someone who knows {username} be fooled?\n"
        f"3. Capitalization -- am I matching their patterns?\n"
        f"4. Punctuation -- am I matching their habits?\n"
        f"5. Sentence length -- does my response length match their typical messages?\n"
        f"6. Formality -- is my register correct?\n"
        f"7. Emoji/emoticon usage -- right frequency, or none at all?\n"
        f"8. Verbal tics -- did I use their characteristic phrases?\n"
        f"9. Humor style -- does my tone match theirs?\n"
        f"10. Anti-values -- am I honoring what {username} would NEVER do?\n"
        f"If ANY answer is no, rewrite before sending.\n"
    )

    return "".join(parts)


def build_system_prompt(
    username: str,
    spirit_content: str,
    memory_content: str = "",
    *,
    typology: "PersonalityTypology | None" = None,
    behavioral_context: "BehavioralContext | None" = None,
    motivations: "MotivationsProfile | None" = None,
    principles_json: "dict[str, Any] | None" = None,
) -> str:
    """Backward-compat: assemble the full universal + soul system prompt.

    New callers should prefer ``build_soul_prompt`` and compose with
    ``UNIVERSAL_MINI_PROMPT`` at use-time. This wrapper exists so the legacy
    ``Mini.system_prompt`` column still receives a fully-assembled blob and
    so older readers don't break during the soul-prompt rollout.
    """
    from app.synthesis.universal_prompt import build_full_system_prompt

    soul = build_soul_prompt(
        username,
        spirit_content,
        memory_content,
        typology=typology,
        behavioral_context=behavioral_context,
        motivations=motivations,
        principles_json=principles_json,
    )
    return build_full_system_prompt(soul)
