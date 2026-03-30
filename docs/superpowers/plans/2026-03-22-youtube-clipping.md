# YouTube Smart Clipping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pipeline that takes a YouTube URL, extracts the best 30-90s clips using AI, reframes to vertical 9:16 with face tracking, and saves them as source videos for the existing splitscreen pipeline.

**Architecture:** Two new DB models (ClipExtraction, Clip) + three new services (YouTube downloader, OpenAI clip analyzer, MediaPipe face reframer) + Celery task for async processing + API routes for submitting and viewing extractions. Follows existing patterns from the jobs/worker system.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Celery, yt-dlp, OpenAI (GPT-4o), Deepgram (existing), MediaPipe, FFmpeg

**Spec:** `docs/superpowers/specs/2026-03-22-youtube-clipping-design.md`

---

## File Structure

### New Files
- `app/models/clip_extraction.py` — ClipExtraction + ExtractionStatus enum
- `app/models/clip.py` — Clip model
- `app/schemas/clip.py` — Pydantic request/response schemas
- `app/services/youtube.py` — yt-dlp download service
- `app/services/clip_analyzer.py` — OpenAI transcript analysis
- `app/services/face_reframer.py` — MediaPipe face tracking + FFmpeg reframe
- `app/routes/clips.py` — API routes for clip extraction
- `app/clip_worker.py` — Celery task for clip extraction pipeline
- `tests/test_youtube_service.py` — YouTube downloader tests
- `tests/test_clip_analyzer.py` — OpenAI analyzer tests
- `tests/test_face_reframer.py` — Face reframer tests
- `tests/test_clip_routes.py` — Route tests

### Modified Files
- `app/models/user.py` — Add `clip_extractions` relationship
- `app/config.py` — Add `openai_api_key` and `openai_model` settings
- `app/services/credits.py` — Update `refund_credit` signature to accept `job_id: str | None`
- `app/main.py` — Register clips router
- `requirements.txt` — Add `openai`, `yt-dlp`, `mediapipe`, `opencv-python-headless`
- `migrations/versions/` — New migration for clip_extractions and clips tables

---

## Task 1: Add Dependencies and Config

**Files:**
- Modify: `requirements.txt`
- Modify: `app/config.py`

- [ ] **Step 1: Add new dependencies to requirements.txt**

Append to `requirements.txt`:
```
openai
yt-dlp
mediapipe
opencv-python-headless
```

- [ ] **Step 2: Install dependencies**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && pip install openai yt-dlp mediapipe opencv-python-headless`

- [ ] **Step 2b: Update `refund_credit` signature in `app/services/credits.py`**

Change line 24 from:
```python
def refund_credit(db: Session, user_id: str, job_id: str, commit: bool = True) -> None:
```
To:
```python
def refund_credit(db: Session, user_id: str, job_id: str | None = None, commit: bool = True) -> None:
```

This allows clip extractions to refund credits without a job reference.

- [ ] **Step 3: Add config settings to `app/config.py`**

Add two new fields to the `Settings` class (after `deepgram_api_key`):
```python
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt app/config.py
git commit -m "feat: add openai, yt-dlp, mediapipe dependencies and config"
```

---

## Task 2: ClipExtraction and Clip Models

**Files:**
- Create: `app/models/clip_extraction.py`
- Create: `app/models/clip.py`
- Modify: `app/models/user.py`

- [ ] **Step 1: Create ClipExtraction model**

```python
# app/models/clip_extraction.py
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, Integer, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class ExtractionStatus(str, enum.Enum):
    pending = "pending"
    downloading = "downloading"
    transcribing = "transcribing"
    analyzing = "analyzing"
    extracting = "extracting"
    completed = "completed"
    failed = "failed"


class ClipExtraction(Base):
    __tablename__ = "clip_extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[ExtractionStatus] = mapped_column(
        Enum(ExtractionStatus), default=ExtractionStatus.pending
    )
    youtube_url: Mapped[str] = mapped_column(String(2048))
    video_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_video_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_charged: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="clip_extractions")
    clips: Mapped[list["Clip"]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )
```

- [ ] **Step 2: Create Clip model**

```python
# app/models/clip.py
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, Integer, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("clip_extractions.id"))
    storage_key: Mapped[str] = mapped_column(String(500))
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    duration: Mapped[float] = mapped_column(Float)
    virality_score: Mapped[int] = mapped_column(Integer)
    hook_text: Mapped[str] = mapped_column(Text)
    transcript_text: Mapped[str] = mapped_column(Text)
    reframed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    extraction: Mapped["ClipExtraction"] = relationship(back_populates="clips")
```

- [ ] **Step 3: Add relationship to User model**

In `app/models/user.py`, add after line 32 (`refresh_tokens` relationship):
```python
    clip_extractions: Mapped[list["ClipExtraction"]] = relationship(back_populates="user")
```

- [ ] **Step 4: Generate and run Alembic migration**

Run:
```bash
cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api"
alembic revision --autogenerate -m "add clip_extractions and clips tables"
alembic upgrade head
```

- [ ] **Step 5: Commit**

```bash
git add app/models/clip_extraction.py app/models/clip.py app/models/user.py migrations/versions/
git commit -m "feat: add ClipExtraction and Clip models with migration"
```

---

## Task 3: Clip Schemas

**Files:**
- Create: `app/schemas/clip.py`

- [ ] **Step 1: Create schemas**

```python
# app/schemas/clip.py
import re

from pydantic import BaseModel, field_validator


class ExtractClipsRequest(BaseModel):
    youtube_url: str

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        youtube_pattern = re.compile(
            r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
        )
        if not youtube_pattern.match(v):
            raise ValueError("Invalid YouTube URL")
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

    model_config = {"from_attributes": True}


class ExtractionSummaryResponse(BaseModel):
    id: str
    status: str
    youtube_url: str
    video_title: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class ExtractionListResponse(BaseModel):
    extractions: list[ExtractionSummaryResponse]
    next_cursor: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add app/schemas/clip.py
git commit -m "feat: add clip extraction request/response schemas"
```

---

## Task 4: YouTube Download Service

**Files:**
- Create: `app/services/youtube.py`
- Create: `tests/test_youtube_service.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_youtube_service.py
import os
import pytest
from unittest.mock import patch, MagicMock

from app.services.youtube import download_video, validate_youtube_url, MAX_DURATION_SECONDS


class TestValidateYoutubeUrl:
    def test_valid_watch_url(self):
        assert validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_valid_short_url(self):
        assert validate_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_valid_shorts_url(self):
        assert validate_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ") is True

    def test_invalid_url(self):
        assert validate_youtube_url("https://vimeo.com/12345") is False

    def test_empty_url(self):
        assert validate_youtube_url("") is False


class TestDownloadVideo:
    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_download_success(self, mock_ydl_class, tmp_path):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Video",
            "duration": 300.0,
            "width": 1920,
            "height": 1080,
            "requested_downloads": [{"filepath": str(tmp_path / "video.mp4")}],
        }
        # Create the fake file so the function can find it
        (tmp_path / "video.mp4").write_bytes(b"fake video")

        result = download_video("https://youtube.com/watch?v=abc123", str(tmp_path))
        assert result["title"] == "Test Video"
        assert result["duration"] == 300.0
        assert result["width"] == 1920
        assert result["height"] == 1080

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_download_too_long(self, mock_ydl_class, tmp_path):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Long Video",
            "duration": MAX_DURATION_SECONDS + 1,
            "width": 1920,
            "height": 1080,
        }

        with pytest.raises(ValueError, match="Video too long"):
            download_video("https://youtube.com/watch?v=abc123", str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_youtube_service.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the service**

```python
# app/services/youtube.py
import os
import re

import yt_dlp

MAX_DURATION_SECONDS = 3600  # 60 minutes


def validate_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube URL."""
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
    )
    return bool(pattern.match(url))


def download_video(url: str, output_dir: str) -> dict:
    """Download a YouTube video and return metadata.

    Returns dict with: title, duration, filepath, width, height
    Raises ValueError if video exceeds MAX_DURATION_SECONDS.
    """
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "source.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        duration = info.get("duration", 0)
        if duration > MAX_DURATION_SECONDS:
            raise ValueError(
                f"Video too long ({duration:.0f}s, max {MAX_DURATION_SECONDS}s / 60 minutes)"
            )

        # Now download
        info = ydl.extract_info(url, download=True)

        filepath = None
        if "requested_downloads" in info and info["requested_downloads"]:
            filepath = info["requested_downloads"][0].get("filepath")
        if not filepath:
            # Fallback: look for the file in output_dir
            for f in os.listdir(output_dir):
                if f.startswith("source."):
                    filepath = os.path.join(output_dir, f)
                    break

        if not filepath or not os.path.exists(filepath):
            raise RuntimeError("Download completed but output file not found")

        return {
            "title": info.get("title", "Unknown"),
            "duration": float(info.get("duration", 0)),
            "filepath": filepath,
            "width": int(info.get("width", 0)),
            "height": int(info.get("height", 0)),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_youtube_service.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/youtube.py tests/test_youtube_service.py
git commit -m "feat: add YouTube download service with yt-dlp"
```

---

## Task 5: OpenAI Clip Analyzer Service

**Files:**
- Create: `app/services/clip_analyzer.py`
- Create: `tests/test_clip_analyzer.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_clip_analyzer.py
import json
from unittest.mock import patch, MagicMock

from app.services.clip_analyzer import analyze_transcript, format_transcript


class TestFormatTranscript:
    def test_formats_words_with_timestamps(self):
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]
        result = format_transcript(words)
        assert "[0:00]" in result
        assert "Hello" in result
        assert "world" in result

    def test_empty_words(self):
        result = format_transcript([])
        assert result == ""


class TestAnalyzeTranscript:
    @patch("app.services.clip_analyzer.OpenAI")
    def test_returns_clips(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "clips": [
                {
                    "start_time": 10.0,
                    "end_time": 55.0,
                    "virality_score": 85,
                    "hook_text": "You won't believe this",
                    "reasoning": "Strong hook"
                }
            ]
        })
        mock_client.chat.completions.create.return_value = mock_response

        words = [{"word": "test", "start": 0.0, "end": 1.0}]
        result = analyze_transcript(words, video_duration=120.0)

        assert len(result) == 1
        assert result[0]["virality_score"] == 85
        assert result[0]["start_time"] == 10.0
        assert result[0]["end_time"] == 55.0

    @patch("app.services.clip_analyzer.OpenAI")
    def test_filters_out_of_bounds_clips(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "clips": [
                {"start_time": 10.0, "end_time": 55.0, "virality_score": 85,
                 "hook_text": "Good clip", "reasoning": "ok"},
                {"start_time": 100.0, "end_time": 200.0, "virality_score": 90,
                 "hook_text": "Bad clip", "reasoning": "out of bounds"},
            ]
        })
        mock_client.chat.completions.create.return_value = mock_response

        words = [{"word": "test", "start": 0.0, "end": 1.0}]
        result = analyze_transcript(words, video_duration=60.0)

        assert len(result) == 1
        assert result[0]["hook_text"] == "Good clip"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_clip_analyzer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the service**

```python
# app/services/clip_analyzer.py
import json

from openai import OpenAI

from app.config import settings

SYSTEM_PROMPT = """You are a viral content analyst specializing in short-form video for TikTok, Instagram Reels, and YouTube Shorts. Given a transcript with word-level timestamps from a video, identify the best clips between 30-90 seconds long.

For each clip:
- It must have a strong hook in the first 3 seconds that makes viewers stop scrolling
- It must contain a complete thought or story arc — no mid-sentence cuts
- It should end cleanly, ideally on a punchline, key insight, or emotional peak
- Score it 1-100 on virality potential based on: hook strength, emotional engagement, shareability, and completeness

Return JSON: { "clips": [{ "start_time": float, "end_time": float, "virality_score": int, "hook_text": "first sentence of the clip", "reasoning": "why this clip works" }] }

Order clips by virality_score descending. Aim for 5-15 clips depending on video length."""


def format_transcript(words: list[dict]) -> str:
    """Format word-level timestamps into readable transcript text."""
    if not words:
        return ""

    lines = []
    current_line_start = words[0]["start"]
    current_words = []

    for i, w in enumerate(words):
        current_words.append(w["word"])
        # Start a new line every ~15 words for readability
        if len(current_words) >= 15:
            minutes = int(current_line_start // 60)
            seconds = int(current_line_start % 60)
            timestamp = f"[{minutes}:{seconds:02d}]"
            lines.append(f"{timestamp} {' '.join(current_words)}")
            current_words = []
            if i + 1 < len(words):
                current_line_start = words[i + 1]["start"]

    # Remaining words
    if current_words:
        minutes = int(current_line_start // 60)
        seconds = int(current_line_start % 60)
        timestamp = f"[{minutes}:{seconds:02d}]"
        lines.append(f"{timestamp} {' '.join(current_words)}")

    return "\n".join(lines)


def _chunk_words(words: list[dict], chunk_duration: float = 1800.0, overlap: float = 120.0) -> list[list[dict]]:
    """Split word list into time-based chunks with overlap."""
    if not words:
        return []

    total_duration = words[-1]["end"]
    if total_duration <= chunk_duration:
        return [words]

    chunks = []
    chunk_start = 0.0
    while chunk_start < total_duration:
        chunk_end = chunk_start + chunk_duration
        chunk = [w for w in words if w["start"] >= chunk_start and w["end"] <= chunk_end]
        if chunk:
            chunks.append(chunk)
        chunk_start += chunk_duration - overlap

    return chunks


def _deduplicate_clips(clips: list[dict]) -> list[dict]:
    """Remove overlapping clips, keeping highest scored."""
    clips.sort(key=lambda c: c["virality_score"], reverse=True)
    result = []
    for clip in clips:
        overlaps = False
        for existing in result:
            overlap_start = max(clip["start_time"], existing["start_time"])
            overlap_end = min(clip["end_time"], existing["end_time"])
            if overlap_end > overlap_start:
                overlap_duration = overlap_end - overlap_start
                clip_duration = clip["end_time"] - clip["start_time"]
                if overlap_duration > clip_duration * 0.5:
                    overlaps = True
                    break
        if not overlaps:
            result.append(clip)
    return result


def analyze_transcript(words: list[dict], video_duration: float) -> list[dict]:
    """Send transcript to OpenAI GPT-4o, return list of clip suggestions.

    Each clip: { start_time, end_time, virality_score, hook_text, reasoning }
    """
    client = OpenAI(api_key=settings.openai_api_key)

    chunks = _chunk_words(words)
    all_clips = []

    for chunk in chunks:
        transcript_text = format_transcript(chunk)
        if not transcript_text:
            continue

        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"]
        user_msg = f"Video duration: {video_duration:.1f}s. This transcript covers {chunk_start:.1f}s to {chunk_end:.1f}s.\n\n{transcript_text}"

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4096,
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        clips = data.get("clips", [])
        all_clips.extend(clips)

    # Validate: filter clips outside video bounds
    valid_clips = []
    for clip in all_clips:
        start = clip.get("start_time", 0)
        end = clip.get("end_time", 0)
        if 0 <= start < end <= video_duration and 30 <= (end - start) <= 90:
            valid_clips.append(clip)

    # Deduplicate overlapping clips from chunk boundaries
    if len(chunks) > 1:
        valid_clips = _deduplicate_clips(valid_clips)

    # Sort by virality score descending
    valid_clips.sort(key=lambda c: c.get("virality_score", 0), reverse=True)

    return valid_clips
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_clip_analyzer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/clip_analyzer.py tests/test_clip_analyzer.py
git commit -m "feat: add OpenAI clip analyzer service with transcript chunking"
```

---

## Task 6: Face Reframer Service

**Files:**
- Create: `app/services/face_reframer.py`
- Create: `tests/test_face_reframer.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_face_reframer.py
import json
import subprocess
from unittest.mock import patch, MagicMock

from app.services.face_reframer import (
    get_video_dimensions,
    is_landscape,
    smooth_positions,
)


class TestGetVideoDimensions:
    @patch("app.services.face_reframer.subprocess.run")
    def test_returns_dimensions(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"streams":[{"width":1920,"height":1080}]}',
            returncode=0,
        )
        w, h = get_video_dimensions("/fake/path.mp4")
        assert w == 1920
        assert h == 1080


class TestIsLandscape:
    def test_landscape(self):
        assert is_landscape(1920, 1080) is True

    def test_portrait(self):
        assert is_landscape(1080, 1920) is False

    def test_square(self):
        assert is_landscape(1080, 1080) is False


class TestSmoothPositions:
    def test_smooths_positions(self):
        positions = [100, 200, 100, 200, 100]
        smoothed = smooth_positions(positions, window=3)
        # Should reduce variance
        assert max(smoothed) - min(smoothed) < max(positions) - min(positions)

    def test_empty_list(self):
        assert smooth_positions([], window=3) == []

    def test_single_element(self):
        assert smooth_positions([100], window=3) == [100]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_face_reframer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the service**

```python
# app/services/face_reframer.py
import json
import os
import subprocess
import tempfile

import cv2
import mediapipe as mp


def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Get video width and height using FFprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-select_streams", "v:0", video_path,
        ],
        capture_output=True, text=True, timeout=10,
    )
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"])


def is_landscape(width: int, height: int) -> bool:
    """Returns True if video is landscape (wider than tall)."""
    return width > height


def smooth_positions(positions: list[float], window: int = 5) -> list[float]:
    """Apply moving average smoothing to a list of positions."""
    if len(positions) <= 1:
        return positions
    smoothed = []
    for i in range(len(positions)):
        start = max(0, i - window // 2)
        end = min(len(positions), i + window // 2 + 1)
        avg = sum(positions[start:end]) / (end - start)
        smoothed.append(avg)
    return smoothed


def _detect_face_positions(video_path: str, sample_interval: float = 0.5) -> list[dict]:
    """Sample frames and detect face center positions using MediaPipe.

    Returns list of {"time": float, "x": int, "y": int} for each frame with a face.
    """
    face_detection = mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    )

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = int(fps * sample_interval) if fps > 0 else 15
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    positions = []
    frame_idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            time_sec = frame_idx / fps if fps > 0 else 0
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_detection.process(rgb_frame)

            if results.detections:
                # Use the first (most confident) detection
                detection = results.detections[0]
                bbox = detection.location_data.relative_bounding_box
                center_x = int((bbox.xmin + bbox.width / 2) * width)
                center_y = int((bbox.ymin + bbox.height / 2) * height)
                positions.append({"time": time_sec, "x": center_x, "y": center_y})

        frame_idx += 1

    cap.release()
    face_detection.close()
    return positions


def _compute_crop_positions(
    face_positions: list[dict],
    src_width: int,
    src_height: int,
    target_width: int = 1080,
    target_height: int = 1920,
) -> list[float]:
    """Compute smoothed horizontal crop offsets from face positions.

    Returns list of x-offsets (one per face position sample).
    """
    # Compute the crop width needed from source to match 9:16 aspect ratio
    crop_h = src_height
    crop_w = int(crop_h * target_width / target_height)
    crop_w = min(crop_w, src_width)

    if not face_positions:
        # Center crop fallback
        x_offset = (src_width - crop_w) // 2
        return [float(x_offset)]

    raw_offsets = []
    for pos in face_positions:
        x = pos["x"] - crop_w // 2
        x = max(0, min(x, src_width - crop_w))
        raw_offsets.append(float(x))

    return smooth_positions(raw_offsets, window=5)


def reframe_to_vertical(input_path: str, output_path: str) -> bool:
    """Reframe a video to 9:16 vertical using face tracking.

    Returns True if reframing was applied, False if already vertical.
    """
    width, height = get_video_dimensions(input_path)

    if not is_landscape(width, height):
        # Already vertical or square — just scale to 1080x1920
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ],
            capture_output=True, timeout=300,
        )
        return False

    # Landscape — detect faces and compute crop
    face_positions = _detect_face_positions(input_path)

    crop_h = height
    crop_w = int(crop_h * 1080 / 1920)
    crop_w = min(crop_w, width)

    offsets = _compute_crop_positions(face_positions, width, height)

    if len(offsets) == 1:
        # Static crop (no face tracking or only one sample)
        x_off = int(offsets[0])
        crop_filter = f"crop={crop_w}:{crop_h}:{x_off}:0,scale=1080:1920"
    else:
        # Use the average position for a static crop
        # (dynamic per-frame crop would require a more complex filter chain)
        avg_x = int(sum(offsets) / len(offsets))
        avg_x = max(0, min(avg_x, width - crop_w))
        crop_filter = f"crop={crop_w}:{crop_h}:{avg_x}:0,scale=1080:1920"

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", crop_filter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ],
        capture_output=True, timeout=300,
    )

    if not os.path.exists(output_path):
        raise RuntimeError(f"FFmpeg reframe failed — output not created: {output_path}")

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_face_reframer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/face_reframer.py tests/test_face_reframer.py
git commit -m "feat: add face reframer service with MediaPipe tracking"
```

---

## Task 7: Clip Extraction Celery Task

**Files:**
- Create: `app/clip_worker.py`

- [ ] **Step 1: Create the worker file**

```python
# app/clip_worker.py
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction, ExtractionStatus
from app.services.credits import refund_credit
from app.services.youtube import download_video
from app.services.transcription import transcribe_audio
from app.services.clip_analyzer import analyze_transcript
from app.services.face_reframer import reframe_to_vertical
from app.worker import celery_app

engine = create_engine(settings.database_url)
ClipWorkerSession = sessionmaker(bind=engine)


def _extract_clip_segment(source_path: str, start: float, end: float, output_path: str) -> None:
    """Extract a segment from video using FFmpeg."""
    import subprocess
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", source_path,
            "-t", str(end - start),
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ],
        capture_output=True, timeout=300,
    )
    if not os.path.exists(output_path):
        raise RuntimeError(f"FFmpeg clip extraction failed: {output_path}")


def _get_transcript_for_range(words: list[dict], start: float, end: float) -> str:
    """Extract transcript text for a time range."""
    clip_words = [w["word"] for w in words if w["start"] >= start and w["end"] <= end]
    return " ".join(clip_words)


@celery_app.task(name="extract_clips", bind=True, max_retries=3)
def extract_clips_task(self, extraction_id: str):
    db = ClipWorkerSession()
    try:
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if not extraction:
            return

        # Stage 1: Download
        extraction.status = ExtractionStatus.downloading
        db.commit()

        download_dir = os.path.join(settings.storage_dir, "downloads", extraction_id)
        os.makedirs(download_dir, exist_ok=True)

        meta = download_video(extraction.youtube_url, download_dir)
        extraction.video_title = meta["title"]
        extraction.video_duration = meta["duration"]
        extraction.source_video_key = f"downloads/{extraction_id}/{os.path.basename(meta['filepath'])}"
        db.commit()

        source_path = meta["filepath"]

        # Stage 2: Transcribe
        extraction.status = ExtractionStatus.transcribing
        db.commit()

        words = transcribe_audio(source_path)
        if not words:
            raise ValueError("No speech detected in video — cannot extract clips")

        # Stage 3: Analyze
        extraction.status = ExtractionStatus.analyzing
        db.commit()

        clip_suggestions = analyze_transcript(words, video_duration=meta["duration"])
        if not clip_suggestions:
            raise ValueError("OpenAI returned no valid clips for this video")

        # Stage 4: Extract & Reframe
        extraction.status = ExtractionStatus.extracting
        db.commit()

        clips_dir = os.path.join(settings.storage_dir, "clips", extraction_id)
        os.makedirs(clips_dir, exist_ok=True)

        for suggestion in clip_suggestions:
            clip_id = str(uuid.uuid4())
            raw_path = os.path.join(clips_dir, f"{clip_id}_raw.mp4")
            final_path = os.path.join(clips_dir, f"{clip_id}.mp4")

            # Extract segment
            _extract_clip_segment(
                source_path,
                suggestion["start_time"],
                suggestion["end_time"],
                raw_path,
            )

            # Reframe to vertical
            try:
                reframed = reframe_to_vertical(raw_path, final_path)
            except Exception:
                # Reframe failed — use raw clip
                os.rename(raw_path, final_path)
                reframed = False

            # Clean up raw file if reframe produced a separate file
            if os.path.exists(raw_path) and raw_path != final_path:
                os.remove(raw_path)

            storage_key = f"clips/{extraction_id}/{clip_id}.mp4"
            transcript_text = _get_transcript_for_range(
                words, suggestion["start_time"], suggestion["end_time"]
            )

            clip = Clip(
                id=clip_id,
                extraction_id=extraction_id,
                storage_key=storage_key,
                start_time=suggestion["start_time"],
                end_time=suggestion["end_time"],
                duration=suggestion["end_time"] - suggestion["start_time"],
                virality_score=suggestion.get("virality_score", 0),
                hook_text=suggestion.get("hook_text", ""),
                transcript_text=transcript_text,
                reframed=reframed,
            )
            db.add(clip)

        # Stage 5: Complete
        extraction.status = ExtractionStatus.completed
        extraction.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        db.rollback()
        extraction = db.query(ClipExtraction).filter(
            ClipExtraction.id == extraction_id
        ).first()
        if not extraction:
            raise

        if self.request.retries < self.max_retries:
            extraction.status = ExtractionStatus.pending
            extraction.error_message = f"Retry {self.request.retries + 1}: {str(e)[:500]}"
            db.commit()
            raise self.retry(exc=e)
        else:
            extraction.status = ExtractionStatus.failed
            extraction.error_message = str(e)[:1000]
            extraction.completed_at = datetime.now(timezone.utc)
            db.flush()
            refund_credit(db, extraction.user_id, job_id=None, commit=False)
            db.commit()
    finally:
        db.close()
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('app/clip_worker.py').read()); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add app/clip_worker.py
git commit -m "feat: add clip extraction Celery task with full pipeline"
```

---

## Task 8: Clip Routes — Tests

**Files:**
- Create: `tests/test_clip_routes.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_clip_routes.py
from unittest.mock import patch

from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction, ExtractionStatus
from app.models.user import User
from app.services.auth import create_access_token


def _create_user(db, credits=10):
    user = User(email="test@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


class TestExtractClips:
    @patch("app.routes.clips._dispatch_extraction")
    def test_create_extraction(self, mock_dispatch, client, db):
        user = _create_user(db)
        resp = client.post(
            "/clips/extract",
            json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert "youtube.com" in data["youtube_url"]
        mock_dispatch.assert_called_once()

    def test_invalid_url(self, client, db):
        user = _create_user(db)
        resp = client.post(
            "/clips/extract",
            json={"youtube_url": "https://vimeo.com/12345"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 422  # Pydantic validation

    @patch("app.routes.clips._dispatch_extraction")
    def test_insufficient_credits(self, mock_dispatch, client, db):
        user = _create_user(db, credits=0)
        resp = client.post(
            "/clips/extract",
            json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 402
        mock_dispatch.assert_not_called()


class TestGetExtraction:
    def test_get_extraction_with_clips(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id,
            youtube_url="https://youtube.com/watch?v=abc",
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.flush()
        clip = Clip(
            extraction_id=extraction.id,
            storage_key="clips/test/clip1.mp4",
            start_time=10.0,
            end_time=55.0,
            duration=45.0,
            virality_score=85,
            hook_text="Amazing hook",
            transcript_text="Full transcript here",
            reframed=True,
        )
        db.add(clip)
        db.commit()
        db.refresh(extraction)

        resp = client.get(
            f"/clips/{extraction.id}",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert len(data["clips"]) == 1
        assert data["clips"][0]["virality_score"] == 85

    def test_get_nonexistent(self, client, db):
        user = _create_user(db)
        resp = client.get(
            "/clips/nonexistent-id",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 404

    def test_cannot_see_other_users_extraction(self, client, db):
        user1 = _create_user(db)
        user2 = User(email="other@example.com", password_hash="hashed", credits_remaining=10)
        db.add(user2)
        db.commit()
        db.refresh(user2)

        extraction = ClipExtraction(
            user_id=user2.id,
            youtube_url="https://youtube.com/watch?v=abc",
        )
        db.add(extraction)
        db.commit()
        db.refresh(extraction)

        resp = client.get(
            f"/clips/{extraction.id}",
            headers=_auth_header(user1.id),
        )
        assert resp.status_code == 404


class TestListExtractions:
    def test_list_empty(self, client, db):
        user = _create_user(db)
        resp = client.get("/clips", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["extractions"] == []

    def test_list_with_items(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id,
            youtube_url="https://youtube.com/watch?v=abc",
        )
        db.add(extraction)
        db.commit()

        resp = client.get("/clips", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert len(resp.json()["extractions"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_clip_routes.py -v`
Expected: FAIL

- [ ] **Step 3: Commit**

```bash
git add tests/test_clip_routes.py
git commit -m "test: add clip route tests (red)"
```

---

## Task 9: Clip Routes — Implementation

**Files:**
- Create: `app/routes/clips.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create the routes file**

```python
# app/routes/clips.py
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.clip_extraction import ClipExtraction, ExtractionStatus
from app.models.user import User
from app.schemas.clip import (
    ClipResponse,
    ExtractClipsRequest,
    ExtractionListResponse,
    ExtractionResponse,
    ExtractionSummaryResponse,
)
from app.services.credits import deduct_credit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clips", tags=["clips"])


def _is_celery_available() -> bool:
    try:
        from redis import Redis
        from app.config import settings
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


def _process_extraction_inline(extraction_id: str) -> None:
    """Process extraction synchronously (dev mode, no Celery)."""
    import os
    import uuid
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.models.clip import Clip
    from app.services.youtube import download_video
    from app.services.transcription import transcribe_audio
    from app.services.clip_analyzer import analyze_transcript
    from app.services.face_reframer import reframe_to_vertical
    from app.services.credits import refund_credit

    engine = create_engine(settings.database_url)
    LocalSession = sessionmaker(bind=engine)
    db = LocalSession()
    try:
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if not extraction:
            return

        # Stage 1: Download
        extraction.status = ExtractionStatus.downloading
        db.commit()
        download_dir = os.path.join(settings.storage_dir, "downloads", extraction_id)
        os.makedirs(download_dir, exist_ok=True)
        meta = download_video(extraction.youtube_url, download_dir)
        extraction.video_title = meta["title"]
        extraction.video_duration = meta["duration"]
        extraction.source_video_key = f"downloads/{extraction_id}/{os.path.basename(meta['filepath'])}"
        db.commit()
        source_path = meta["filepath"]

        # Stage 2: Transcribe
        extraction.status = ExtractionStatus.transcribing
        db.commit()
        words = transcribe_audio(source_path)
        if not words:
            raise ValueError("No speech detected in video")

        # Stage 3: Analyze
        extraction.status = ExtractionStatus.analyzing
        db.commit()
        clip_suggestions = analyze_transcript(words, video_duration=meta["duration"])
        if not clip_suggestions:
            raise ValueError("No valid clips found for this video")

        # Stage 4: Extract & Reframe
        extraction.status = ExtractionStatus.extracting
        db.commit()
        clips_dir = os.path.join(settings.storage_dir, "clips", extraction_id)
        os.makedirs(clips_dir, exist_ok=True)

        import subprocess
        for suggestion in clip_suggestions:
            clip_id = str(uuid.uuid4())
            raw_path = os.path.join(clips_dir, f"{clip_id}_raw.mp4")
            final_path = os.path.join(clips_dir, f"{clip_id}.mp4")

            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(suggestion["start_time"]),
                 "-i", source_path, "-t", str(suggestion["end_time"] - suggestion["start_time"]),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                 "-c:a", "aac", "-b:a", "128k", raw_path],
                capture_output=True, timeout=300,
            )

            try:
                reframed = reframe_to_vertical(raw_path, final_path)
            except Exception:
                os.rename(raw_path, final_path)
                reframed = False

            if os.path.exists(raw_path) and raw_path != final_path:
                os.remove(raw_path)

            clip_words = [w["word"] for w in words
                          if w["start"] >= suggestion["start_time"]
                          and w["end"] <= suggestion["end_time"]]

            clip = Clip(
                id=clip_id,
                extraction_id=extraction_id,
                storage_key=f"clips/{extraction_id}/{clip_id}.mp4",
                start_time=suggestion["start_time"],
                end_time=suggestion["end_time"],
                duration=suggestion["end_time"] - suggestion["start_time"],
                virality_score=suggestion.get("virality_score", 0),
                hook_text=suggestion.get("hook_text", ""),
                transcript_text=" ".join(clip_words),
                reframed=reframed,
            )
            db.add(clip)

        extraction.status = ExtractionStatus.completed
        extraction.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        db.rollback()
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if extraction:
            extraction.status = ExtractionStatus.failed
            extraction.error_message = str(e)[:1000]
            extraction.completed_at = datetime.now(timezone.utc)
            db.flush()
            refund_credit(db, extraction.user_id, job_id=None, commit=False)
            db.commit()
        logger.exception("Inline extraction failed for %s", extraction_id)
    finally:
        db.close()


def _dispatch_extraction(extraction_id: str) -> None:
    if _is_celery_available():
        from app.clip_worker import extract_clips_task
        extract_clips_task.delay(extraction_id)
    else:
        logger.info("Celery unavailable, processing extraction %s inline", extraction_id)
        _process_extraction_inline(extraction_id)


def _clip_to_response(clip) -> ClipResponse:
    return ClipResponse(
        id=clip.id,
        storage_key=clip.storage_key,
        start_time=clip.start_time,
        end_time=clip.end_time,
        duration=clip.duration,
        virality_score=clip.virality_score,
        hook_text=clip.hook_text,
        transcript_text=clip.transcript_text,
        reframed=clip.reframed,
        preview_url=f"/storage/{clip.storage_key}",
        created_at=clip.created_at.isoformat(),
    )


def _extraction_to_response(extraction, include_clips=True) -> ExtractionResponse:
    clips = []
    if include_clips and extraction.clips:
        clips = sorted(
            [_clip_to_response(c) for c in extraction.clips],
            key=lambda c: c.virality_score,
            reverse=True,
        )
    return ExtractionResponse(
        id=extraction.id,
        status=extraction.status.value,
        youtube_url=extraction.youtube_url,
        video_title=extraction.video_title,
        video_duration=extraction.video_duration,
        error_message=extraction.error_message,
        created_at=extraction.created_at.isoformat(),
        completed_at=extraction.completed_at.isoformat() if extraction.completed_at else None,
        clips=clips,
    )


@router.post("/extract", response_model=ExtractionResponse, status_code=status.HTTP_201_CREATED)
def extract_clips(
    body: ExtractClipsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extraction = ClipExtraction(
        user_id=user.id,
        youtube_url=body.youtube_url,
    )
    db.add(extraction)
    db.flush()

    if not deduct_credit(db, user.id, job_id=None, commit=False):
        db.rollback()
        raise HTTPException(status_code=402, detail="Insufficient credits")

    db.commit()
    db.refresh(extraction)

    _dispatch_extraction(str(extraction.id))

    return _extraction_to_response(extraction, include_clips=False)


@router.get("/{extraction_id}", response_model=ExtractionResponse)
def get_extraction(
    extraction_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extraction = (
        db.query(ClipExtraction)
        .filter(ClipExtraction.id == extraction_id, ClipExtraction.user_id == user.id)
        .first()
    )
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return _extraction_to_response(extraction)


@router.get("", response_model=ExtractionListResponse)
def list_extractions(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(ClipExtraction)
        .filter(ClipExtraction.user_id == user.id)
        .order_by(ClipExtraction.created_at.desc())
    )
    if cursor:
        cursor_ext = db.query(ClipExtraction).filter(ClipExtraction.id == cursor).first()
        if cursor_ext:
            query = query.filter(ClipExtraction.created_at < cursor_ext.created_at)

    extractions = query.limit(limit + 1).all()
    next_cursor = str(extractions[-1].id) if len(extractions) > limit else None

    return ExtractionListResponse(
        extractions=[
            ExtractionSummaryResponse(
                id=e.id,
                status=e.status.value,
                youtube_url=e.youtube_url,
                video_title=e.video_title,
                created_at=e.created_at.isoformat(),
            )
            for e in extractions[:limit]
        ],
        next_cursor=next_cursor,
    )
```

- [ ] **Step 2: Register router in `app/main.py`**

Add import and include_router:
```python
from app.routes.clips import router as clips_router
# ...
app.include_router(clips_router)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_clip_routes.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add app/routes/clips.py app/main.py
git commit -m "feat: add clip extraction routes with inline fallback"
```

---

## Task 10: Final Integration Test

**Files:** None new — verification only.

- [ ] **Step 1: Run all tests**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Start server and test manually**

Run: `python -m uvicorn app.main:app --reload --port 8000`

Manual test:
1. Login to get a token
2. `POST /clips/extract` with a short YouTube URL (pick a <5min video)
3. Poll `GET /clips/{id}` — watch status progress through stages
4. When completed, verify clips array has entries with virality scores
5. Use a clip's `storage_key` as `source_video_key` in `POST /jobs/batch` to confirm integration

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address issues found during integration testing"
```
