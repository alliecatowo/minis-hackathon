"""Models for evidence storage and explorer progress tracking.

Evidence represents raw data from ingestion sources. ExplorerFinding and
ExplorerQuote capture structured outputs from explorer agents.
ExplorerProgress tracks per-source agent progress for a mini.
"""

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class Evidence(Base):
    """Raw data from ingestion sources, organized per mini per source."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_privacy: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    explored: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Incremental ingestion fields (ALLIE-374 M1)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    last_fetched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # AI contamination detection (ALLIE-433)
    ai_contamination_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_contamination_checked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Partial unique index: prevents duplicate inserts for the same
        # (mini, source, external_id) tuple. NULL external_id is excluded
        # so legacy rows (no external_id) don't conflict with each other.
        Index(
            "uq_evidence_mini_source_external_id",
            "mini_id",
            "source_type",
            "external_id",
            unique=True,
            postgresql_where="external_id IS NOT NULL",
        ),
    )


class ExplorerFinding(Base):
    """Structured findings persisted by explorer agents."""

    __tablename__ = "explorer_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExplorerQuote(Base):
    """Behavioral quotes extracted by explorer agents."""

    __tablename__ = "explorer_quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    significance: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExplorerProgress(Base):
    """Tracks agent progress per mini per source."""

    __tablename__ = "explorer_progress"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    explored_items: Mapped[int] = mapped_column(Integer, default=0)
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    memories_count: Mapped[int] = mapped_column(Integer, default=0)
    quotes_count: Mapped[int] = mapped_column(Integer, default=0)
    nodes_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Incremental ingestion: timestamp of the most recent successful exploration (ALLIE-374 M1)
    last_explored_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
