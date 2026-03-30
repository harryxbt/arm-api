from typing import Literal

from pydantic import BaseModel


class CreateClusterRequest(BaseModel):
    name: str


class UpdateClusterRequest(BaseModel):
    name: str


class AccountCredentials(BaseModel):
    email: str | None = None
    email_password: str | None = None
    phone: str | None = None
    social_password: str | None = None


class AddAccountRequest(BaseModel):
    platform: Literal["youtube", "tiktok", "instagram"]
    handle: str
    credentials: AccountCredentials | None = None


class CreatePostRequest(BaseModel):
    clip_id: str | None = None
    platform_post_id: str | None = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    posted_at: str | None = None


class UpdatePostRequest(BaseModel):
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None


class StatsResponse(BaseModel):
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0


class PostResponse(BaseModel):
    id: str
    clip_id: str | None = None
    platform_post_id: str | None = None
    views: int
    likes: int
    comments: int
    shares: int
    posted_at: str | None = None
    created_at: str


class UpdateAccountRequest(BaseModel):
    handle: str | None = None
    credentials: AccountCredentials | None = None


class AccountResponse(BaseModel):
    id: str
    platform: str
    handle: str
    credentials: AccountCredentials | None = None
    stats: StatsResponse
    posts: list[PostResponse] = []
    created_at: str


class AccountSummaryResponse(BaseModel):
    id: str
    platform: str
    handle: str
    created_at: str


class ClusterSummaryResponse(BaseModel):
    id: str
    name: str
    account_count: int
    stats: StatsResponse
    created_at: str


class ClusterListResponse(BaseModel):
    clusters: list[ClusterSummaryResponse]


class ExtractionSummaryInCluster(BaseModel):
    id: str
    status: str
    youtube_url: str
    video_title: str | None = None
    created_at: str


class ClusterDetailResponse(BaseModel):
    id: str
    name: str
    created_at: str
    accounts: list[AccountResponse]
    extractions: list[ExtractionSummaryInCluster]
    stats: StatsResponse
