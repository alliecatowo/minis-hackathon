from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_main_module():
    module_name = "minis_mcp_main_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name]

    main_path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location(module_name, main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {main_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


main = _load_main_module()


class MinisMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_mini_resolves_username_route(self):
        async def fake_request_json(method, path, **kwargs):
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/minis/by-username/torvalds")
            self.assertFalse(kwargs)
            return {"id": "mini-123", "username": "torvalds"}

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.get_mini.fn("torvalds")
        finally:
            main._request_json = original

        self.assertEqual(result["id"], "mini-123")

    async def test_get_mini_status_resolves_username_before_streaming(self):
        async def fake_request_json(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/minis/by-username/torvalds"))
            return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

        async def fake_stream_sse_events(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/minis/5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd/status"))
            self.assertIn("timeout_seconds", kwargs)
            return [
                ("progress", '{"stage":"fetch","status":"started","message":"Started","progress":0.1}'),
                ("done", "Pipeline completed"),
            ]

        original_request = main._request_json
        original_stream = main._stream_sse_events
        main._request_json = fake_request_json
        main._stream_sse_events = fake_stream_sse_events
        try:
            result = await main.get_mini_status.fn("torvalds", timeout_seconds=15.0)
        finally:
            main._request_json = original_request
            main._stream_sse_events = original_stream

        self.assertEqual(
            result,
            [
                {
                    "event": "progress",
                    "stage": "fetch",
                    "status": "started",
                    "message": "Started",
                    "progress": 0.1,
                },
                {"event": "done", "data": "Pipeline completed"},
            ],
        )

    async def test_chat_with_mini_collects_conversation_and_chunks(self):
        async def fake_request_json(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/minis/by-username/torvalds"))
            return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

        async def fake_stream_sse_events(method, path, **kwargs):
            self.assertEqual((method, path), ("POST", "/minis/5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd/chat"))
            self.assertEqual(
                kwargs["json_body"],
                {
                    "message": "What do you think about Rust?",
                    "history": [],
                    "conversation_id": None,
                },
            )
            return [
                ("conversation_id", "conv-42"),
                ("chunk", "First "),
                ("chunk", "reply."),
            ]

        original_request = main._request_json
        original_stream = main._stream_sse_events
        main._request_json = fake_request_json
        main._stream_sse_events = fake_stream_sse_events
        try:
            result = await main.chat_with_mini.fn("torvalds", "What do you think about Rust?")
        finally:
            main._request_json = original_request
            main._stream_sse_events = original_stream

        self.assertEqual(
            result,
            {
                "mini_id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd",
                "conversation_id": "conv-42",
                "response": "First reply.",
            },
        )

    async def test_predict_review_returns_compact_summary_and_raw_prediction(self):
        async def fake_request_json(method, path, **kwargs):
            if (method, path) == ("GET", "/minis/by-username/torvalds"):
                return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

            self.assertEqual((method, path), ("POST", "/minis/5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd/review-prediction"))
            self.assertEqual(
                kwargs["json_body"],
                {
                    "repo_name": "acme/widgets",
                    "title": "Refactor auth retries",
                    "description": "Touches auth token refresh and queue retries.",
                    "diff_summary": "Adds retry logic around token refresh failures.",
                    "changed_files": ["backend/app/auth.py"],
                    "author_model": "senior_peer",
                    "delivery_context": "normal",
                },
            )
            return {
                "version": "review_prediction_v1",
                "reviewer_username": "torvalds",
                "private_assessment": {
                    "blocking_issues": [
                        {
                            "key": "tests",
                            "summary": "Add tests for the retry branch.",
                            "rationale": "The new path changes auth behavior.",
                            "confidence": 0.91,
                        }
                    ],
                    "non_blocking_issues": [],
                    "open_questions": [
                        {
                            "key": "rollback",
                            "summary": "What is the rollback plan?",
                            "rationale": "Auth failures can strand requests.",
                            "confidence": 0.67,
                        }
                    ],
                    "positive_signals": [],
                    "confidence": 0.8,
                },
                "delivery_policy": {
                    "author_model": "senior_peer",
                    "context": "normal",
                    "strictness": "high",
                    "teaching_mode": False,
                    "shield_author_from_noise": False,
                    "rationale": "Peer review.",
                },
                "expressed_feedback": {
                    "summary": "Likely asks for tests before approval.",
                    "comments": [],
                    "approval_state": "request_changes",
                },
            }

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.predict_review.fn(
                "torvalds",
                title="Refactor auth retries",
                description="Touches auth token refresh and queue retries.",
                diff_summary="Adds retry logic around token refresh failures.",
                changed_files=["backend/app/auth.py"],
                repo_name="acme/widgets",
                author_model="senior_peer",
                delivery_context="normal",
            )
        finally:
            main._request_json = original

        self.assertEqual(result["mini_id"], "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd")
        self.assertEqual(result["reviewer_username"], "torvalds")
        self.assertEqual(result["approval_state"], "request_changes")
        self.assertEqual(result["summary"], "Likely asks for tests before approval.")
        self.assertEqual(
            result["likely_blockers"],
            [
                {
                    "key": "tests",
                    "summary": "Add tests for the retry branch.",
                    "rationale": "The new path changes auth behavior.",
                    "confidence": 0.91,
                }
            ],
        )
        self.assertEqual(
            result["open_questions"],
            [
                {
                    "key": "rollback",
                    "summary": "What is the rollback plan?",
                    "rationale": "Auth failures can strand requests.",
                    "confidence": 0.67,
                }
            ],
        )
        self.assertEqual(result["prediction"]["version"], "review_prediction_v1")

    async def test_predict_review_requires_change_context(self):
        with self.assertRaisesRegex(
            main.BackendError,
            "Provide at least one of title, description, diff_summary, or changed_files.",
        ):
            await main.predict_review.fn("torvalds")

    async def test_predict_review_validates_author_model(self):
        with self.assertRaisesRegex(
            main.BackendError,
            "author_model must be one of: junior_peer, trusted_peer, senior_peer, unknown.",
        ):
            await main.predict_review.fn("torvalds", title="Refactor auth", author_model="staff")


# ---------------------------------------------------------------------------
# get_decision_frameworks tests
# ---------------------------------------------------------------------------

_SAMPLE_MINI = {
    "id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd",
    "username": "torvalds",
    "principles_json": {
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": [
                {
                    "framework_id": "fw-aaa",
                    "condition": "When safety-critical code changes",
                    "block_policy": "Block until tests added",
                    "value_ids": ["correctness"],
                    "confidence": 0.85,
                    "revision": 3,
                },
                {
                    "framework_id": "fw-bbb",
                    "condition": "When refactoring without tests",
                    "block_policy": "Request tests",
                    "value_ids": ["reliability"],
                    "confidence": 0.20,
                    "revision": 1,
                },
                {
                    "framework_id": "fw-ccc",
                    "condition": "When perf regression detected",
                    "block_policy": "Require benchmark",
                    "value_ids": ["performance"],
                    "confidence": 0.55,
                    "revision": 2,
                },
            ],
        }
    },
}

_MINI_NO_PROFILE = {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "username": "ghost",
    "principles_json": None,
}


class GetDecisionFrameworksTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, mini_payload, **kwargs):
        async def fake_fetch_mini(identifier):
            return mini_payload

        original = main._fetch_mini
        main._fetch_mini = fake_fetch_mini
        try:
            return await main.get_decision_frameworks.fn("torvalds", **kwargs)
        finally:
            main._fetch_mini = original

    async def test_frameworks_sorted_by_confidence_desc(self):
        result = await self._call(_SAMPLE_MINI)
        confidences = [fw["confidence"] for fw in result["frameworks"]]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    async def test_badges_assigned_correctly(self):
        result = await self._call(_SAMPLE_MINI)
        badges = {fw["framework_id"]: fw["badge"] for fw in result["frameworks"]}
        self.assertEqual(badges["fw-aaa"], "high")   # 0.85 > 0.7
        self.assertIsNone(badges["fw-ccc"])          # 0.55 in middle
        self.assertEqual(badges["fw-bbb"], "low")    # 0.20 < 0.3

    async def test_min_confidence_filter(self):
        result = await self._call(_SAMPLE_MINI, min_confidence=0.5)
        framework_ids = {fw["framework_id"] for fw in result["frameworks"]}
        # fw-bbb (0.20) should be filtered out
        self.assertNotIn("fw-bbb", framework_ids)
        self.assertIn("fw-aaa", framework_ids)
        self.assertIn("fw-ccc", framework_ids)

    async def test_limit(self):
        result = await self._call(_SAMPLE_MINI, limit=1)
        self.assertEqual(len(result["frameworks"]), 1)
        # Should be the highest confidence one
        self.assertEqual(result["frameworks"][0]["framework_id"], "fw-aaa")

    async def test_summary_fields(self):
        result = await self._call(_SAMPLE_MINI)
        summary = result["summary"]
        self.assertEqual(summary["total"], 3)
        self.assertAlmostEqual(summary["mean_confidence"], (0.85 + 0.55 + 0.20) / 3, places=3)
        self.assertEqual(summary["max_revision"], 3)

    async def test_empty_profile_returns_note(self):
        result = await self._call(_MINI_NO_PROFILE)
        self.assertEqual(result["frameworks"], [])
        self.assertIn("note", result)
        self.assertEqual(result["summary"]["total"], 0)
        self.assertEqual(result["summary"]["mean_confidence"], 0.0)

    async def test_bad_username_raises_backend_error(self):
        async def fake_fetch_mini_error(identifier):
            raise main.BackendError("404 Mini not found")

        original = main._fetch_mini
        main._fetch_mini = fake_fetch_mini_error
        try:
            with self.assertRaisesRegex(main.BackendError, "404"):
                await main.get_decision_frameworks.fn("nobody")
        finally:
            main._fetch_mini = original

    async def test_username_propagated_to_output(self):
        result = await self._call(_SAMPLE_MINI)
        self.assertEqual(result["username"], "torvalds")


if __name__ == "__main__":
    unittest.main()
