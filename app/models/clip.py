import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, Integer, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("clip_extractions.id"))
    storage_key: Mapped[str] = mapped_column(String(500))
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    duration: Mapped[float] = mapped_column(Float)
    virality_score: Mapped[int] = mapped_column(Integer)
    hook_text: Mapped[str] = mapped_column(Text)
    transcript_text: Mapped[str] = mapped_column(Text)
    reframed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    extraction: Mapped["ClipExtraction"] = relationship(back_populates="clips")
    posts: Mapped[list["AccountPost"]] = relationship(back_populates="clip")
