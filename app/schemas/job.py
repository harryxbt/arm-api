from pydantic import BaseModel, field_validator


class CaptionStyleRequest(BaseModel):
    font: str | None = None            # montserrat, impact, bangers, anton, bebas, poppins
    font_size: int | None = None        # default 68
    words_per_chunk: int | None = None  # default 3
    position: str | None = None         # top, center, bottom
    primary_color: str | None = None    # hex RGB e.g. "FFFFFF"
    highlight_color: str | None = None  # hex RGB e.g. "00FFFF"
    outline_color: str | None = None    # hex RGB e.g. "000000"
    highlight: bool | None = None       # word-by-word highlight animation

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: str | None) -> str | None:
        if v is not None and v not in ("top", "center", "bottom"):
            raise ValueError("position must be top, center, or bottom")
        return v


class CreateJobRequest(BaseModel):
    source_video_key: str
    gameplay_id: str | None = None
    gameplay_key: str | None = None
    caption_style: CaptionStyleRequest | None = None


class CreateBatchJobRequest(BaseModel):
    source_video_key: str
    gameplay_ids: list[str]
    caption_style: CaptionStyleRequest | None = None

    @field_validator("gameplay_ids")
    @classmethod
    def validate_gameplay_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("gameplay_ids must not be empty")
        if len(v) > 20:
            raise ValueError("Maximum 20 gameplay clips per batch")
        return v


class JobResponse(BaseModel):
    id: str
    status: str
    source_video_key: str
    gameplay_key: str
    output_url: str | None = None
    error_message: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class BatchJobResponse(BaseModel):
    jobs: list[JobResponse]
    credits_deducted: int


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    next_cursor: str | None = None
