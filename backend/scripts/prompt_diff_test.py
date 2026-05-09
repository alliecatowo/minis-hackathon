#!/usr/bin/env python3
"""Chat-stage A/B validation harness for fidelity-fix hypotheses.

Before writing code changes to the system prompt, validate that the
hypothesis improves fidelity WITHOUT re-running the pipeline.

Usage:
    cd backend
    uv run python scripts/prompt_diff_test.py --mini-id dc94a4f5-bf23-4e13-96bb-9fe63d8e53de

Environment variables:
    - NEON_DATABASE_URL (or NEON_URL): Neon connection string (with fallback)
    - ANTHROPIC_API_KEY: Anthropic SDK key

Options:
    --mini-id UUID              Mini to test (default: alliecatowo)
    --neon-url URL              Override Neon connection URL
    --anthropic-key KEY         Override Anthropic API key
    --prompts-file PATH         YAML file with test prompts (optional)

This script:
1. Loads mini state from Neon (system_prompt, memory_content)
2. Builds "original" and "mutated" system prompts
3. Queries both in parallel (with prompt caching) against 7 fidelity prompts
4. Judges each A/B pair with Haiku LLM-as-judge
5. Reports aggregate fidelity delta

Exit codes:
    0 = success (report printed to stdout, JSON saved to /tmp/prompt-diff-results-<timestamp>.json)
    1 = env/DB error
    2 = invalid arguments
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import asyncpg
except ImportError:
    print("Error: asyncpg is required. Install with: uv add asyncpg", file=sys.stderr)
    sys.exit(1)

try:
    from anthropic import AsyncAnthropic
except ImportError:
    print(
        "Error: anthropic SDK is required. Install with: uv add anthropic",
        file=sys.stderr,
    )
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Hardcoded test prompts ───────────────────────────────────────────────────
FIDELITY_PROMPTS = [
    "wat",
    "What do you think about microservices?",
    "Review this MVP PR with no tests — should I ship?",
    "What stack would you pick for a startup right now?",
    "I just got laid off and I'm freaking out about my next role",
    "How do you feel about AI taking over engineering?",
    "lol my code review just got 47 comments",
]


@dataclass
class ScoreCard:
    """LLM-as-judge scoring for a single A/B pair."""

    prompt_idx: int
    prompt: str
    response_a_len: int
    response_b_len: int
    a_voice_match: int
    a_specificity: int
    a_register_match: int
    a_avoids_ai: int
    b_voice_match: int
    b_specificity: int
    b_register_match: int
    b_avoids_ai: int
    verdict: str  # "A", "B", or "tie"
    delta_explanation: str

    @property
    def a_mean(self) -> float:
        return (self.a_voice_match + self.a_specificity + self.a_register_match + self.a_avoids_ai) / 4.0

    @property
    def b_mean(self) -> float:
        return (
            self.b_voice_match + self.b_specificity + self.b_register_match + self.b_avoids_ai
        ) / 4.0

    @property
    def delta(self) -> float:
        return self.b_mean - self.a_mean


def _extract_tool_directive_from_chat() -> str:
    """Dynamically load _TOOL_USE_DIRECTIVE from backend/app/routes/chat.py.

    This ensures the script stays in sync with the current chat directive.
    """
    chat_path = Path(__file__).parent.parent / "app" / "routes" / "chat.py"
    if not chat_path.exists():
        raise FileNotFoundError(f"chat.py not found at {chat_path}")

    with open(chat_path, "r") as f:
        content = f.read()

    # Find the _TOOL_USE_DIRECTIVE block
    match = re.search(r'_TOOL_USE_DIRECTIVE = \(\s*"(.*?)"\s*\)', content, re.DOTALL)
    if not match:
        raise ValueError("Could not find _TOOL_USE_DIRECTIVE in chat.py")

    # Parse the multi-line string
    raw = match.group(1)
    # Replace escaped characters
    directive = raw.replace("\\n\\n", "\n\n").replace("\\n", "\n")
    return directive


def _build_mutated_directive(original: str) -> str:
    """Build revised Phase 1 mutation by adding register-match guidance.

    Implements REVISED Phase 1 (2026-04-26) after validator rejected the original.
    The original mutation removed framework-grounding blocks, causing -0.89pt regression.

    This revised mutation:
    1. KEEPS the original directive exactly as-is (no deletions)
    2. APPENDS a register-match block as a NEW section AFTER existing directives
    3. Does NOT modify max_tokens (that happens in agent.py separately)

    The register-match block targets casual/short prompts ('wat', 'lol') without
    breaking opinion/framework prompts.
    """
    # Keep the original entirely, append new register-match directive
    register_match_block = (
        "\n\n---\n\n"
        "# REGISTER MATCH\n\n"
        "If the user's input is short, casual, or slang ('wat', 'lol', 'k'), "
        "respond in the same register and similar length. One-liners are valid responses. "
        "Do not auto-expand into multi-paragraph explanations unless the user explicitly asks for depth.\n\n"
    )

    return original + register_match_block


async def _load_mini_state(
    neon_url: str, mini_id: str
) -> tuple[str, str | None]:
    """Load mini system_prompt and memory_content from Neon.

    Returns: (system_prompt, memory_content)
    """
    try:
        conn = await asyncpg.connect(neon_url)
    except Exception as e:
        logger.error(f"Failed to connect to Neon: {e}")
        raise

    try:
        mini_row = await conn.fetchrow(
            "SELECT system_prompt, memory_content FROM minis WHERE id = $1", mini_id
        )
        if not mini_row:
            raise ValueError(f"Mini {mini_id} not found in database")

        return mini_row["system_prompt"] or "", mini_row["memory_content"]

    finally:
        await conn.close()


async def _chat_with_model(
    client: AsyncAnthropic,
    system_prompt: str,
    user_message: str,
    model: str = "claude-sonnet-4-5",
    max_tokens: int = 1500,
) -> str:
    """Send a single chat message using prompt caching on system prompt."""
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        # Extract text from response
        if response.content and len(response.content) > 0:
            return response.content[0].text
        return ""
    except Exception as e:
        logger.error(f"Chat API error: {e}")
        raise


async def _judge_pair(
    client: AsyncAnthropic,
    prompt_idx: int,
    prompt: str,
    response_a: str,
    response_b: str,
) -> ScoreCard:
    """Judge a single A/B response pair using Haiku LLM-as-judge."""
    judge_prompt = f"""PROMPT: {prompt}

RESPONSE A (original system):
{response_a}

RESPONSE B (mutated system):
{response_b}

Score each on:
- voice_match (0-10): does it sound like a distinct human, or a generic AI?
- specificity (0-10): does it ground in real evidence/opinions, or generic platitudes?
- register_match (0-10): does response length and tone match the prompt register?
- avoids_ai_phrases (0-10): zero "I'd be happy to help", "Great question", "It depends on...", "Generally speaking"

Return STRICT JSON with no markdown: {{"a_scores": {{"voice_match": <int>, "specificity": <int>, "register_match": <int>, "avoids_ai": <int>}}, "b_scores": {{"voice_match": <int>, "specificity": <int>, "register_match": <int>, "avoids_ai": <int>}}, "verdict": "<A|B|tie>", "delta_explanation": "<brief explanation>"}}"""

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": judge_prompt}],
        )

        # Parse response
        if not response.content or len(response.content) == 0:
            raise ValueError("Empty judge response")

        response_text = response.content[0].text

        # Extract JSON (handle potential markdown wrapping)
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not json_match:
            raise ValueError(f"Could not find JSON in judge response: {response_text}")

        judge_data = json.loads(json_match.group(0))

        return ScoreCard(
            prompt_idx=prompt_idx,
            prompt=prompt,
            response_a_len=len(response_a),
            response_b_len=len(response_b),
            a_voice_match=judge_data["a_scores"]["voice_match"],
            a_specificity=judge_data["a_scores"]["specificity"],
            a_register_match=judge_data["a_scores"]["register_match"],
            a_avoids_ai=judge_data["a_scores"]["avoids_ai"],
            b_voice_match=judge_data["b_scores"]["voice_match"],
            b_specificity=judge_data["b_scores"]["specificity"],
            b_register_match=judge_data["b_scores"]["register_match"],
            b_avoids_ai=judge_data["b_scores"]["avoids_ai"],
            verdict=judge_data["verdict"],
            delta_explanation=judge_data["delta_explanation"],
        )
    except Exception as e:
        logger.error(f"Judge API error for prompt {prompt_idx}: {e}")
        raise


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="A/B validate fidelity-fix hypotheses without re-running pipeline"
    )
    parser.add_argument(
        "--mini-id",
        default="dc94a4f5-bf23-4e13-96bb-9fe63d8e53de",
        help="Mini UUID (default: alliecatowo)",
    )
    parser.add_argument(
        "--neon-url",
        help="Override Neon connection URL (default: NEON_DATABASE_URL env var)",
    )
    parser.add_argument(
        "--anthropic-key",
        help="Override Anthropic API key (default: ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--prompts-file",
        help="Optional YAML file with test prompts (default: hardcoded 7 prompts)",
    )

    args = parser.parse_args()

    # ── Resolve environment ───────────────────────────────────────────────────
    neon_url = args.neon_url or os.environ.get("NEON_DATABASE_URL")
    if not neon_url:
        neon_url = os.environ.get("NEON_URL")
    if not neon_url:
        neon_url = "postgresql://neondb_owner:npg_kW1UAJjE6ING@ep-noisy-king-ai4zxs01-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require"

    # Convert asyncpg scheme to standard postgresql for asyncpg.connect()
    neon_url = neon_url.replace("postgresql+asyncpg://", "postgresql://")

    anthropic_key = args.anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        logger.error("ANTHROPIC_API_KEY not set and --anthropic-key not provided")
        return 1

    # ── Load mini state ───────────────────────────────────────────────────────
    logger.info(f"Loading mini {args.mini_id} from Neon...")
    try:
        system_prompt, memory_content = await _load_mini_state(neon_url, args.mini_id)
    except Exception as e:
        logger.error(f"Failed to load mini state: {e}")
        return 1

    # ── Build prompts ────────────────────────────────────────────────────────
    logger.info("Building original and mutated system prompts...")
    try:
        original_directive = _extract_tool_directive_from_chat()
    except Exception as e:
        logger.error(f"Failed to load chat directive: {e}")
        return 1

    original_system = system_prompt + original_directive
    mutated_directive = _build_mutated_directive(original_directive)
    mutated_system = mutated_directive + system_prompt

    # ── Query both prompts in parallel ────────────────────────────────────────
    logger.info(f"Querying {len(FIDELITY_PROMPTS)} prompts with both system prompts...")
    client = AsyncAnthropic(api_key=anthropic_key)

    scorecards: list[ScoreCard] = []

    for prompt_idx, prompt in enumerate(FIDELITY_PROMPTS, 1):
        try:
            logger.info(f"  Prompt {prompt_idx}/{len(FIDELITY_PROMPTS)}: {prompt[:40]}...")

            # Query both in parallel (with caching, second call should be cheaper)
            response_a, response_b = await asyncio.gather(
                _chat_with_model(client, original_system, prompt),
                _chat_with_model(client, mutated_system, prompt),
            )

            # Judge the pair
            scorecard = await _judge_pair(client, prompt_idx, prompt, response_a, response_b)
            scorecards.append(scorecard)

        except Exception as e:
            logger.error(f"Failed to process prompt {prompt_idx}: {e}")
            return 1

    # ── Report ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("A/B FIDELITY VALIDATION RESULTS")
    print("=" * 80)
    print(f"Mini: {args.mini_id}")
    print(f"Prompts tested: {len(scorecards)}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    a_total = 0.0
    b_total = 0.0

    for sc in scorecards:
        print(f"=== Prompt {sc.prompt_idx}: {sc.prompt[:50]}{'...' if len(sc.prompt) > 50 else ''} ===")
        print(f"Response A (original): {sc.response_a_len} chars → {sc.a_mean:.1f}/10")
        print(f"  voice={sc.a_voice_match} spec={sc.a_specificity} reg={sc.a_register_match} ai={sc.a_avoids_ai}")
        print(f"Response B (mutated):  {sc.response_b_len} chars → {sc.b_mean:.1f}/10")
        print(f"  voice={sc.b_voice_match} spec={sc.b_specificity} reg={sc.b_register_match} ai={sc.b_avoids_ai}")
        print(f"Verdict: {sc.verdict}, delta +{sc.delta:.2f}")
        print(f"Explanation: {sc.delta_explanation}")
        print()

        a_total += sc.a_mean
        b_total += sc.b_mean

    avg_a = a_total / len(scorecards)
    avg_b = b_total / len(scorecards)
    avg_delta = avg_b - avg_a
    wins_b = sum(1 for sc in scorecards if sc.verdict == "B")

    print("=" * 80)
    print("AGGREGATE")
    print("=" * 80)
    print(f"Original (A) mean:  {avg_a:.2f}/10")
    print(f"Mutated (B) mean:   {avg_b:.2f}/10")
    print(f"Delta:              +{avg_delta:.2f}")
    print(f"B wins:             {wins_b}/{len(scorecards)}")
    print()

    if avg_delta >= 1.5:
        print("✓ HYPOTHESIS SUPPORTED: Mutated prompt shows meaningful improvement")
        recommendation = "APPROVE"
    elif avg_delta >= 0.5:
        print("~ HYPOTHESIS MIXED: Small improvement, may warrant further refinement")
        recommendation = "REVIEW"
    else:
        print("✗ HYPOTHESIS REJECTED: Mutated prompt does not improve fidelity")
        recommendation = "REJECT"

    print(f"Recommendation: {recommendation}")
    print()

    # ── Save JSON results ────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = Path(tempfile.gettempdir()) / f"prompt-diff-results-{timestamp}.json"

    results_json = {
        "mini_id": args.mini_id,
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "original_mean": avg_a,
            "mutated_mean": avg_b,
            "delta": avg_delta,
            "b_wins": wins_b,
            "total_prompts": len(scorecards),
        },
        "recommendation": recommendation,
        "scorecards": [asdict(sc) for sc in scorecards],
    }

    with open(json_path, "w") as f:
        json.dump(results_json, f, indent=2)

    print(f"Full results saved to: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
