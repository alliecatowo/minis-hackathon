"""Agent framework built on PydanticAI.

Provides helper functions that wrap PydanticAI's Agent to yield AgentEvent
objects compatible with the frontend SSE protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

# Bridge GEMINI_API_KEY to GOOGLE_API_KEY for PydanticAI
if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from dataclasses import dataclass, field
from typing import Any

from pydantic_core import SchemaValidator
from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    TextPartDelta,
)
from pydantic_ai._function_schema import FunctionSchema
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import Model, infer_model
from pydantic_ai.tools import Tool

from pydantic_ai.settings import ModelSettings as PydanticModelSettings

from app.core.cassette import get_cassette_mode, record_response, replay_response
from app.core.compaction import create_compaction_processor
from app.core.models import ModelTier, get_model

logger = logging.getLogger(__name__)


def _default_chat_max_tokens() -> int | None:
    """Per-turn output ceiling. Default: no cap (model decides).

    Override via LLM_CHAT_MAX_TOKENS env var if you want to enforce a ceiling.
    """
    raw = os.environ.get("LLM_CHAT_MAX_TOKENS")
    if not raw:
        return None
    try:
        n = int(raw)
        return n if n > 0 else None
    except ValueError:
        return None


class LLMDisabledError(RuntimeError):
    """Raised when DISABLE_LLM_CALLS is active."""

    pass


def _check_llm_kill_switch(caller: str = "unknown") -> None:
    """Raise LLMDisabledError if the LLM kill switch is active.

    Logs the attempted invocation so operators can see traffic during outage.
    """
    from app.core.config import settings as _settings  # local import to avoid circular

    if _settings.llm_disabled:
        logger.warning(
            "llm.kill_switch blocked invocation caller=%s DISABLE_LLM_CALLS=%s",
            caller,
            _settings.disable_llm_calls,
        )
        raise LLMDisabledError(
            "LLM calls are temporarily disabled (DISABLE_LLM_CALLS). "
            "Service will resume when the flag is cleared."
        )


def _get_env_var_for_model(model: str) -> str:
    """Return the conventional provider key env var without reading or mutating it."""
    if model.startswith("google-gla:") or model.startswith("gemini:"):
        return "GOOGLE_API_KEY"
    if model.startswith("anthropic:"):
        return "ANTHROPIC_API_KEY"
    if model.startswith("openai:"):
        return "OPENAI_API_KEY"
    return "GOOGLE_API_KEY"


def _build_model_with_api_key(model: str, api_key: str | None) -> Any:
    """Return a PydanticAI model instance when a per-request API key is provided."""
    if not api_key:
        base_model: Any = model
    else:
        provider, sep, model_name = model.partition(":")
        if not sep or not model_name:
            raise ValueError(f"Invalid model string for API-key override: {model}")

        if provider in {"google-gla", "gemini"}:
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google_gla import GoogleGLAProvider

            base_model = GoogleModel(model_name, provider=GoogleGLAProvider(api_key=api_key))
        elif provider == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            base_model = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))
        elif provider == "openai":
            from pydantic_ai.models.openai import OpenAIModel
            from pydantic_ai.providers.openai import OpenAIProvider

            base_model = OpenAIModel(model_name, provider=OpenAIProvider(api_key=api_key))
        else:
            raise ValueError(f"Per-request API keys are not supported for provider '{provider}'")

    # Least-invasive intercept point: model factory output used by all Agent(...) call sites.
    if get_cassette_mode() in {"record", "replay"}:
        return _CassetteModelProxy(base_model)
    return base_model


class _CassetteModelProxy(Model):
    """Model proxy that records/replays request/response payloads via cassette fixtures."""

    def __init__(self, base_model: Model | str) -> None:
        self._base_model = base_model

    @property
    def model_name(self) -> str:
        if isinstance(self._base_model, str):
            return self._base_model
        return self._base_model.model_name

    @property
    def system(self) -> str | None:
        if isinstance(self._base_model, str):
            return None
        return self._base_model.system

    def _resolved_base_model(self) -> Model:
        if isinstance(self._base_model, str):
            self._base_model = infer_model(self._base_model)
        return self._base_model

    def _request_payload(
        self,
        messages: list[Any],
        model_settings: Any,
    ) -> dict[str, Any]:
        def _strip_volatile(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    k: _strip_volatile(v)
                    for k, v in value.items()
                    if k
                    not in {
                        "timestamp",
                        "run_id",
                        "id",
                        "tool_call_id",
                        "provider_response_id",
                    }
                }
            if isinstance(value, list):
                return [_strip_volatile(v) for v in value]
            return value

        stable_messages = _strip_volatile(
            ModelMessagesTypeAdapter.dump_python(messages, mode="json", by_alias=True)
        )
        return {
            "model_name": self.model_name,
            "system": self.system,
            "messages": stable_messages,
            "model_settings": dict(model_settings or {}),
        }

    async def request(self, messages: list[Any], model_settings: Any, model_request_parameters: Any) -> ModelResponse:
        mode = get_cassette_mode()
        request_payload = self._request_payload(messages, model_settings)

        if mode == "replay":
            replayed = replay_response(request_payload)
            restored = ModelMessagesTypeAdapter.validate_python([replayed])
            if not restored or not isinstance(restored[0], ModelResponse):
                raise RuntimeError("Cassette replay response could not be parsed as ModelResponse.")
            return restored[0]

        response = await self._resolved_base_model().request(
            messages, model_settings, model_request_parameters
        )
        if mode == "record":
            response_json = ModelMessagesTypeAdapter.dump_python([response], mode="json", by_alias=True)[0]
            record_response(request_payload, response_json)
        return response


@dataclass
class AgentTool:
    """A tool the agent can call.

    Kept for backward compatibility with callers that build tool lists
    (explorers, chat, chief synthesizer). Converted to PydanticAI
    FunctionToolset at agent run time.
    """

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
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class AgentEvent:
    """An event from the agent streaming loop.

    Types: "tool_call", "tool_result", "chunk", "done", "error"
    The frontend SSE protocol depends on these exact type strings.
    """

    type: str  # "tool_call", "tool_result", "chunk", "done", "error"
    data: str


def _build_tools(tools: list[AgentTool]) -> list[Tool]:
    """Convert AgentTool list to a list of PydanticAI Tool objects."""
    import inspect

    result = []
    for tool in tools:
        handler = tool.handler
        name = tool.name
        description = tool.description
        parameters = tool.parameters

        sig = inspect.signature(handler)
        accepted = set(sig.parameters)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

        async def _wrapper(_h=handler, _a=accepted, _v=has_var_kw, **kwargs) -> str:
            if _v:
                filtered = kwargs
            else:
                filtered = {k: v for k, v in kwargs.items() if k in _a}
            res = await _h(**filtered)
            return str(res) if res is not None else "OK"

        schema = FunctionSchema(
            function=_wrapper,
            name=name,
            description=description,
            json_schema=parameters,
            validator=SchemaValidator({"type": "any"}),
            takes_ctx=False,
            is_async=True,
        )
        t = Tool(
            _wrapper, takes_ctx=False, name=name, description=description, function_schema=schema
        )
        result.append(t)
    return result


def _build_agent(
    system_prompt: str,
    tools: list[AgentTool],
    model: str | None = None,
) -> Agent:
    """Build a PydanticAI Agent from system prompt and AgentTool list."""
    resolved_model = model or get_model(ModelTier.STANDARD)
    tool_list = _build_tools(tools)

    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent = Agent(
        resolved_model,
        instructions=system_prompt,
        tools=tool_list,
        output_type=str,
        history_processors=history_processors,
    )
    return agent


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("Ignoring invalid integer env var %s=%r", name, value)
        return None
    return parsed if parsed > 0 else None


def _build_usage_limits(
    *,
    max_turns: int,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_total_tokens: int | None = None,
):
    """Build PydanticAI usage limits with env-backed token caps."""
    from pydantic_ai.usage import UsageLimits

    return UsageLimits(
        request_limit=None,  # token budget is the enforcer, not request count
        input_tokens_limit=max_input_tokens or _env_int("LLM_REQUEST_TOKEN_LIMIT"),
        output_tokens_limit=max_output_tokens or _env_int("LLM_RESPONSE_TOKEN_LIMIT"),
        total_tokens_limit=max_total_tokens or _env_int("LLM_TOTAL_TOKEN_LIMIT"),
    )


_RETRY_429_PATTERN = re.compile(r"retry[^0-9]*(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


_LLM_MAX_CONCURRENT_REQS = _env_int("LLM_MAX_CONCURRENT_REQS") or 6
_LLM_MIN_REQUEST_GAP_MS = _env_int("LLM_MIN_REQUEST_GAP_MS") or 50
_LLM_MIN_REQUEST_GAP_SECONDS = _LLM_MIN_REQUEST_GAP_MS / 1000.0
_LLM_REQUEST_SEMAPHORE = asyncio.Semaphore(_LLM_MAX_CONCURRENT_REQS)
_LLM_REQUEST_SPACING_LOCK = asyncio.Lock()
_LLM_NEXT_REQUEST_TIME = 0.0


@asynccontextmanager
async def _llm_throttle() -> AsyncGenerator[None, None]:
    """Smooth bursty LLM traffic with concurrency and kickoff spacing limits."""
    global _LLM_NEXT_REQUEST_TIME

    await _LLM_REQUEST_SEMAPHORE.acquire()
    try:
        async with _LLM_REQUEST_SPACING_LOCK:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_seconds = _LLM_NEXT_REQUEST_TIME - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
                now = loop.time()
            _LLM_NEXT_REQUEST_TIME = now + _LLM_MIN_REQUEST_GAP_SECONDS
        yield
    finally:
        _LLM_REQUEST_SEMAPHORE.release()


async def _run_with_retry(
    agent: Agent,
    user_prompt: str,
    max_turns: int,
    max_input_tokens: int | None,
    max_output_tokens: int | None,
    max_total_tokens: int | None,
    *,
    max_retries: int = 3,
    model_settings: PydanticModelSettings | None = None,
) -> Any:
    """Run an agent with automatic retry on 429 rate-limit errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with _llm_throttle():
                return await agent.run(
                    user_prompt,
                    usage_limits=_build_usage_limits(
                        max_turns=max_turns,
                        max_input_tokens=max_input_tokens,
                        max_output_tokens=max_output_tokens,
                        max_total_tokens=max_total_tokens,
                    ),
                    model_settings=model_settings,
                )
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
                raise
            if attempt >= max_retries:
                raise
            delay = 30.0
            m = _RETRY_429_PATTERN.search(msg)
            if m:
                delay = float(m.group(1)) + 2.0
            logger.warning(
                "Agent 429 rate-limited (attempt %d/%d), retrying in %.1fs",
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


async def run_agent(
    system_prompt: str,
    user_prompt: str,
    tools: list[AgentTool] | None = None,
    history: list[dict] | None = None,
    max_turns: int = 20,
    model: str | None = None,
    api_key: str | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_total_tokens: int | None = None,
    model_settings: PydanticModelSettings | None = None,
) -> AgentResult:
    """Run an agent loop using PydanticAI.

    Wraps PydanticAI's Agent.run() to maintain the same interface as the
    old hand-rolled ReAct loop. The agent decides when it's done.

    If api_key is provided, it is passed to the provider client for this
    specific Agent instance. Global process environment is never mutated.
    """
    effective_settings: PydanticModelSettings = {}
    default_cap = _default_chat_max_tokens()
    if default_cap is not None:
        effective_settings["max_tokens"] = default_cap
    if max_output_tokens is not None:
        effective_settings["max_tokens"] = max_output_tokens
    if model_settings:
        effective_settings.update(model_settings)
    _check_llm_kill_switch(caller="run_agent")
    resolved_model = model or get_model(ModelTier.STANDARD)
    tool_outputs: dict[str, list[Any]] = {t.name: [] for t in tools}

    # Build tools with tracking wrappers
    finished = False
    finish_rejected = False
    finish_tool_name = "finish"
    tracking_tools: list[AgentTool] = []

    for tool in tools:
        _handler = tool.handler
        _name = tool.name

        async def _tracking_wrapper(_h=_handler, _n=_name, **kwargs) -> str:
            nonlocal finished, finish_rejected
            result = await _h(**kwargs)
            result_str = str(result) if result is not None else "OK"
            tool_outputs.setdefault(_n, []).append(kwargs)

            # Track finish tool behavior
            if _n == finish_tool_name:
                if result_str.startswith("NOT YET"):
                    finish_rejected = True
                else:
                    finished = True

            return result_str

        tracking_tools.append(
            AgentTool(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
                handler=_tracking_wrapper,
            )
        )

    tool_list = _build_tools(tracking_tools)
    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent = Agent(
        _build_model_with_api_key(resolved_model, api_key),
        instructions=system_prompt,
        tools=tool_list,
        output_type=str,
        history_processors=history_processors,
        retries=3,
    )

    try:
        result = await _run_with_retry(
            agent,
            user_prompt,
            max_turns,
            max_input_tokens,
            max_output_tokens,
            max_total_tokens,
            model_settings=effective_settings,  # type: ignore[arg-type]
        )
        usage = result.usage()
        return AgentResult(
            final_response=result.output,
            tool_outputs=tool_outputs,
            turns_used=usage.requests,
            tokens_in=usage.request_tokens or 0,
            tokens_out=usage.response_tokens or 0,
        )
    except Exception as e:
        logger.error("Agent run failed: %s", e)
        return AgentResult(
            final_response=None,
            tool_outputs=tool_outputs,
            turns_used=0,
        )


async def run_agent_streaming(
    system_prompt: str,
    user_prompt: str,
    tools: list[AgentTool],
    history: list[dict] | None = None,
    max_turns: int = 20,
    model: str | None = None,
    api_key: str | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    max_total_tokens: int | None = None,
    tool_choice_strategy: str = "auto_after_first",
    finish_tool_name: str | None = "finish",
) -> AsyncGenerator[AgentEvent, None]:
    """Run an agent loop with streaming output, yielding AgentEvent objects.

    Uses PydanticAI's run_stream_events() to iterate over all events
    (tool calls, tool results, text deltas) and translates them into
    AgentEvent objects that the frontend SSE protocol expects.

    If api_key is provided, it is passed to the provider client for this
    specific Agent instance. Global process environment is never mutated.
    """
    _check_llm_kill_switch(caller="run_agent_streaming")
    resolved_model = model or get_model(ModelTier.STANDARD)
    tool_outputs: dict[str, list[Any]] = {t.name: [] for t in tools}

    # Build tools with tracking wrappers
    tracking_tools: list[AgentTool] = []

    for tool in tools:
        _handler = tool.handler
        _name = tool.name

        async def _wrapper(_h=_handler, _n=_name, **kwargs) -> str:
            result = await _h(**kwargs)
            result_str = str(result) if result is not None else "OK"
            tool_outputs.setdefault(_n, []).append(kwargs)
            return result_str

        tracking_tools.append(
            AgentTool(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
                handler=_wrapper,
            )
        )

    tool_list = _build_tools(tracking_tools)

    # Build message history for multi-turn chat
    message_history = None
    if history:
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            UserPromptPart,
        )

        message_history = []
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                message_history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
            elif role == "assistant":
                message_history.append(ModelResponse(parts=[TextPart(content=content)]))

    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent = Agent(
        _build_model_with_api_key(resolved_model, api_key),
        instructions=system_prompt,
        tools=tool_list,
        output_type=str,
        history_processors=history_processors,
    )

    try:
        async for event in agent.run_stream_events(
            user_prompt,
            message_history=message_history,
            usage_limits=_build_usage_limits(
                max_turns=max_turns,
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
                max_total_tokens=max_total_tokens,
            ),
            model_settings={"max_tokens": max_output_tokens or _default_chat_max_tokens()},
        ):
            if isinstance(event, AgentRunResultEvent):
                # Final result — we already streamed the text via deltas
                pass
            elif isinstance(event, FunctionToolCallEvent):
                # Tool is being called
                try:
                    args = event.part.args
                    if isinstance(args, str):
                        args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                yield AgentEvent(
                    type="tool_call",
                    data=json.dumps({"tool": event.part.tool_name, "args": args}),
                )
            elif isinstance(event, FunctionToolResultEvent):
                # Tool returned a result
                result_content = str(event.result.content) if event.result else ""
                tool_name = event.result.tool_name if event.result else ""
                yield AgentEvent(
                    type="tool_result",
                    data=json.dumps(
                        {
                            "tool": tool_name,
                            "summary": result_content[:200],
                        }
                    ),
                )
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    yield AgentEvent(
                        type="chunk",
                        data=event.delta.content_delta,
                    )
            # PartStartEvent, FinalResultEvent, etc. are handled implicitly

    except Exception as e:
        logger.error("Streaming agent failed: %s", e)
        yield AgentEvent(type="error", data=str(e))

    yield AgentEvent(type="done", data="")
