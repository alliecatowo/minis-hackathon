from collections.abc import AsyncGenerator

import litellm

from app.core.config import settings

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


async def llm_completion(
    prompt: str, system: str = "", model: str | None = None, api_key: str | None = None
) -> str:
    """Single-shot LLM completion. Returns the assistant message content."""
    model = model or settings.default_llm_model
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {"model": model, "messages": messages}
    if api_key:
        kwargs["api_key"] = api_key
    response = await litellm.acompletion(**kwargs)
    return response.choices[0].message.content


async def llm_completion_json(
    prompt: str, system: str = "", model: str | None = None, api_key: str | None = None
) -> str:
    """LLM completion with JSON response format. Returns raw string (caller parses)."""
    model = model or settings.default_llm_model
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if api_key:
        kwargs["api_key"] = api_key
    response = await litellm.acompletion(**kwargs)
    return response.choices[0].message.content


async def llm_stream(
    messages: list[dict], model: str | None = None, api_key: str | None = None
) -> AsyncGenerator[str, None]:
    """Streaming LLM completion. Yields content deltas as strings."""
    model = model or settings.default_llm_model

    kwargs: dict = {"model": model, "messages": messages, "stream": True}
    if api_key:
        kwargs["api_key"] = api_key
    response = await litellm.acompletion(**kwargs)
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
