# app/schemas/clipper.py
from pydantic import BaseModel, EmailStr


# --- Admin: Clipper management ---

class CreateClipperRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class ClipperAccountResponse(BaseModel):
    id: str
    platform: str
    handle: str
    cluster_name: str


class ClipperSummaryResponse(BaseModel):
    id: str
    email: str
    name: str
    is_active: bool
    account_count: int
    created_at: str


class ClipperDetailResponse(BaseModel):
    id: str
    email: str
    name: str
    is_active: bool
    accounts: list[ClipperAccountResponse]
    created_at: str


class ClipperListResponse(BaseModel):
    clippers: list[ClipperSummaryResponse]


class LinkAccountRequest(BaseModel):
    account_id: str


# --- Admin: Assignments ---

class CreateAssignmentRequest(BaseModel):
    video_key: str
    account_id: str
    caption: str = ""
    hashtags: str = ""


class AssignmentResponse(BaseModel):
    id: str
    account_id: str
    platform: str
    handle: str
    video_key: str
    download_url: str | None = None
    caption: str
    hashtags: str
    status: str
    post_url: str | None = None
    posted_at: str | None = None
    created_at: str


class AssignmentListResponse(BaseModel):
    assignments: list[AssignmentResponse]


# --- Clipper portal ---

class ClipperLoginRequest(BaseModel):
    email: EmailStr
    password: str


class ClipperTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    name: str


class SubmitPostRequest(BaseModel):
    post_url: str
