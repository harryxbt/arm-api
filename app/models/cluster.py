import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, UniqueConstraint, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class Platform(str, enum.Enum):
    youtube = "youtube"
    tiktok = "tiktok"
    instagram = "instagram"


class PostStatus(str, enum.Enum):
    pending = "pending"
    uploading = "uploading"
    posted = "posted"
    failed = "failed"


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    accounts: Mapped[list["ClusterAccount"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    extractions: Mapped[list["ClipExtraction"]] = relationship(
        back_populates="cluster"
    )


class ClusterAccount(Base):
    __tablename__ = "cluster_accounts"
    __table_args__ = (
        UniqueConstraint("cluster_id", "platform", "handle", name="uq_cluster_platform_handle"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    handle: Mapped[str] = mapped_column(String(255))
    credentials: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    cluster: Mapped["Cluster"] = relationship(back_populates="accounts")
    posts: Mapped[list["AccountPost"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class AccountPost(Base):
    __tablename__ = "account_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("cluster_accounts.id", ondelete="CASCADE"))
    clip_id: Mapped[str | None] = mapped_column(ForeignKey("clips.id", ondelete="SET NULL"), nullable=True)
    platform_post_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    video_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PostStatus | None] = mapped_column(Enum(PostStatus), nullable=True)
    platform_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    account: Mapped["ClusterAccount"] = relationship(back_populates="posts")
    clip: Mapped["Clip | None"] = relationship(back_populates="posts")
