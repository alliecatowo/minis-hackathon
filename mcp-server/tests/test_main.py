from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


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
                "prediction_available": True,
                "mode": "llm",
                "unavailable_reason": None,
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
        self.assertIs(result["prediction_available"], True)
        self.assertEqual(result["mode"], "llm")
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

    async def test_predict_review_gates_backend_payload_missing_availability_contract(self):
        async def fake_request_json(method, path, **kwargs):
            if (method, path) == ("GET", "/minis/by-username/torvalds"):
                return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

            return {
                "version": "review_prediction_v1",
                "reviewer_username": "torvalds",
                "private_assessment": {
                    "blocking_issues": [
                        {
                            "key": "generic-risk",
                            "summary": "Would likely ask for tests.",
                            "rationale": "fallback defaults",
                            "confidence": 0.5,
                        }
                    ],
                    "non_blocking_issues": [],
                    "open_questions": [],
                    "positive_signals": [],
                    "confidence": 0.5,
                },
                "delivery_policy": {},
                "expressed_feedback": {
                    "summary": "Would likely request changes.",
                    "comments": [],
                    "approval_state": "request_changes",
                },
            }

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.predict_review.fn("torvalds", title="Refactor auth")
        finally:
            main._request_json = original

        self.assertIs(result["prediction_available"], False)
        self.assertEqual(result["mode"], "gated")
        self.assertIn("omitted review prediction availability contract", result["unavailable_reason"])
        self.assertEqual(result["approval_state"], "uncertain")
        self.assertEqual(result["likely_blockers"], [])

    async def test_predict_review_returns_gated_summary_without_blockers(self):
        async def fake_request_json(method, path, **kwargs):
            if (method, path) == ("GET", "/minis/by-username/torvalds"):
                return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

            return {
                "version": "review_prediction_v1",
                "prediction_available": False,
                "mode": "gated",
                "unavailable_reason": "REVIEW_PREDICTOR_LLM_ENABLED is disabled",
                "reviewer_username": "torvalds",
                "private_assessment": {
                    "blocking_issues": [],
                    "non_blocking_issues": [],
                    "open_questions": [],
                    "positive_signals": [],
                    "confidence": 0.0,
                },
                "delivery_policy": {},
                "expressed_feedback": {
                    "summary": "Review prediction unavailable.",
                    "comments": [],
                    "approval_state": "uncertain",
                },
            }

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.predict_review.fn("torvalds", title="Refactor auth")
        finally:
            main._request_json = original

        self.assertIs(result["prediction_available"], False)
        self.assertEqual(result["mode"], "gated")
        self.assertEqual(
            result["unavailable_reason"],
            "REVIEW_PREDICTOR_LLM_ENABLED is disabled",
        )
        self.assertEqual(result["likely_blockers"], [])
        self.assertEqual(result["open_questions"], [])

    async def test_advise_patch_returns_framework_guidance_and_raw_artifact(self):
        async def fake_request_json(method, path, **kwargs):
            if (method, path) == ("GET", "/minis/by-username/torvalds"):
                return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

            self.assertEqual((method, path), ("POST", "/minis/5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd/patch-advisor"))
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
                "version": "patch_advisor_v1",
                "advice_available": True,
                "mode": "framework",
                "reviewer_username": "torvalds",
                "change_plan": [{"key": "change-tests", "framework_id": "fw-tests"}],
                "do_not_change": [{"key": "do-not-fw-tests"}],
                "risks": [{"key": "risk-tests"}],
                "expected_reviewer_objections": [{"key": "objection-tests"}],
                "evidence_references": [
                    {"framework_id": "fw-tests", "evidence_ids": ["ev-1"]}
                ],
                "framework_signals": [{"framework_id": "fw-tests"}],
            }

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.advise_patch.fn(
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

        self.assertTrue(result["advice_available"])
        self.assertEqual(result["mode"], "framework")
        self.assertEqual(result["change_plan"][0]["framework_id"], "fw-tests")
        self.assertEqual(result["evidence_references"][0]["evidence_ids"], ["ev-1"])
        self.assertEqual(result["advisor"]["version"], "patch_advisor_v1")

    async def test_advise_patch_returns_gated_artifact_without_generic_guidance(self):
        async def fake_request_json(method, path, **kwargs):
            if (method, path) == ("GET", "/minis/by-username/torvalds"):
                return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

            return {
                "version": "patch_advisor_v1",
                "advice_available": False,
                "mode": "gated",
                "unavailable_reason": "No decision-framework evidence is available.",
                "reviewer_username": "torvalds",
                "change_plan": [],
                "do_not_change": [],
                "risks": [],
                "expected_reviewer_objections": [],
                "evidence_references": [],
            }

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.advise_patch.fn("torvalds", title="Refactor auth")
        finally:
            main._request_json = original

        self.assertFalse(result["advice_available"])
        self.assertEqual(result["mode"], "gated")
        self.assertEqual(result["change_plan"], [])
        self.assertEqual(result["risks"], [])
        self.assertIn("No decision-framework evidence", result["unavailable_reason"])

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

    async def test_predict_review_includes_framework_id_and_revision_when_present(self):
        """framework_id and revision pass through _signal_summary when signals carry them."""

        async def fake_request_json(method, path, **kwargs):
            if (method, path) == ("GET", "/minis/by-username/torvalds"):
                return {"id": "5f3f7d6d-b362-4ce7-b9da-c1fd67dbd5bd"}

            return {
                "version": "review_prediction_v1",
                "prediction_available": True,
                "mode": "llm",
                "unavailable_reason": None,
                "reviewer_username": "torvalds",
                "private_assessment": {
                    "blocking_issues": [
                        {
                            "key": "fw-test",
                            "summary": "Tests required.",
                            "rationale": "New path untested.",
                            "confidence": 0.91,
                            "framework_id": "fw-always-test",
                            "revision": 5,
                        }
                    ],
                    "non_blocking_issues": [],
                    "open_questions": [
                        {
                            "key": "rollback",
                            "summary": "Rollback plan?",
                            "rationale": "Auth changes need rollback.",
                            "confidence": 0.6,
                            # No framework_id here — should be absent from output
                        }
                    ],
                    "positive_signals": [],
                    "confidence": 0.8,
                },
                "delivery_policy": {
                    "author_model": "unknown",
                    "context": "normal",
                    "strictness": "high",
                    "teaching_mode": False,
                    "shield_author_from_noise": False,
                    "rationale": "Peer review.",
                },
                "expressed_feedback": {
                    "summary": "Needs tests.",
                    "comments": [],
                    "approval_state": "request_changes",
                },
            }

        original = main._request_json
        main._request_json = fake_request_json
        try:
            result = await main.predict_review.fn("torvalds", title="Refactor auth")
        finally:
            main._request_json = original

        blockers = result["likely_blockers"]
        self.assertEqual(len(blockers), 1)
        blocker = blockers[0]
        self.assertEqual(blocker["framework_id"], "fw-always-test")
        self.assertEqual(blocker["revision"], 5)

        # Open question without framework_id should NOT have the key at all
        questions = result["open_questions"]
        self.assertEqual(len(questions), 1)
        self.assertNotIn("framework_id", questions[0])
        self.assertNotIn("revision", questions[0])

    async def test_predict_review_signal_without_framework_id_omits_field(self):
        """Signals without framework_id do not get a None framework_id key in output."""
        signal = {
            "key": "style",
            "summary": "Style issue.",
            "rationale": "Nit.",
            "confidence": 0.4,
        }
        result = main._signal_summary(signal)
        self.assertIsNotNone(result)
        self.assertNotIn("framework_id", result)
        self.assertNotIn("revision", result)

    def test_signal_summary_includes_framework_id_and_revision_when_set(self):
        """_signal_summary passes through framework_id and revision when present."""
        signal = {
            "key": "no-tests",
            "summary": "Tests required.",
            "rationale": "Unvetted path.",
            "confidence": 0.88,
            "framework_id": "fw-require-tests",
            "revision": 3,
        }
        result = main._signal_summary(signal)
        self.assertIsNotNone(result)
        self.assertEqual(result["framework_id"], "fw-require-tests")
        self.assertEqual(result["revision"], 3)

    async def test_advise_coding_changes_returns_gated_when_prediction_unavailable(self):
        async def fake_predict_review(identifier, **kwargs):
            return {
                "mini_id": "mini-123",
                "reviewer_username": "torvalds",
                "prediction_available": False,
                "mode": "gated",
                "unavailable_reason": "mini has no review evidence",
                "prediction": {"prediction_available": False},
            }

        original = main.predict_review.fn
        main.predict_review.fn = fake_predict_review
        try:
            result = await main.advise_coding_changes.fn("torvalds", title="Refactor auth")
        finally:
            main.predict_review.fn = original

        self.assertIs(result["guidance_available"], False)
        self.assertEqual(result["mode"], "gated")
        self.assertEqual(result["change_plan"], [])

    async def test_advise_coding_changes_derives_plan_from_review_prediction(self):
        async def fake_predict_review(identifier, **kwargs):
            return {
                "mini_id": "mini-123",
                "reviewer_username": "torvalds",
                "prediction_available": True,
                "approval_state": "request_changes",
                "summary": "Needs tests.",
                "likely_blockers": [
                    {
                        "key": "tests",
                        "summary": "Add retry tests.",
                        "rationale": "Auth retry path changed.",
                        "confidence": 0.9,
                        "framework_id": "fw-tests",
                    }
                ],
                "open_questions": [{"key": "rollback", "summary": "Rollback plan?"}],
                "delivery_policy": {"strictness": "high"},
                "prediction": {
                    "expressed_feedback": {
                        "comments": [
                            {
                                "type": "note",
                                "disposition": "comment",
                                "issue_key": "naming",
                                "summary": "Clarify the helper name.",
                                "rationale": "Name hides retry behavior.",
                            }
                        ]
                    }
                },
            }

        original = main.predict_review.fn
        main.predict_review.fn = fake_predict_review
        try:
            result = await main.advise_coding_changes.fn("torvalds", title="Refactor auth")
        finally:
            main.predict_review.fn = original

        self.assertIs(result["guidance_available"], True)
        self.assertEqual(result["mode"], "review_prediction")
        self.assertEqual(result["change_plan"][0]["priority"], "blocker")
        self.assertEqual(result["change_plan"][0]["framework_id"], "fw-tests")
        self.assertEqual(result["change_plan"][1]["priority"], "note")
        self.assertEqual(result["questions_to_answer"][0]["key"], "rollback")

    def test_auth_token_reads_file_when_env_missing(self):
        import tempfile
        import os

        original_env_token = os.environ.pop("MINIS_AUTH_TOKEN", None)
        original_env_file = os.environ.get("MINIS_AUTH_TOKEN_FILE")
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "token"
            token_file.write_text("file-token\n", encoding="utf-8")
            os.environ["MINIS_AUTH_TOKEN_FILE"] = str(token_file)
            try:
                self.assertEqual(main._auth_token(), "file-token")
            finally:
                if original_env_token is not None:
                    os.environ["MINIS_AUTH_TOKEN"] = original_env_token
                else:
                    os.environ.pop("MINIS_AUTH_TOKEN", None)
                if original_env_file is not None:
                    os.environ["MINIS_AUTH_TOKEN_FILE"] = original_env_file
                else:
                    os.environ.pop("MINIS_AUTH_TOKEN_FILE", None)


# ---------------------------------------------------------------------------
# get_decision_frameworks tests
# ---------------------------------------------------------------------------

_SAMPLE_MINI = {
    "username": "torvalds",
    "frameworks": [
        {
            "framework_id": "fw-aaa",
            "trigger": "When safety-critical code changes",
            "action": "Block until tests added",
            "value": "correctness",
            "confidence": 0.85,
            "revision": 3,
            "badge": "high",
        },
        {
            "framework_id": "fw-ccc",
            "trigger": "When perf regression detected",
            "action": "Require benchmark",
            "value": "performance",
            "confidence": 0.55,
            "revision": 2,
            "badge": None,
        },
        {
            "framework_id": "fw-bbb",
            "trigger": "When refactoring without tests",
            "action": "Request tests",
            "value": "reliability",
            "confidence": 0.20,
            "revision": 1,
            "badge": "low",
        },
    ],
    "summary": {
        "total": 3,
        "mean_confidence": round((0.85 + 0.55 + 0.20) / 3, 4),
        "max_revision": 3,
    },
}

_MINI_NO_PROFILE = {
    "username": "ghost",
    "frameworks": [],
    "summary": {"total": 0, "mean_confidence": 0.0, "max_revision": 0},
}


class GetDecisionFrameworksTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, payload, **kwargs):
        async def fake_request_json(method, path, **request_kwargs):
            self.assertEqual(method, "GET")
            self.assertTrue(path.startswith("/minis/by-username/torvalds/decision-frameworks"))
            self.assertFalse(request_kwargs)
            query = parse_qs(urlsplit(path).query)
            min_confidence = float(query.get("min_confidence", ["0.0"])[0])
            limit = int(query.get("limit", ["20"])[0])
            frameworks = [
                fw for fw in payload["frameworks"] if fw.get("confidence", 0.0) >= min_confidence
            ][:limit]
            return {
                **payload,
                "frameworks": frameworks,
                "summary": {
                    "total": len(frameworks),
                    "mean_confidence": round(
                        sum(fw["confidence"] for fw in frameworks) / len(frameworks), 4
                    )
                    if frameworks
                    else 0.0,
                    "max_revision": max((fw["revision"] for fw in frameworks), default=0),
                },
            }

        original = main._request_json
        main._request_json = fake_request_json
        try:
            return await main.get_decision_frameworks.fn("torvalds", **kwargs)
        finally:
            main._request_json = original

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
        self.assertIs(result["frameworks_available"], False)
        self.assertEqual(result["mode"], "gated")
        self.assertIn("no decision-framework evidence", result["unavailable_reason"])
        self.assertEqual(result["summary"]["total"], 0)
        self.assertEqual(result["summary"]["mean_confidence"], 0.0)

    async def test_bad_username_raises_backend_error(self):
        async def fake_request_error(method, path, **kwargs):
            raise main.BackendError("404 Mini not found")

        original = main._request_json
        main._request_json = fake_request_error
        try:
            with self.assertRaisesRegex(main.BackendError, "404"):
                await main.get_decision_frameworks.fn("nobody")
        finally:
            main._request_json = original

    async def test_username_propagated_to_output(self):
        result = await self._call(_SAMPLE_MINI)
        self.assertEqual(result["username"], "torvalds")


if __name__ == "__main__":
    unittest.main()
