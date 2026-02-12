import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class MiniRevision(Base):
    __tablename__ = "mini_revisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mini_id: Mapped[int] = mapped_column(Integer, ForeignKey("minis.id", ondelete="CASCADE"))
    revision_number: Mapped[int] = mapped_column(Integer)
    spirit_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    values_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str] = mapped_column(String(50), default="initial")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
