"""Tests for the get_my_decision_frameworks chat tool.

Verifies:
- Tool is registered in _build_chat_tools
- Handler returns frameworks sorted by confidence desc
- badge field is set correctly (HIGH / LOW / '')
- min_confidence filter works
- limit cap works
- Graceful handling of missing/corrupt principles_json
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_principles_json(frameworks: list[dict]) -> dict:
    return {
        "principles": [],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": frameworks,
        },
    }


def _fw(
    framework_id: str = "framework:test",
    condition: str = "when X",
    decision_order: list[str] | None = None,
    value_ids: list[str] | None = None,
    confidence: float = 0.5,
    revision: int = 0,
) -> dict:
    return {
        "framework_id": framework_id,
        "condition": condition,
        "decision_order": decision_order or [condition],
        "value_ids": value_ids or ["value:correctness"],
        "confidence": confidence,
        "revision": revision,
        "tradeoff": "",
        "priority": "medium",
        "specificity_level": "case_pattern",
        "escalation_threshold": "",
        "counterexamples": [],
        "evidence_ids": [],
        "counter_evidence_ids": [],
        "evidence_provenance": [],
        "temporal_span": {},
        "motivation_ids": [],
        "approval_policy": None,
        "block_policy": None,
        "expression_policy": None,
        "exceptions": [],
        "source_type": None,
        "version": "framework-model-v1",
        "confidence_history": [],
    }


def _make_mini(principles_json: dict | None = None) -> MagicMock:
    mini = MagicMock()
    mini.id = str(uuid.uuid4())
    mini.username = "testdev"
    mini.status = "ready"
    mini.visibility = "public"
    mini.system_prompt = "You are testdev."
    mini.memory_content = None
    mini.evidence_cache = None
    mini.knowledge_graph_json = None
    mini.principles_json = principles_json
    mini.owner_id = str(uuid.uuid4())
    mini.display_name = "testdev"
    return mini


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestGetMyDecisionFrameworksToolRegistration:
    def test_tool_is_registered(self):
        from app.routes.chat import _build_chat_tools

        mini = _make_mini()
        tools = _build_chat_tools(mini)
        names = {t.name for t in tools}
        assert "get_my_decision_frameworks" in names

    def test_total_tool_count_is_eight(self):
        """Framework profile plus application tools are both registered."""
        from app.routes.chat import _build_chat_tools

        mini = _make_mini()
        tools = _build_chat_tools(mini)
        assert len(tools) == 8

    def test_schema_has_optional_params(self):
        from app.routes.chat import _build_chat_tools

        mini = _make_mini()
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")
        props = tool.parameters["properties"]
        assert "min_confidence" in props
        assert "limit" in props
        # No required fields — both params are optional
        assert tool.parameters.get("required", []) == []


# ---------------------------------------------------------------------------
# Handler behaviour
# ---------------------------------------------------------------------------


class TestGetMyDecisionFrameworksHandler:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_principles(self):
        from app.routes.chat import _build_chat_tools

        mini = _make_mini(principles_json=None)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")
        result = await tool.handler()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_frameworks_sorted_by_confidence_desc(self):
        from app.routes.chat import _build_chat_tools

        low = _fw("framework:low", confidence=0.3)
        high = _fw("framework:high", confidence=0.85)
        mid = _fw("framework:mid", confidence=0.6)
        p_json = _make_principles_json([low, high, mid])
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert isinstance(result, list)
        assert len(result) == 3
        confidences = [r["confidence"] for r in result]
        assert confidences == sorted(confidences, reverse=True)

    @pytest.mark.asyncio
    async def test_badge_high_confidence(self):
        from app.routes.chat import _build_chat_tools

        fw = _fw("framework:strong", confidence=0.85)
        p_json = _make_principles_json([fw])
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert result[0]["badge"] == "HIGH CONFIDENCE"

    @pytest.mark.asyncio
    async def test_badge_low_confidence(self):
        from app.routes.chat import _build_chat_tools

        fw = _fw("framework:weak", confidence=0.15)
        p_json = _make_principles_json([fw])
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert result[0]["badge"] == "LOW CONFIDENCE"

    @pytest.mark.asyncio
    async def test_badge_empty_for_medium_confidence(self):
        from app.routes.chat import _build_chat_tools

        fw = _fw("framework:mid", confidence=0.5)
        p_json = _make_principles_json([fw])
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert result[0]["badge"] == ""

    @pytest.mark.asyncio
    async def test_min_confidence_filter(self):
        from app.routes.chat import _build_chat_tools

        low = _fw("framework:low", confidence=0.2)
        high = _fw("framework:high", confidence=0.8)
        p_json = _make_principles_json([low, high])
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler(min_confidence=0.5)
        assert len(result) == 1
        assert result[0]["framework_id"] == "framework:high"

    @pytest.mark.asyncio
    async def test_limit_cap(self):
        from app.routes.chat import _build_chat_tools

        frameworks = [_fw(f"framework:{i}", confidence=float(i) / 20) for i in range(15)]
        p_json = _make_principles_json(frameworks)
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler(limit=5)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_wire_shape_has_required_fields(self):
        from app.routes.chat import _build_chat_tools

        fw = _fw(
            "framework:test",
            condition="when code has no tests",
            decision_order=["block until tests added"],
            value_ids=["value:reliability"],
            confidence=0.75,
            revision=2,
        )
        p_json = _make_principles_json([fw])
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert len(result) == 1
        item = result[0]
        assert item["framework_id"] == "framework:test"
        assert item["trigger"] == "when code has no tests"
        assert item["action"] == "block until tests added"
        assert item["value"] == "reliability"
        assert item["confidence"] == 0.75
        assert item["revision"] == 2
        assert item["badge"] == "HIGH CONFIDENCE"

    @pytest.mark.asyncio
    async def test_tiebreak_by_revision_desc(self):
        """When two frameworks have equal confidence, higher revision comes first."""
        from app.routes.chat import _build_chat_tools

        fw_a = _fw("framework:a", confidence=0.6, revision=1)
        fw_b = _fw("framework:b", confidence=0.6, revision=5)
        p_json = _make_principles_json([fw_a, fw_b])
        mini = _make_mini(principles_json=p_json)
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert result[0]["framework_id"] == "framework:b"
        assert result[1]["framework_id"] == "framework:a"

    @pytest.mark.asyncio
    async def test_graceful_with_json_string_principles(self):
        """principles_json stored as a JSON string (not dict) is parsed gracefully."""
        from app.routes.chat import _build_chat_tools

        p_json = _make_principles_json([_fw("framework:x", confidence=0.7)])
        mini = _make_mini(principles_json=json.dumps(p_json))
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert len(result) == 1
        assert result[0]["framework_id"] == "framework:x"

    @pytest.mark.asyncio
    async def test_graceful_with_corrupt_principles(self):
        """Corrupt / un-parseable principles_json returns empty list, not exception."""
        from app.routes.chat import _build_chat_tools

        mini = _make_mini(principles_json="not-json{{{")
        tools = _build_chat_tools(mini)
        tool = next(t for t in tools if t.name == "get_my_decision_frameworks")

        result = await tool.handler()
        assert result == []
