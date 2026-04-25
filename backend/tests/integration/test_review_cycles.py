"""Integration tests for durable review-cycle persistence."""

from __future__ import annotations

import json
import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.evidence import ExplorerFinding, ExplorerQuote, ReviewCycle
from app.models.schemas import (
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
    StructuredReviewState,
)
from app.review_cycles import finalize_review_cycle, upsert_review_cycle_prediction
from app.synthesis.pipeline import _build_synthetic_reports_from_db

_CREATE_MINIS = """
CREATE TABLE IF NOT EXISTS minis (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    principles_json JSON,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_REVIEW_CYCLES = """
CREATE TABLE IF NOT EXISTS review_cycles (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'github',
    external_id TEXT NOT NULL,
    metadata_json JSON,
    predicted_state_json JSON NOT NULL,
    human_review_outcome_json JSON,
    delta_metrics_json JSON,
    predicted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    human_reviewed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_review_cycles_mini_source_external_id UNIQUE (mini_id, source_type, external_id)
)
"""

_CREATE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    item_type TEXT NOT NULL,
    content TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT 'general',
    metadata_json JSON,
    source_privacy TEXT NOT NULL DEFAULT 'public',
    retention_policy TEXT,
    retention_expires_at TEXT,
    source_authorization TEXT,
    authorization_revoked_at TEXT,
    access_classification TEXT,
    lifecycle_audit_json TEXT,
    explored BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    external_id TEXT,
    last_fetched_at TEXT,
    content_hash TEXT,
    ai_contamination_score FLOAT,
    ai_contamination_confidence FLOAT,
    ai_contamination_status TEXT,
    ai_contamination_reasoning TEXT,
    ai_contamination_provenance_json TEXT,
    ai_contamination_checked_at TEXT
)
"""

_CREATE_EXPLORER_FINDINGS = """
CREATE TABLE IF NOT EXISTS explorer_findings (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_EXPLORER_QUOTES = """
CREATE TABLE IF NOT EXISTS explorer_quotes (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    quote TEXT NOT NULL,
    context TEXT,
    significance TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def _issue_comment(
    issue_key: str,
    *,
    comment_type: str,
    disposition: str,
    summary: str,
    rationale: str | None = None,
) -> dict[str, str]:
    return {
        "type": comment_type,
        "disposition": disposition,
        "issue_key": issue_key,
        "summary": summary,
        "rationale": rationale or f"Tracks {issue_key}.",
    }


def _review_state(
    summary: str,
    approval_state: str,
    *,
    blocking_issue_keys: list[str] | None = None,
    comments: list[dict] | None = None,
    outcome_capture: dict | None = None,
) -> StructuredReviewState:
    payload = {
        "private_assessment": {
            "blocking_issues": [
                {
                    "key": issue_key,
                    "summary": f"Predicted concern for {issue_key}.",
                    "rationale": f"Reason about {issue_key}.",
                }
                for issue_key in (blocking_issue_keys or [])
            ],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.8,
        },
        "delivery_policy": {
            "author_model": "trusted_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": True,
            "shield_author_from_noise": True,
        },
        "expressed_feedback": {
            "summary": summary,
            "comments": comments or [],
            "approval_state": approval_state,
        },
    }
    if outcome_capture is not None:
        payload["outcome_capture"] = outcome_capture
    return StructuredReviewState.model_validate(payload)


@pytest.fixture(scope="module")
def engine():
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest_asyncio.fixture(scope="module")
async def tables(engine):
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_MINIS))
        await conn.execute(text(_CREATE_REVIEW_CYCLES))
        await conn.execute(text(_CREATE_EVIDENCE))
        await conn.execute(text(_CREATE_EXPLORER_FINDINGS))
        await conn.execute(text(_CREATE_EXPLORER_QUOTES))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS explorer_quotes"))
        await conn.execute(text("DROP TABLE IF EXISTS explorer_findings"))
        await conn.execute(text("DROP TABLE IF EXISTS evidence"))
        await conn.execute(text("DROP TABLE IF EXISTS review_cycles"))
        await conn.execute(text("DROP TABLE IF EXISTS minis"))
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine, tables):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        mini_id = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO minis (id, username, status) VALUES (:id, :username, 'ready')"
            ),
            {"id": mini_id, "username": f"user-{mini_id[:8]}"},
        )
        await s.commit()
        yield s, mini_id
        await s.execute(text("DELETE FROM explorer_quotes"))
        await s.execute(text("DELETE FROM explorer_findings"))
        await s.execute(text("DELETE FROM evidence"))
        await s.execute(text("DELETE FROM review_cycles"))
        await s.execute(text("DELETE FROM minis"))
        await s.commit()


class TestReviewCyclePersistence:
    @pytest.mark.asyncio
    async def test_upsert_then_finalize_updates_single_row(self, session):
        db, mini_id = session
        external_id = "acme/widgets#123:allie:deadbeef"

        created = await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 123},
                predicted_state=_review_state(
                    "Please add tests.",
                    "request_changes",
                    blocking_issue_keys=["missing-tests"],
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="blocker",
                            disposition="request_changes",
                            summary="Please add tests.",
                        )
                    ],
                ),
            ),
        )

        assert created.external_id == external_id
        assert created.human_review_outcome is None
        assert created.delta_metrics is None

        finalized = await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state(
                    "Nit only, otherwise fine.",
                    "comment",
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="note",
                            disposition="comment",
                            summary="Tests can land in a quick follow-up.",
                        )
                    ],
                    outcome_capture={
                        "artifact_outcome": "revised",
                        "final_disposition": "commented",
                        "reviewer_summary": "Nit only, otherwise fine.",
                        "suggestion_outcomes": [
                            {
                                "suggestion_key": "missing-tests",
                                "outcome": "deferred",
                                "summary": "Tests can land in a quick follow-up.",
                            }
                        ],
                    },
                ),
                delta_metrics={
                    "github_review_state": "COMMENTED",
                    "github_review_id": 987,
                },
            ),
        )

        assert finalized is not None
        assert finalized.id == created.id
        assert finalized.human_review_outcome["expressed_feedback"]["approval_state"] == "comment"
        assert finalized.human_review_outcome["outcome_capture"]["artifact_outcome"] == "revised"
        assert finalized.delta_metrics["approval_state_changed"] is True
        assert finalized.delta_metrics["predicted_approval_state"] == "request_changes"
        assert finalized.delta_metrics["actual_approval_state"] == "comment"
        assert finalized.delta_metrics["github_review_id"] == 987
        assert finalized.delta_metrics["artifact_outcome"] == "revised"
        assert finalized.delta_metrics["final_disposition"] == "commented"
        assert finalized.delta_metrics["reviewer_summary"] == "Nit only, otherwise fine."
        assert finalized.delta_metrics["suggestion_outcomes"] == [
            {
                "suggestion_key": "missing-tests",
                "outcome": "deferred",
                "summary": "Tests can land in a quick follow-up.",
            }
        ]
        assert finalized.delta_metrics["suggestion_outcome_counts"] == {"deferred": 1}
        assert finalized.delta_metrics["terminal_resolution"] == "downgraded"
        assert finalized.delta_metrics["issue_outcomes"] == [
            {
                "issue_key": "missing-tests",
                "outcome": "downgraded",
                "predicted_type": "blocker",
                "predicted_disposition": "request_changes",
                "predicted_summary": "Please add tests.",
                "actual_type": "note",
                "actual_disposition": "comment",
                "actual_summary": "Tests can land in a quick follow-up.",
            }
        ]
        assert finalized.delta_metrics["predicted_issue_count"] == 1
        assert finalized.delta_metrics["matched_issue_count"] == 1
        assert finalized.delta_metrics["actual_issue_count"] == 1
        assert finalized.human_reviewed_at is not None

        count_result = await db.execute(select(func.count()).select_from(ReviewCycle))
        assert count_result.scalar_one() == 1

        stored_result = await db.execute(
            select(ReviewCycle).where(
                ReviewCycle.mini_id == mini_id,
                ReviewCycle.source_type == "github",
                ReviewCycle.external_id == external_id,
            )
        )
        stored = stored_result.scalar_one()
        assert stored.predicted_state["expressed_feedback"]["approval_state"] == "request_changes"
        assert stored.human_review_outcome["expressed_feedback"]["summary"] == "Nit only, otherwise fine."
        assert stored.human_review_outcome["outcome_capture"]["final_disposition"] == "commented"

    @pytest.mark.asyncio
    async def test_finalize_writes_review_learning_back_into_synthesis_inputs(self, session):
        db, mini_id = session
        external_id = "acme/widgets#456:allie:feedface"

        await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 456},
                predicted_state=_review_state(
                    "Block on test gap.",
                    "request_changes",
                    blocking_issue_keys=["missing-tests"],
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="blocker",
                            disposition="request_changes",
                            summary="Block on test gap.",
                        )
                    ],
                ),
            ),
        )

        await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state(
                    "Nit only, otherwise fine.",
                    "comment",
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="note",
                            disposition="comment",
                            summary="Coverage can follow after merge.",
                        )
                    ],
                ),
                delta_metrics={},
            ),
        )

        findings_result = await db.execute(
            select(ExplorerFinding).where(
                ExplorerFinding.mini_id == mini_id,
                ExplorerFinding.source_type == "review_writeback",
            )
        )
        findings = findings_result.scalars().all()
        assert len(findings) == 1
        assert findings[0].category == "decision_patterns"
        assert "predicted approval_state=request_changes" in findings[0].content
        assert "actual approval_state=comment" in findings[0].content
        assert "approval_state_changed=yes" in findings[0].content
        assert "terminal_resolution=downgraded" in findings[0].content
        assert "issue_outcomes=missing-tests=downgraded" in findings[0].content
        assert "Nit only, otherwise fine." in findings[0].content

        quotes_result = await db.execute(
            select(ExplorerQuote).where(
                ExplorerQuote.mini_id == mini_id,
                ExplorerQuote.source_type == "review_writeback",
            )
        )
        quotes = quotes_result.scalars().all()
        assert len(quotes) == 1
        assert quotes[0].quote == "Nit only, otherwise fine."
        assert quotes[0].significance == "review_outcome"

        async_session = sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
        reports = await _build_synthetic_reports_from_db(mini_id, async_session)
        review_reports = [report for report in reports if report.source_name == "review_writeback"]
        assert len(review_reports) == 1
        assert "actual approval_state=comment" in review_reports[0].personality_findings
        assert any(
            quote["quote"] == "Nit only, otherwise fine."
            for quote in review_reports[0].behavioral_quotes
        )

    @pytest.mark.asyncio
    async def test_finalize_writes_outcome_capture_into_writeback_learning(self, session):
        db, mini_id = session
        external_id = "acme/widgets#456:allie:outcomes"

        await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 458},
                predicted_state=_review_state(
                    "Looks ready to merge.",
                    "approve",
                    comments=[
                        _issue_comment(
                            "add-appendix",
                            comment_type="note",
                            disposition="comment",
                            summary="Appendix would help future readers.",
                        )
                    ],
                ),
            ),
        )

        await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state(
                    "",
                    "comment",
                    outcome_capture={
                        "artifact_outcome": "accepted",
                        "final_disposition": "approved_with_followups",
                        "reviewer_summary": "Approved with a docs follow-up after landing.",
                        "suggestion_outcomes": [
                            {
                                "suggestion_key": "add-appendix",
                                "outcome": "deferred",
                                "summary": "Appendix can ship after merge.",
                            }
                        ],
                    },
                ),
                delta_metrics={},
            ),
        )

        findings_result = await db.execute(
            select(ExplorerFinding).where(
                ExplorerFinding.mini_id == mini_id,
                ExplorerFinding.source_type == "review_writeback",
            )
        )
        findings = findings_result.scalars().all()
        assert len(findings) == 1
        assert "artifact_outcome=accepted" in findings[0].content
        assert "final_disposition=approved_with_followups" in findings[0].content
        assert "suggestion_outcomes=add-appendix=deferred" in findings[0].content
        assert "Approved with a docs follow-up after landing." in findings[0].content

        quotes_result = await db.execute(
            select(ExplorerQuote).where(
                ExplorerQuote.mini_id == mini_id,
                ExplorerQuote.source_type == "review_writeback",
            )
        )
        quotes = quotes_result.scalars().all()
        assert len(quotes) == 1
        assert quotes[0].quote == "Approved with a docs follow-up after landing."

    @pytest.mark.asyncio
    async def test_finalize_marks_issue_resolved_before_submit_when_review_approves(self, session):
        db, mini_id = session
        external_id = "acme/widgets#457:allie:facefeed"

        await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 457},
                predicted_state=_review_state(
                    "Please add tests before merge.",
                    "request_changes",
                    blocking_issue_keys=["missing-tests"],
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="blocker",
                            disposition="request_changes",
                            summary="Please add tests before merge.",
                        )
                    ],
                ),
            ),
        )

        finalized = await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state("Looks good now.", "approve"),
                delta_metrics={},
            ),
        )

        assert finalized is not None
        assert finalized.delta_metrics["terminal_resolution"] == "resolved_before_submit"
        assert finalized.delta_metrics["issue_outcomes"] == [
            {
                "issue_key": "missing-tests",
                "outcome": "resolved_before_submit",
                "predicted_type": "blocker",
                "predicted_disposition": "request_changes",
                "predicted_summary": "Please add tests before merge.",
                "actual_type": None,
                "actual_disposition": None,
                "actual_summary": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_finalize_replaces_prior_writeback_for_same_cycle(self, session):
        db, mini_id = session
        external_id = "acme/widgets#789:allie:cafebabe"

        await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 789},
                predicted_state=_review_state(
                    "Still blocked on tests.",
                    "request_changes",
                    blocking_issue_keys=["missing-tests"],
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="blocker",
                            disposition="request_changes",
                            summary="Still blocked on tests.",
                        )
                    ],
                ),
            ),
        )

        await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state(
                    "Need coverage before merge.",
                    "request_changes",
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="blocker",
                            disposition="request_changes",
                            summary="Need coverage before merge.",
                        )
                    ],
                ),
                delta_metrics={},
            ),
        )

        await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state(
                    "Actually fine with a follow-up test.",
                    "comment",
                ),
                delta_metrics={},
            ),
        )

        findings_result = await db.execute(
            select(ExplorerFinding).where(
                ExplorerFinding.mini_id == mini_id,
                ExplorerFinding.source_type == "review_writeback",
            )
        )
        findings = findings_result.scalars().all()
        assert len(findings) == 1
        assert "actual approval_state=comment" in findings[0].content
        assert "terminal_resolution=not_raised" in findings[0].content
        assert "Actually fine with a follow-up test." in findings[0].content

        quotes_result = await db.execute(
            select(ExplorerQuote).where(
                ExplorerQuote.mini_id == mini_id,
                ExplorerQuote.source_type == "review_writeback",
            )
        )
        quotes = quotes_result.scalars().all()
        assert len(quotes) == 1
        assert quotes[0].quote == "Actually fine with a follow-up test."


def _make_principles_json(frameworks: list[dict]) -> str:
    return json.dumps(
        {
            "decision_frameworks": {
                "version": "decision_frameworks_v1",
                "frameworks": frameworks,
                "source": "principles_motivations_normalizer",
            }
        }
    )


def _fw(
    framework_id: str,
    condition: str,
    confidence: float,
    evidence_ids: list[str] | None = None,
) -> dict:
    return {
        "framework_id": framework_id,
        "condition": condition,
        "priority": "medium",
        "tradeoff": "t",
        "escalation_threshold": "e",
        "confidence": confidence,
        "specificity_level": "case_pattern",
        "evidence_ids": evidence_ids or [],
        "version": "framework-model-v1",
        "revision": 0,
        "confidence_history": [],
    }


@pytest_asyncio.fixture
async def session_with_frameworks(engine, tables):
    """Session with a mini pre-populated with a matching decision framework."""
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        mini_id = str(uuid.uuid4())
        principles = _make_principles_json(
            [
                _fw(
                    "fw:missing-tests",
                    "missing tests before merge",
                    confidence=0.60,
                    evidence_ids=["e1", "e2", "e3", "e4", "e5"],
                ),
            ]
        )
        await s.execute(
            text(
                "INSERT INTO minis (id, username, status, principles_json)"
                " VALUES (:id, :u, 'ready', :pj)"
            ),
            {"id": mini_id, "u": f"fw-{mini_id[:8]}", "pj": principles},
        )
        await s.commit()
        yield s, mini_id
        await s.execute(text("DELETE FROM explorer_quotes"))
        await s.execute(text("DELETE FROM explorer_findings"))
        await s.execute(text("DELETE FROM review_cycles"))
        await s.execute(text("DELETE FROM minis"))
        await s.commit()


class TestFrameworkDriftAlertLogging:
    """Verify that framework_drift_alert log lines are emitted on band-change/large shifts."""

    @pytest.mark.asyncio
    async def test_band_change_emits_drift_alert_log(self, caplog, engine, tables):
        """A confirmed outcome that pushes confidence from neutral (0.65) into high (0.70) emits a drift alert."""
        # Build a fresh mini with confidence=0.65 (neutral).
        # One "confirmed" finalize → +0.05 → 0.70 → crosses HIGH boundary → band_change log.
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as db:
            mini_id = str(uuid.uuid4())
            principles = _make_principles_json(
                [_fw("fw:missing-tests", "missing tests before merge", confidence=0.65, evidence_ids=["e1", "e2", "e3", "e4", "e5"])]
            )
            await db.execute(
                text("INSERT INTO minis (id, username, status, principles_json) VALUES (:id, :u, 'ready', :pj)"),
                {"id": mini_id, "u": f"dft-{mini_id[:8]}", "pj": principles},
            )
            await db.commit()

            external_id = f"pr:band-change-{uuid.uuid4().hex[:8]}"
            await upsert_review_cycle_prediction(
                db,
                mini_id,
                ReviewCyclePredictionUpsertRequest(
                    external_id=external_id,
                    source_type="github",
                    metadata_json={"repo_full_name": "acme/widgets", "pr_number": 99},
                    predicted_state=_review_state(
                        "Add tests.",
                        "request_changes",
                        blocking_issue_keys=["missing-tests"],
                        comments=[
                            _issue_comment(
                                "missing-tests",
                                comment_type="blocker",
                                disposition="request_changes",
                                summary="Add tests.",
                            )
                        ],
                    ),
                ),
            )

            with caplog.at_level(logging.INFO, logger="app.review_cycles"):
                # 0.65 → 0.70: neutral → high (band change triggers alert)
                await finalize_review_cycle(
                    db,
                    mini_id,
                    ReviewCycleOutcomeUpdateRequest(
                        external_id=external_id,
                        source_type="github",
                        human_review_outcome=_review_state(
                            "Correct call.",
                            "request_changes",
                            comments=[
                                _issue_comment(
                                    "missing-tests",
                                    comment_type="blocker",
                                    disposition="request_changes",
                                    summary="Tests still needed.",
                                )
                            ],
                        ),
                        delta_metrics={},
                    ),
                )

            await db.execute(text("DELETE FROM explorer_quotes"))
            await db.execute(text("DELETE FROM explorer_findings"))
            await db.execute(text("DELETE FROM review_cycles"))
            await db.execute(text("DELETE FROM minis WHERE id = :id"), {"id": mini_id})
            await db.commit()

        drift_records = [
            r for r in caplog.records if r.getMessage() == "framework_drift_alert"
        ]
        assert len(drift_records) >= 1
        rec = drift_records[0]
        assert rec.mini_id == str(mini_id)
        assert rec.framework_id == "fw:missing-tests"
        assert rec.source == "review_writeback"
        assert rec.band_change is not None
        assert "neutral" in rec.band_change
        assert "high" in rec.band_change

    @pytest.mark.asyncio
    async def test_sub_threshold_shift_emits_no_drift_alert(self, session_with_frameworks, caplog):
        """A sub-threshold shift with no band change produces zero drift alert lines."""
        db, mini_id = session_with_frameworks

        # "downgraded" outcome is not in _OUTCOME_DELTAS so produces no delta at all;
        # use a fresh mini with confidence in a position where a small shift won't cross a band
        sub_mini_id = str(uuid.uuid4())
        principles = _make_principles_json(
            [_fw("fw:sub", "missing tests before merge", confidence=0.50, evidence_ids=["e1", "e2", "e3", "e4", "e5"])]
        )
        await db.execute(
            text("INSERT INTO minis (id, username, status, principles_json) VALUES (:id, :u, 'ready', :pj)"),
            {"id": sub_mini_id, "u": f"sub-{sub_mini_id[:8]}", "pj": principles},
        )
        await db.commit()

        external_id = f"pr:sub-thresh-{uuid.uuid4().hex[:8]}"
        await upsert_review_cycle_prediction(
            db,
            sub_mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={},
                predicted_state=_review_state(
                    "Add tests.",
                    "request_changes",
                    blocking_issue_keys=["missing-tests"],
                    comments=[
                        _issue_comment(
                            "missing-tests",
                            comment_type="blocker",
                            disposition="request_changes",
                            summary="Tests missing.",
                        )
                    ],
                ),
            ),
        )

        with caplog.at_level(logging.INFO, logger="app.review_cycles"):
            await finalize_review_cycle(
                db,
                sub_mini_id,
                ReviewCycleOutcomeUpdateRequest(
                    external_id=external_id,
                    source_type="github",
                    # confirmed → +0.05. At 0.50 that's 0.55 — still neutral, shift=0.05 < 0.1 threshold.
                    human_review_outcome=_review_state(
                        "Good call.",
                        "request_changes",
                        comments=[
                            _issue_comment(
                                "missing-tests",
                                comment_type="blocker",
                                disposition="request_changes",
                                summary="Tests still missing.",
                            )
                        ],
                    ),
                    delta_metrics={},
                ),
            )

        drift_records = [
            r for r in caplog.records if r.getMessage() == "framework_drift_alert"
        ]
        assert len(drift_records) == 0
