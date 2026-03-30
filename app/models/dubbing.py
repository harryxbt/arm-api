# app/models/dubbing.py
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class DubbingJobStatus(str, enum.Enum):
    pending = "pending"
    downloading = "downloading"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class DubbingOutputStatus(str, enum.Enum):
    pending = "pending"
    dubbing = "dubbing"
    lip_syncing = "lip_syncing"
    completed = "completed"
    failed = "failed"


class DubbingJob(Base):
    __tablename__ = "dubbing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_video_key: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    languages: Mapped[list] = mapped_column(JSON)
    status: Mapped[DubbingJobStatus] = mapped_column(
        Enum(DubbingJobStatus), default=DubbingJobStatus.pending
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_charged: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="dubbing_jobs")
    outputs: Mapped[list["DubbingOutput"]] = relationship(
        back_populates="dubbing_job", cascade="all, delete-orphan"
    )


class DubbingOutput(Base):
    __tablename__ = "dubbing_outputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    dubbing_job_id: Mapped[str] = mapped_column(ForeignKey("dubbing_jobs.id"))
    language: Mapped[str] = mapped_column(String(10))
    elevenlabs_dubbing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dubbed_audio_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synclabs_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_video_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[DubbingOutputStatus] = mapped_column(
        Enum(DubbingOutputStatus), default=DubbingOutputStatus.pending
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dubbing_job: Mapped["DubbingJob"] = relationship(back_populates="outputs")
