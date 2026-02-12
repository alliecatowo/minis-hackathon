import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class CommunicationContext(Base):
    __tablename__ = "communication_contexts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mini_id: Mapped[int] = mapped_column(Integer, ForeignKey("minis.id"))
    context_key: Mapped[str] = mapped_column(String(50))
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    voice_modulation: Mapped[str] = mapped_column(Text)  # Voice delta description
    example_messages: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
