"""Tests for backend/app/core/agent.py — pure function tests."""

from __future__ import annotations

from app.core.agent import (
    AgentTool,
    _clean_assistant_msg,
    _is_gemini,
    _tools_to_openai_format,
)


# ── _is_gemini ───────────────────────────────────────────────────────


class TestIsGemini:
    def test_gemini_model(self):
        assert _is_gemini("gemini/gemini-2.5-flash") is True
        assert _is_gemini("gemini-1.5-pro") is True

    def test_non_gemini_model(self):
        assert _is_gemini("gpt-4o") is False
        assert _is_gemini("claude-sonnet-4-5-20250929") is False

    def test_case_insensitive(self):
        assert _is_gemini("GEMINI-2.5-FLASH") is True
        assert _is_gemini("Gemini-Pro") is True


# ── _tools_to_openai_format ──────────────────────────────────────────


class TestToolsToOpenaiFormat:
    def test_converts_single_tool(self):
        tool = AgentTool(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            handler=None,
        )
        result = _tools_to_openai_format([tool])
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "test_tool"
        assert result[0]["function"]["description"] == "A test tool"
        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_converts_multiple_tools(self):
        tools = [
            AgentTool(name=f"tool_{i}", description=f"Tool {i}", parameters={}, handler=None)
            for i in range(3)
        ]
        result = _tools_to_openai_format(tools)
        assert len(result) == 3
        names = [r["function"]["name"] for r in result]
        assert names == ["tool_0", "tool_1", "tool_2"]

    def test_empty_tools(self):
        assert _tools_to_openai_format([]) == []


# ── _clean_assistant_msg ─────────────────────────────────────────────


class TestCleanAssistantMsg:
    def test_basic_message(self):
        msg = {"role": "assistant", "content": "Hello"}
        result = _clean_assistant_msg(msg)
        assert result["role"] == "assistant"
        assert result["content"] == "Hello"

    def test_strips_provider_specific_fields(self):
        msg = {
            "role": "assistant",
            "content": "Hello",
            "provider_specific_fields": {"something": "bloated"},
        }
        result = _clean_assistant_msg(msg)
        assert "provider_specific_fields" not in result

    def test_truncates_long_tool_call_ids(self):
        long_id = "a" * 200
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": long_id,
                    "type": "function",
                    "function": {"name": "test", "arguments": "{}"},
                    "extra_field": "noise",
                }
            ],
        }
        result = _clean_assistant_msg(msg)
        assert len(result["tool_calls"][0]["id"]) == 64
        assert result["tool_calls"][0]["type"] == "function"
        assert result["tool_calls"][0]["function"]["name"] == "test"

    def test_handles_pydantic_model(self):
        """Test with an object that has model_dump (like litellm responses)."""

        class FakeMessage:
            def model_dump(self):
                return {"role": "assistant", "content": "From model"}

        result = _clean_assistant_msg(FakeMessage())
        assert result["role"] == "assistant"
        assert result["content"] == "From model"

    def test_tool_calls_none_preserves_structure(self):
        msg = {"role": "assistant", "content": "Just text", "tool_calls": None}
        result = _clean_assistant_msg(msg)
        # tool_calls is falsy so no cleaning happens
        assert result["role"] == "assistant"
