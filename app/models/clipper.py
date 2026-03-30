# app/models/clipper.py
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class AssignmentStatus(enum.Enum):
    assigned = "assigned"
    posted = "posted"


class Clipper(Base):
    __tablename__ = "clippers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    accounts: Mapped[list["ClipperAccount"]] = relationship(
        back_populates="clipper", cascade="all, delete-orphan"
    )


class ClipperAccount(Base):
    __tablename__ = "clipper_accounts"
    __table_args__ = (
        UniqueConstraint("clipper_id", "account_id", name="uq_clipper_account"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    clipper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clippers.id", ondelete="CASCADE")
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cluster_accounts.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    clipper: Mapped["Clipper"] = relationship(back_populates="accounts")
    account = relationship("ClusterAccount")


class ClipAssignment(Base):
    __tablename__ = "clip_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cluster_accounts.id", ondelete="CASCADE")
    )
    video_key: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus), default=AssignmentStatus.assigned
    )
    post_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    account = relationship("ClusterAccount")
