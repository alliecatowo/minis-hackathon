"""Tests for author-grounded AI-contamination scoring."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.ingestion.ai_contamination import (
    AIDetectionResult,
    AuthorBaseline,
    classify_and_persist_evidence,
    score_evidence_batch,
)
from app.models.evidence import Evidence


Classifier = Callable[[str, AuthorBaseline], Awaitable[AIDetectionResult]]

_CREATE_EVIDENCE = """
CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    item_type TEXT NOT NULL,
    content TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT 'general',
    metadata_json TEXT,
    source_privacy TEXT NOT NULL DEFAULT 'public',
    retention_policy TEXT,
    retention_expires_at TEXT,
    source_authorization TEXT,
    authorization_revoked_at TEXT,
    access_classification TEXT,
    lifecycle_audit_json TEXT,
    source_uri TEXT,
    author_id TEXT,
    audience_id TEXT,
    target_id TEXT,
    scope_json TEXT,
    raw_body TEXT,
    raw_body_ref TEXT,
    raw_context_json TEXT,
    provenance_json TEXT,
    explored INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    external_id TEXT,
    evidence_date TEXT,
    last_fetched_at TEXT,
    content_hash TEXT,
    ai_contamination_score REAL,
    ai_contamination_confidence REAL,
    ai_contamination_status TEXT,
    ai_contamination_reasoning TEXT,
    ai_contamination_provenance_json TEXT,
    ai_contamination_checked_at TEXT
)
"""


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_EVIDENCE))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _content(label: str) -> str:
    return (
        f"{label}: I tend to prefer small explicit changes with provenance because "
        "review decisions need to survive later reconstruction and audit. "
        "This sentence keeps the sample above the baseline threshold."
    )


async def _seed(
    session: AsyncSession,
    mini_id: str,
    *,
    candidate_content: str = "Candidate text that needs classification.",
    baseline_count: int = 2,
) -> str:
    for i in range(baseline_count):
        session.add(
            Evidence(
                id=f"baseline-{i}",
                mini_id=mini_id,
                source_type="github",
                item_type="review",
                content=_content(f"baseline {i}"),
                author_id="alice",
                external_id=f"baseline-{i}",
                provenance_json={
                    "collector": "github",
                    "authored_by_subject": True,
                    "confidence": 0.95,
                },
            )
        )
    candidate_id = "candidate"
    session.add(
        Evidence(
            id=candidate_id,
            mini_id=mini_id,
            source_type="github",
            item_type="review",
            content=candidate_content,
            external_id="candidate",
        )
    )
    await session.flush()
    return candidate_id


async def _classify(
    session_factory,
    classifier: Classifier,
    *,
    baseline_count: int = 2,
) -> Evidence:
    mini_id = str(uuid.uuid4())
    async with session_factory() as session:
        async with session.begin():
            candidate_id = await _seed(session, mini_id, baseline_count=baseline_count)
            await classify_and_persist_evidence(
                mini_id,
                candidate_id,
                session,
                username="alice",
                classifier=classifier,
            )
        row = (
            await session.execute(select(Evidence).where(Evidence.id == candidate_id))
        ).scalar_one()
        return row


@pytest.mark.asyncio
async def test_persists_human_verdict(session_factory):
    async def classifier(text: str, baseline: AuthorBaseline) -> AIDetectionResult:
        assert len(baseline.samples) == 2
        assert set(baseline.evidence_ids) == {"baseline-0", "baseline-1"}
        return AIDetectionResult(verdict="human", score=0.08, confidence=0.91, reasoning="fits")

    row = await _classify(session_factory, classifier)

    assert row.ai_contamination_status == "human"
    assert row.ai_contamination_score == 0.08
    assert row.ai_contamination_confidence == 0.91
    assert set(row.ai_contamination_provenance_json["baseline_evidence_ids"]) == {
        "baseline-0",
        "baseline-1",
    }


@pytest.mark.asyncio
async def test_persists_ai_like_verdict(session_factory):
    async def classifier(text: str, baseline: AuthorBaseline) -> AIDetectionResult:
        return AIDetectionResult(
            verdict="ai_like",
            score=0.93,
            confidence=0.88,
            reasoning="surrogate polish",
        )

    row = await _classify(session_factory, classifier)

    assert row.ai_contamination_status == "ai_like"
    assert row.ai_contamination_score == 0.93


@pytest.mark.asyncio
async def test_low_confidence_result_becomes_uncertain(session_factory):
    async def classifier(text: str, baseline: AuthorBaseline) -> AIDetectionResult:
        return AIDetectionResult(
            verdict="ai_like",
            score=0.82,
            confidence=0.41,
            reasoning="weak signal",
        )

    row = await _classify(session_factory, classifier)

    assert row.ai_contamination_status == "uncertain"
    assert row.ai_contamination_score == 0.82
    assert row.ai_contamination_confidence == 0.41


@pytest.mark.asyncio
async def test_insufficient_baseline_does_not_call_classifier(session_factory):
    called = False

    async def classifier(text: str, baseline: AuthorBaseline) -> AIDetectionResult:
        nonlocal called
        called = True
        return AIDetectionResult(verdict="human", score=0.0, confidence=1.0, reasoning="nope")

    row = await _classify(session_factory, classifier, baseline_count=1)

    assert called is False
    assert row.ai_contamination_status == "insufficient_baseline"
    assert row.ai_contamination_score is None
    assert row.ai_contamination_provenance_json["state"] == "insufficient_baseline"


# ---------------------------------------------------------------------------
# score_evidence_batch — ai_like items are marked explored=True (MINI-235)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_evidence_batch_marks_ai_like_as_explored(session_factory):
    """Items classified as ai_like must be marked explored=True so explorers skip them."""

    async def ai_like_classifier(text: str, baseline: AuthorBaseline) -> AIDetectionResult:
        return AIDetectionResult(
            verdict="ai_like",
            score=0.92,
            confidence=0.85,
            reasoning="surrogate polish",
        )

    mini_id = str(uuid.uuid4())
    async with session_factory() as session:
        async with session.begin():
            await _seed(session, mini_id, candidate_content="Definitely AI-generated text.")

    counts = await score_evidence_batch(
        mini_id,
        ["candidate"],
        session_factory,
        username="alice",
        classifier=ai_like_classifier,
    )

    assert counts["ai_like"] == 1

    # The candidate row must now be marked explored=True
    async with session_factory() as session:
        row = (
            await session.execute(select(Evidence).where(Evidence.id == "candidate"))
        ).scalar_one()
    assert row.explored is True
    assert row.ai_contamination_status == "ai_like"


@pytest.mark.asyncio
async def test_score_evidence_batch_human_verdict_does_not_set_explored(session_factory):
    """Items classified as human must NOT be auto-marked explored — they need processing."""

    async def human_classifier(text: str, baseline: AuthorBaseline) -> AIDetectionResult:
        return AIDetectionResult(
            verdict="human",
            score=0.12,
            confidence=0.90,
            reasoning="author voice match",
        )

    mini_id = str(uuid.uuid4())
    async with session_factory() as session:
        async with session.begin():
            await _seed(session, mini_id, candidate_content="Genuine developer prose.")

    await score_evidence_batch(
        mini_id,
        ["candidate"],
        session_factory,
        username="alice",
        classifier=human_classifier,
    )

    async with session_factory() as session:
        row = (
            await session.execute(select(Evidence).where(Evidence.id == "candidate"))
        ).scalar_one()
    # explored should remain False — let the explorer process it
    assert row.explored is False
    assert row.ai_contamination_status == "human"


@pytest.mark.asyncio
async def test_score_evidence_batch_returns_verdict_counts(session_factory):
    """score_evidence_batch returns a dict with verdict counts."""

    async def human_classifier(text: str, baseline: AuthorBaseline) -> AIDetectionResult:
        return AIDetectionResult(
            verdict="human",
            score=0.10,
            confidence=0.90,
            reasoning="fits",
        )

    mini_id = str(uuid.uuid4())
    async with session_factory() as session:
        async with session.begin():
            await _seed(session, mini_id)

    counts = await score_evidence_batch(
        mini_id,
        ["candidate"],
        session_factory,
        username="alice",
        classifier=human_classifier,
    )

    assert isinstance(counts, dict)
    assert counts["human"] == 1
    assert counts.get("ai_like", 0) == 0
