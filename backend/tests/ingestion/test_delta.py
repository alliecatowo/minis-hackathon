"""Tests for delta-query helpers (ALLIE-374 M1).

These tests use an in-memory SQLite database so no real PostgreSQL connection
is required.
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

from app.ingestion.delta import get_latest_external_ids, get_max_last_fetched_at
from app.models.evidence import Evidence


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
    ai_contamination_checked_at TEXT,
    context TEXT NOT NULL DEFAULT 'general'
)
"""

_CREATE_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_mini_source_external_id
ON evidence (mini_id, source_type, external_id)
WHERE external_id IS NOT NULL
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
        await conn.execute(text(_CREATE_IDX))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS evidence"))


@pytest_asyncio.fixture
async def session(engine, tables):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
        await s.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence(
    mini_id: str,
    source_type: str = "github",
    external_id: str | None = None,
    last_fetched_at: datetime | None = None,
) -> Evidence:
    return Evidence(
        id=str(uuid.uuid4()),
        mini_id=mini_id,
        source_type=source_type,
        item_type="commit",
        content="some content",
        last_fetched_at=last_fetched_at,
        external_id=external_id,
    )


# ---------------------------------------------------------------------------
# get_latest_external_ids
# ---------------------------------------------------------------------------


class TestGetLatestExternalIds:
    @pytest.mark.asyncio
    async def test_returns_expected_set(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        session.add(_evidence(mini_id, external_id="sha-abc"))
        session.add(_evidence(mini_id, external_id="sha-def"))
        session.add(_evidence(mini_id, external_id=None))  # NULL should be excluded
        await session.flush()

        result = await get_latest_external_ids(session, mini_id, "github")
        assert result == {"sha-abc", "sha-def"}

    @pytest.mark.asyncio
    async def test_empty_when_no_evidence(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        result = await get_latest_external_ids(session, mini_id, "github")
        assert result == set()

    @pytest.mark.asyncio
    async def test_scoped_to_mini_and_source(self, session: AsyncSession):
        mini_a = str(uuid.uuid4())
        mini_b = str(uuid.uuid4())
        session.add(_evidence(mini_a, source_type="github", external_id="gh-1"))
        session.add(_evidence(mini_b, source_type="github", external_id="gh-2"))
        session.add(_evidence(mini_a, source_type="claude_code", external_id="cc-1"))
        await session.flush()

        result = await get_latest_external_ids(session, mini_a, "github")
        assert result == {"gh-1"}

    @pytest.mark.asyncio
    async def test_excludes_null_external_ids(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        session.add(_evidence(mini_id, external_id=None))
        session.add(_evidence(mini_id, external_id=None))
        await session.flush()

        result = await get_latest_external_ids(session, mini_id, "github")
        assert result == set()


# ---------------------------------------------------------------------------
# get_max_last_fetched_at
# ---------------------------------------------------------------------------


class TestGetMaxLastFetchedAt:
    @pytest.mark.asyncio
    async def test_returns_max_timestamp(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 15, tzinfo=timezone.utc)
        session.add(_evidence(mini_id, last_fetched_at=t1))
        session.add(_evidence(mini_id, last_fetched_at=t2))
        await session.flush()

        result = await get_max_last_fetched_at(session, mini_id, "github")
        assert result is not None
        # Compare naive (SQLite strips tz)
        assert result.replace(tzinfo=None) == t2.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_ignores_null_entries(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        # Only rows with NULL last_fetched_at
        session.add(_evidence(mini_id, last_fetched_at=None))
        session.add(_evidence(mini_id, last_fetched_at=None))
        await session.flush()

        result = await get_max_last_fetched_at(session, mini_id, "github")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_rows(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        result = await get_max_last_fetched_at(session, mini_id, "github")
        assert result is None

    @pytest.mark.asyncio
    async def test_scoped_to_source_type(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 6, 1, tzinfo=timezone.utc)
        session.add(_evidence(mini_id, source_type="github", last_fetched_at=t1))
        session.add(_evidence(mini_id, source_type="claude_code", last_fetched_at=t2))
        await session.flush()

        result = await get_max_last_fetched_at(session, mini_id, "github")
        assert result is not None
        assert result.replace(tzinfo=None) == t1.replace(tzinfo=None)
