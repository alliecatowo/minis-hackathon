"""Tests for incremental ingestion schema additions (ALLIE-374 M1).

Verifies that the new columns exist with the correct types and defaults,
and that the partial unique index behaves correctly (in-memory SQLite).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.evidence import Evidence, ExplorerProgress


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CREATE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    item_type TEXT NOT NULL,
    content TEXT NOT NULL,
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
    explored INTEGER NOT NULL DEFAULT 0,
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
    ai_contamination_checked_at TEXT,
    context TEXT NOT NULL DEFAULT 'general'
)
"""

_CREATE_EVIDENCE_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_mini_source_external_id
ON evidence (mini_id, source_type, external_id)
WHERE external_id IS NOT NULL
"""

_CREATE_EXPLORER_PROGRESS = """
CREATE TABLE IF NOT EXISTS explorer_progress (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    explored_items INTEGER NOT NULL DEFAULT 0,
    findings_count INTEGER NOT NULL DEFAULT 0,
    memories_count INTEGER NOT NULL DEFAULT 0,
    quotes_count INTEGER NOT NULL DEFAULT 0,
    nodes_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    summary TEXT,
    last_explored_at TEXT
)
"""


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
        await conn.execute(text(_CREATE_EVIDENCE))
        await conn.execute(text(_CREATE_EVIDENCE_IDX))
        await conn.execute(text(_CREATE_EXPLORER_PROGRESS))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS evidence"))
        await conn.execute(text("DROP TABLE IF EXISTS explorer_progress"))


@pytest_asyncio.fixture
async def session(engine, tables):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
        await s.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(mini_id: str, external_id: str | None = None) -> Evidence:
    return Evidence(
        id=str(uuid.uuid4()),
        mini_id=mini_id,
        source_type="github",
        item_type="commit",
        content="commit message here",
        external_id=external_id,
    )


# ---------------------------------------------------------------------------
# Evidence column tests
# ---------------------------------------------------------------------------


class TestEvidenceIncrementalColumns:
    def test_external_id_column_exists(self):
        col = Evidence.__table__.columns.get("external_id")
        assert col is not None

    def test_external_id_is_nullable(self):
        col = Evidence.__table__.columns["external_id"]
        assert col.nullable is True

    def test_external_id_max_length(self):
        col = Evidence.__table__.columns["external_id"]
        assert col.type.length == 255

    def test_last_fetched_at_column_exists(self):
        col = Evidence.__table__.columns.get("last_fetched_at")
        assert col is not None

    def test_last_fetched_at_is_nullable(self):
        col = Evidence.__table__.columns["last_fetched_at"]
        assert col.nullable is True

    def test_content_hash_column_exists(self):
        col = Evidence.__table__.columns.get("content_hash")
        assert col is not None

    def test_content_hash_is_nullable(self):
        col = Evidence.__table__.columns["content_hash"]
        assert col.nullable is True

    def test_content_hash_max_length(self):
        col = Evidence.__table__.columns["content_hash"]
        assert col.type.length == 64

    def test_new_fields_default_none(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="x",
        )
        assert ev.external_id is None
        assert ev.last_fetched_at is None
        assert ev.content_hash is None

    def test_review_grade_envelope_columns_exist(self):
        for name in [
            "source_uri",
            "author_id",
            "audience_id",
            "target_id",
            "scope_json",
            "raw_body",
            "raw_body_ref",
            "raw_context_json",
            "provenance_json",
        ]:
            col = Evidence.__table__.columns.get(name)
            assert col is not None
            assert col.nullable is True

    def test_ai_contamination_verdict_columns_exist(self):
        for name in [
            "ai_contamination_score",
            "ai_contamination_confidence",
            "ai_contamination_status",
            "ai_contamination_reasoning",
            "ai_contamination_provenance_json",
            "ai_contamination_checked_at",
        ]:
            col = Evidence.__table__.columns.get(name)
            assert col is not None
            assert col.nullable is True

    def test_review_grade_envelope_defaults_none(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="x",
        )
        assert ev.source_uri is None
        assert ev.author_id is None
        assert ev.audience_id is None
        assert ev.target_id is None
        assert ev.scope_json is None
        assert ev.raw_body is None
        assert ev.raw_body_ref is None
        assert ev.raw_context_json is None
        assert ev.provenance_json is None
        assert ev.ai_contamination_score is None
        assert ev.ai_contamination_confidence is None
        assert ev.ai_contamination_status is None
        assert ev.ai_contamination_reasoning is None
        assert ev.ai_contamination_provenance_json is None
        assert ev.ai_contamination_checked_at is None

    def test_can_set_all_new_fields(self):
        now = datetime.now(timezone.utc)
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="x",
            external_id="abc123",
            last_fetched_at=now,
            content_hash="a" * 64,
            source_uri="https://github.com/acme/app/commit/abc123",
            author_id="github:author",
            scope_json={"type": "repo", "id": "acme/app"},
            raw_body="raw commit message",
            provenance_json={"collector": "github"},
            ai_contamination_score=0.1,
            ai_contamination_confidence=0.9,
            ai_contamination_status="human",
            ai_contamination_reasoning="matches baseline",
            ai_contamination_provenance_json={"baseline_evidence_ids": ["ev-1"]},
            ai_contamination_checked_at=now,
        )
        assert ev.external_id == "abc123"
        assert ev.last_fetched_at == now
        assert ev.content_hash == "a" * 64
        assert ev.source_uri == "https://github.com/acme/app/commit/abc123"
        assert ev.author_id == "github:author"
        assert ev.scope_json == {"type": "repo", "id": "acme/app"}
        assert ev.raw_body == "raw commit message"
        assert ev.provenance_json == {"collector": "github"}
        assert ev.ai_contamination_score == 0.1
        assert ev.ai_contamination_confidence == 0.9
        assert ev.ai_contamination_status == "human"
        assert ev.ai_contamination_reasoning == "matches baseline"
        assert ev.ai_contamination_provenance_json == {"baseline_evidence_ids": ["ev-1"]}
        assert ev.ai_contamination_checked_at == now


# ---------------------------------------------------------------------------
# ExplorerProgress column tests
# ---------------------------------------------------------------------------


class TestExplorerProgressIncrementalColumns:
    def test_last_explored_at_column_exists(self):
        col = ExplorerProgress.__table__.columns.get("last_explored_at")
        assert col is not None

    def test_last_explored_at_is_nullable(self):
        col = ExplorerProgress.__table__.columns["last_explored_at"]
        assert col.nullable is True

    def test_last_explored_at_defaults_none(self):
        prog = ExplorerProgress(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
        )
        assert prog.last_explored_at is None


# ---------------------------------------------------------------------------
# Partial unique index tests (SQLite CREATE UNIQUE INDEX ... WHERE)
# ---------------------------------------------------------------------------


class TestEvidencePartialUniqueIndex:
    @pytest.mark.asyncio
    async def test_unique_external_id_per_mini_source(self, session: AsyncSession):
        """Two rows with same (mini_id, source_type, external_id) should conflict."""
        from sqlalchemy.exc import IntegrityError

        mini_id = str(uuid.uuid4())
        session.add(_make_evidence(mini_id, external_id="sha-abc"))
        await session.flush()

        session.add(_make_evidence(mini_id, external_id="sha-abc"))
        with pytest.raises(IntegrityError):
            await session.flush()

    @pytest.mark.asyncio
    async def test_null_external_id_allows_multiple_rows(self, session: AsyncSession):
        """Multiple rows with NULL external_id must NOT violate the partial index."""
        mini_id = str(uuid.uuid4())
        session.add(_make_evidence(mini_id, external_id=None))
        session.add(_make_evidence(mini_id, external_id=None))
        # Should not raise
        await session.flush()

    @pytest.mark.asyncio
    async def test_same_external_id_different_mini_allowed(self, session: AsyncSession):
        """Same external_id for different minis is fine."""
        mini_a = str(uuid.uuid4())
        mini_b = str(uuid.uuid4())
        session.add(_make_evidence(mini_a, external_id="sha-xyz"))
        session.add(_make_evidence(mini_b, external_id="sha-xyz"))
        # Should not raise
        await session.flush()
