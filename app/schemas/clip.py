# app/schemas/clip.py
import re

from pydantic import BaseModel, field_validator


class ExtractClipsRequest(BaseModel):
    youtube_url: str
    cluster_id: str | None = None

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        youtube_pattern = re.compile(
            r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
        )
        if not youtube_pattern.match(v):
            raise ValueError("Invalid YouTube URL")
        return v


class UpdateClipRequest(BaseModel):
    transcript_text: str

    @field_validator("transcript_text")
    @classmethod
    def validate_length(cls, v: str) -> str:
        if len(v) > 50000:
            raise ValueError("Transcript text must be under 50,000 characters")
        return v


class UpdateLastGameplayRequest(BaseModel):
    gameplay_ids: list[str]

    @field_validator("gameplay_ids")
    @classmethod
    def validate_gameplay_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("gameplay_ids must not be empty")
        if len(v) > 20:
            raise ValueError("Maximum 20 gameplay clips")
        return v


class ClipResponse(BaseModel):
    id: str
    storage_key: str
    start_time: float
    end_time: float
    duration: float
    virality_score: int
    hook_text: str
    transcript_text: str
    reframed: bool
    preview_url: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class ExtractionResponse(BaseModel):
    id: str
    status: str
    youtube_url: str
    video_title: str | None = None
    video_duration: float | None = None
    error_message: str | None = None
    created_at: str
    completed_at: str | None = None
    clips: list[ClipResponse] = []
    last_gameplay_ids: list[str] | None = None
    source_type: str = "youtube"

    model_config = {"from_attributes": True}


class ExtractionSummaryResponse(BaseModel):
    id: str
    status: str
    youtube_url: str
    video_title: str | None = None
    clip_count: int = 0
    source_type: str = "youtube"
    created_at: str

    model_config = {"from_attributes": True}


class ExtractionListResponse(BaseModel):
    extractions: list[ExtractionSummaryResponse]
    next_cursor: str | None = None
