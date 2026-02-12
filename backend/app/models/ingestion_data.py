import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class IngestionData(Base):
    __tablename__ = "ingestion_data"
    __table_args__ = (
        UniqueConstraint("mini_id", "source_name", "data_key", name="uq_ingestion_data"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mini_id: Mapped[int] = mapped_column(Integer, ForeignKey("minis.id"))
    source_name: Mapped[str] = mapped_column(String(50))
    data_key: Mapped[str] = mapped_column(String(100))
    data_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MiniRepoConfig(Base):
    __tablename__ = "mini_repo_config"
    __table_args__ = (
        UniqueConstraint("mini_id", "repo_full_name", name="uq_mini_repo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mini_id: Mapped[int] = mapped_column(Integer, ForeignKey("minis.id"))
    repo_full_name: Mapped[str] = mapped_column(String(255))
    included: Mapped[bool] = mapped_column(Boolean, default=True)
