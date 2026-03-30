# app/schemas/dubbing.py
from pydantic import BaseModel, field_validator

SUPPORTED_LANGUAGES = {"fr", "es", "he"}


class CreateDubbingRequest(BaseModel):
    source_url: str
    languages: list[str]

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("languages must not be empty")
        invalid = set(v) - SUPPORTED_LANGUAGES
        if invalid:
            raise ValueError(f"Unsupported languages: {invalid}. Supported: {sorted(SUPPORTED_LANGUAGES)}")
        return list(set(v))  # deduplicate


class DubbingOutputResponse(BaseModel):
    id: str
    language: str
    status: str
    output_video_key: str | None = None
    download_url: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    model_config = {"from_attributes": True}


class DubbingJobResponse(BaseModel):
    id: str
    status: str
    source_url: str
    languages: list[str]
    credits_charged: int
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    outputs: list[DubbingOutputResponse] = []

    model_config = {"from_attributes": True}


class DubbingJobSummaryResponse(BaseModel):
    id: str
    status: str
    source_url: str
    languages: list[str]
    credits_charged: int
    created_at: str

    model_config = {"from_attributes": True}


class DubbingJobListResponse(BaseModel):
    jobs: list[DubbingJobSummaryResponse]
    next_cursor: str | None = None
