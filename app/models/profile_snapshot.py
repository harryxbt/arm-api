# app/models/profile_snapshot.py
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, BigInteger, Text, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"
    __table_args__ = (
        Index("ix_profile_snapshots_account_scraped", "account_id", "scraped_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("cluster_accounts.id", ondelete="CASCADE")
    )
    followers: Mapped[int] = mapped_column(Integer)
    following: Mapped[int] = mapped_column(Integer)
    total_likes: Mapped[int] = mapped_column(BigInteger)
    total_videos: Mapped[int] = mapped_column(Integer)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recent_videos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
