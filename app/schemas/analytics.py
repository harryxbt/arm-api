# app/schemas/analytics.py
from pydantic import BaseModel


class SnapshotResponse(BaseModel):
    id: str
    account_id: str
    followers: int
    following: int
    total_likes: int
    total_videos: int
    bio: str | None = None
    avatar_url: str | None = None
    recent_videos: list | None = None
    scraped_at: str

    model_config = {"from_attributes": True}


class GrowthResponse(BaseModel):
    current_followers: int
    previous_followers: int | None
    follower_change: int | None
    current_likes: int
    previous_likes: int | None
    likes_change: int | None
    current_videos: int
    previous_videos: int | None
    videos_change: int | None
    period_days: int
    avg_views: float | None = None
    avg_likes: float | None = None
    avg_comments: float | None = None


class AccountSummary(BaseModel):
    account_id: str
    handle: str
    platform: str
    followers: int | None = None
    total_likes: int | None = None
    total_videos: int | None = None
    last_scraped: str | None = None


class ClusterOverviewResponse(BaseModel):
    cluster_id: str
    cluster_name: str
    total_followers: int
    total_likes: int
    total_videos: int
    account_count: int
    accounts: list[AccountSummary]
