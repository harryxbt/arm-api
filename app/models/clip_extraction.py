import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, Integer, Text, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class ExtractionStatus(str, enum.Enum):
    pending = "pending"
    downloading = "downloading"
    transcribing = "transcribing"
    analyzing = "analyzing"
    extracting = "extracting"
    completed = "completed"
    failed = "failed"


class SourceType(str, enum.Enum):
    youtube = "youtube"
    instagram = "instagram"
    upload = "upload"


class ClipExtraction(Base):
    __tablename__ = "clip_extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType), default=SourceType.youtube, server_default="youtube"
    )
    last_gameplay_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ExtractionStatus] = mapped_column(
        Enum(ExtractionStatus), default=ExtractionStatus.pending
    )
    youtube_url: Mapped[str] = mapped_column(String(2048))
    video_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_video_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_charged: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="clip_extractions")
    cluster: Mapped["Cluster | None"] = relationship(back_populates="extractions")
    clips: Mapped[list["Clip"]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )
