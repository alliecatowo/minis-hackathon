"""Minimal ReAct agent loop using litellm with OpenAI function calling."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import litellm

from app.core.config import settings

logger = logging.getLogger(__name__)

# Max retries for transient Gemini empty-choices / malformed responses
_MAX_RETRIES = 3

# Gemini-specific params to disable thinking (prevents multi-turn tool call failures)
# See: https://github.com/BerriAI/litellm/issues/17949
_GEMINI_TOOL_PARAMS: dict[str, Any] = {
    "thinking": {"type": "disabled", "budget_tokens": 0},
}


def _is_gemini(model: str) -> bool:
    """Check if the model is a Gemini model."""
    return "gemini" in model.lower()


def _resolve_tool_choice(strategy: str, turn: int) -> str:
    """Resolve tool_choice value based on strategy and current turn.

    Strategies:
      - "required_until_finish": always "required" (caller exits on finish tool)
      - "required_for_n:<N>": "required" for the first N turns, then "auto"
      - "auto_after_first" (default): "required" on turn 0, "auto" after
    """
    if strategy == "required_until_finish":
        return "required"
    if strategy.startswith("required_for_n:"):
        n = int(strategy.split(":", 1)[1])
        return "required" if turn < n else "auto"
    # default: auto_after_first
    return "required" if turn == 0 else "auto"


@dataclass
class AgentTool:
    """A tool the agent can call."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Any  # async callable(kwargs) -> str


@dataclass
class AgentResult:
    """Result of an agent run."""

    final_response: str | None
    tool_outputs: dict[str, list[Any]] = field(default_factory=dict)
    turns_used: int = 0


def _tools_to_openai_format(tools: list[AgentTool]) -> list[dict]:
    """Convert AgentTools to OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _clean_assistant_msg(msg: Any) -> dict:
    """Serialize an assistant message for the conversation history.

    Strips provider-specific fields that bloat the context (e.g. Gemini
    thought signatures embedded in tool call IDs).
    """
    dumped = msg.model_dump() if hasattr(msg, "model_dump") else dict(msg)
    # Clean up tool calls — keep only standard fields
    if dumped.get("tool_calls"):
        clean_tcs = []
        for tc in dumped["tool_calls"]:
            clean_tcs.append({
                "id": tc.get("id", "")[:64],  # Truncate bloated IDs
                "type": "function",
                "function": tc.get("function", {}),
            })
        dumped["tool_calls"] = clean_tcs
    # Remove provider-specific noise
    dumped.pop("provider_specific_fields", None)
    return {"role": "assistant", **{k: v for k, v in dumped.items() if k != "role"}}


async def run_agent(
    system_prompt: str,
    user_prompt: str,
    tools: list[AgentTool],
    max_turns: int = 10,
    model: str | None = None,
    api_key: str | None = None,
    max_output_tokens: int | None = None,
    tool_choice_strategy: str = "auto_after_first",
    finish_tool_name: str | None = "finish",
) -> AgentResult:
    """Run a ReAct agent loop.

    Calls LLM with tools. If LLM returns tool_calls, executes them and appends
    results back to the conversation. If LLM returns a text response with no
    tool_calls, the agent is done. Repeats until max_turns or completion.
    """
    model = model or settings.default_llm_model
    gemini = _is_gemini(model)
    tool_handlers = {t.name: t.handler for t in tools}
    openai_tools = _tools_to_openai_format(tools)
    tool_outputs: dict[str, list[Any]] = {t.name: [] for t in tools}

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for turn in range(max_turns):
        # Retry loop for transient empty-choices / malformed responses
        msg = None
        for attempt in range(_MAX_RETRIES):
            try:
                # Build completion kwargs
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "tools": openai_tools,
                    "tool_choice": _resolve_tool_choice(tool_choice_strategy, turn),
                }
                if max_output_tokens is not None:
                    kwargs["max_tokens"] = max_output_tokens
                if api_key:
                    kwargs["api_key"] = api_key
                # Disable thinking for Gemini to prevent multi-turn failures
                if gemini:
                    kwargs.update(_GEMINI_TOOL_PARAMS)

                response = await litellm.acompletion(**kwargs)

                if not response.choices:
                    logger.warning(
                        "Empty choices on turn %d attempt %d", turn, attempt
                    )
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue

                # Handle Gemini malformed function call
                finish_reason = getattr(response.choices[0], "finish_reason", "")
                if finish_reason == "malformed_function_call":
                    logger.warning(
                        "Malformed function call on turn %d attempt %d, retrying",
                        turn,
                        attempt,
                    )
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue

                msg = response.choices[0].message
                break
            except Exception as e:
                logger.warning(
                    "Tool-calling error on turn %d attempt %d: %s", turn, attempt, e
                )
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

        if msg is None:
            # All retries exhausted — fall back to no-tools mode
            logger.warning("All retries exhausted on turn %d, falling back", turn)
            return await _fallback_no_tools(messages, model, tool_outputs, turn + 1, api_key=api_key)

        # If no tool calls, agent is done
        if not msg.tool_calls:
            return AgentResult(
                final_response=msg.content,
                tool_outputs=tool_outputs,
                turns_used=turn + 1,
            )

        # Append cleaned assistant message with tool calls
        messages.append(_clean_assistant_msg(msg))

        # Execute each tool call
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            handler = tool_handlers.get(fn_name)
            if handler is None:
                result_str = f"Error: unknown tool '{fn_name}'"
            else:
                try:
                    result = await handler(**fn_args)
                    result_str = str(result) if result is not None else "OK"
                    tool_outputs.setdefault(fn_name, []).append(fn_args)
                except Exception as e:
                    result_str = f"Error executing {fn_name}: {e}"
                    logger.warning("Tool %s failed: %s", fn_name, e)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id[:64] if tc.id else "",
                    "content": result_str,
                }
            )

        # Check if any tool call was the designated finish tool
        if finish_tool_name and any(
            tc.function.name == finish_tool_name for tc in msg.tool_calls
        ):
            return AgentResult(
                final_response=None,
                tool_outputs=tool_outputs,
                turns_used=turn + 1,
            )

    # Exhausted max turns
    return AgentResult(
        final_response=None,
        tool_outputs=tool_outputs,
        turns_used=max_turns,
    )


async def _fallback_no_tools(
    messages: list[dict],
    model: str,
    tool_outputs: dict[str, list[Any]],
    turns_used: int,
    api_key: str | None = None,
) -> AgentResult:
    """Fallback: retry without tools, asking LLM to output structured JSON."""
    fallback_messages = [m for m in messages if m.get("role") != "tool"]
    # Remove tool_calls from assistant messages
    for m in fallback_messages:
        if m.get("role") == "assistant":
            m.pop("tool_calls", None)

    fallback_messages.append(
        {
            "role": "user",
            "content": (
                "Tool calling is unavailable. Please provide your complete analysis "
                "as a JSON object with keys: personality_findings (string with detailed "
                "markdown analysis), memory_entries (list of objects each with category, "
                "topic, content, confidence as number 0-1, evidence_quote), "
                "behavioral_quotes (list of objects each with context, quote, signal_type)."
            ),
        }
    )

    for attempt in range(_MAX_RETRIES):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": fallback_messages,
                "response_format": {"type": "json_object"},
            }
            if api_key:
                kwargs["api_key"] = api_key
            # Disable thinking for Gemini in fallback too
            if _is_gemini(model):
                kwargs["thinking"] = {"type": "disabled", "budget_tokens": 0}

            response = await litellm.acompletion(**kwargs)
            if response.choices:
                content = response.choices[0].message.content
                logger.info("Fallback produced %d chars", len(content) if content else 0)
                return AgentResult(
                    final_response=content,
                    tool_outputs=tool_outputs,
                    turns_used=turns_used,
                )
            logger.warning("Fallback attempt %d returned empty choices", attempt)
            await asyncio.sleep(0.5 * (attempt + 1))
        except Exception as e:
            logger.warning("Fallback attempt %d failed: %s", attempt, e)
            await asyncio.sleep(0.5 * (attempt + 1))

    logger.error("All fallback attempts failed")
    return AgentResult(
        final_response=None,
        tool_outputs=tool_outputs,
        turns_used=turns_used,
    )


@dataclass
class AgentEvent:
    """An event from the agent streaming loop."""
    type: str  # "tool_call", "tool_result", "chunk", "done", "error"
    data: str


async def run_agent_streaming(
    system_prompt: str,
    user_prompt: str,
    tools: list[AgentTool],
    history: list[dict] | None = None,
    max_turns: int = 5,
    model: str | None = None,
    api_key: str | None = None,
    max_output_tokens: int | None = None,
    tool_choice_strategy: str = "auto_after_first",
    finish_tool_name: str | None = "finish",
) -> AsyncGenerator[AgentEvent, None]:
    """Run a ReAct agent loop with streaming output.

    For tool-calling turns: non-streaming completion, yield tool_call/tool_result events.
    For the final turn (no tool_calls): streaming completion, yield chunk events.
    Accepts history for multi-turn chat context.
    """
    model = model or settings.default_llm_model
    gemini = _is_gemini(model)
    tool_handlers = {t.name: t.handler for t in tools}
    openai_tools = _tools_to_openai_format(tools)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Add conversation history if provided
    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": user_prompt})

    for turn in range(max_turns):
        msg = None
        for attempt in range(_MAX_RETRIES):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "tools": openai_tools,
                    "tool_choice": _resolve_tool_choice(tool_choice_strategy, turn),
                }
                if max_output_tokens is not None:
                    kwargs["max_tokens"] = max_output_tokens
                if api_key:
                    kwargs["api_key"] = api_key
                if gemini:
                    kwargs.update(_GEMINI_TOOL_PARAMS)

                response = await litellm.acompletion(**kwargs)

                if not response.choices:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue

                finish_reason = getattr(response.choices[0], "finish_reason", "")
                if finish_reason == "malformed_function_call":
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue

                msg = response.choices[0].message
                break
            except Exception as e:
                logger.warning("Streaming agent error turn %d attempt %d: %s", turn, attempt, e)
                await asyncio.sleep(0.5 * (attempt + 1))

        if msg is None:
            yield AgentEvent(type="error", data="Agent failed after retries")
            return

        # If no tool calls, this is the final turn — stream it
        if not msg.tool_calls:
            # Re-do this turn with streaming
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                }
                if api_key:
                    kwargs["api_key"] = api_key
                if gemini:
                    kwargs["thinking"] = {"type": "disabled", "budget_tokens": 0}

                stream_response = await litellm.acompletion(**kwargs)
                async for chunk in stream_response:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield AgentEvent(type="chunk", data=delta.content)
            except Exception as e:
                # Fall back to the non-streamed content
                if msg.content:
                    yield AgentEvent(type="chunk", data=msg.content)
                else:
                    yield AgentEvent(type="error", data=str(e))

            yield AgentEvent(type="done", data="")
            return

        # Tool-calling turn — execute tools
        messages.append(_clean_assistant_msg(msg))

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            yield AgentEvent(
                type="tool_call",
                data=json.dumps({"tool": fn_name, "args": fn_args}),
            )

            handler = tool_handlers.get(fn_name)
            if handler is None:
                result_str = f"Error: unknown tool '{fn_name}'"
            else:
                try:
                    result = await handler(**fn_args)
                    result_str = str(result) if result is not None else "OK"
                except Exception as e:
                    result_str = f"Error executing {fn_name}: {e}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id[:64] if tc.id else "",
                "content": result_str,
            })

            yield AgentEvent(
                type="tool_result",
                data=json.dumps({"tool": fn_name, "summary": result_str[:200]}),
            )

        # Check if any tool call was the designated finish tool
        if finish_tool_name and any(
            tc.function.name == finish_tool_name for tc in msg.tool_calls
        ):
            yield AgentEvent(type="done", data="")
            return

    # Max turns exhausted — force a final streaming response without tools
    # Strip tool/tool_calls since we're not passing tool definitions
    fallback_messages = [
        {k: v for k, v in m.items() if k != "tool_calls"} if m.get("role") == "assistant" else m
        for m in messages
        if m.get("role") != "tool"
    ]
    fallback_messages.append({
        "role": "user",
        "content": "Please provide your response now based on everything you've learned.",
    })
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": fallback_messages,
            "stream": True,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if gemini:
            kwargs["thinking"] = {"type": "disabled", "budget_tokens": 0}

        stream_response = await litellm.acompletion(**kwargs)
        async for chunk in stream_response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield AgentEvent(type="chunk", data=delta.content)
    except Exception as e:
        logger.warning("Final streaming fallback failed: %s", e)
        yield AgentEvent(type="error", data=str(e))

    yield AgentEvent(type="done", data="")
