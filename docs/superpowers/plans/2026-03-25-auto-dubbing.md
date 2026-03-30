# Auto-Dubbing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone dubbing job type that takes a source video and produces lip-synced dubbed versions in French, Spanish, and Hebrew using ElevenLabs Dubbing API + Sync Labs lip-sync API.

**Architecture:** New `DubbingJob` / `DubbingOutput` models with a Celery worker that fans out one sub-task per language. Each sub-task calls ElevenLabs for audio dubbing, then Sync Labs for visual lip-sync, and finalizes independently. The "last one out" pattern marks the parent job complete.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Celery, httpx, ElevenLabs API, Sync Labs API, FFmpeg

**Spec:** `docs/superpowers/specs/2026-03-25-auto-dubbing-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/models/dubbing.py` | Create | `DubbingJob` + `DubbingOutput` SQLAlchemy models |
| `app/models/__init__.py` | Modify | Register new models |
| `app/schemas/dubbing.py` | Create | Pydantic request/response schemas |
| `app/services/elevenlabs.py` | Create | ElevenLabs Dubbing API client |
| `app/services/synclabs.py` | Create | Sync Labs lip-sync API client |
| `app/routes/dubbing.py` | Create | REST endpoints for dubbing jobs |
| `app/dubbing_worker.py` | Create | Celery tasks for dubbing pipeline |
| `app/config.py` | Modify | Add API key settings |
| `app/main.py` | Modify | Register dubbing router |
| `app/models/user.py` | Modify | Add `dubbing_jobs` relationship |
| `migrations/versions/xxx_add_dubbing_tables.py` | Create (auto) | Alembic migration |
| `tests/test_dubbing_models.py` | Create | Model unit tests |
| `tests/test_dubbing_routes.py` | Create | Route integration tests |
| `tests/test_elevenlabs.py` | Create | ElevenLabs service tests |
| `tests/test_synclabs.py` | Create | Sync Labs service tests |

---

### Task 1: Data Models

**Files:**
- Create: `app/models/dubbing.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/user.py`
- Test: `tests/test_dubbing_models.py`

- [ ] **Step 1: Write the model test**

```python
# tests/test_dubbing_models.py
from app.models.dubbing import DubbingJob, DubbingOutput, DubbingJobStatus, DubbingOutputStatus
from app.models.user import User


def _create_user(db, credits=10):
    user = User(email="dub@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestDubbingModels:
    def test_create_dubbing_job(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr", "es"],
            credits_charged=2,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.id is not None
        assert job.status == DubbingJobStatus.pending
        assert job.languages == ["fr", "es"]
        assert job.credits_charged == 2

    def test_create_dubbing_output(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr"],
            credits_charged=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        output = DubbingOutput(
            dubbing_job_id=job.id,
            language="fr",
        )
        db.add(output)
        db.commit()
        db.refresh(output)
        assert output.id is not None
        assert output.status == DubbingOutputStatus.pending
        assert output.dubbing_job_id == job.id

    def test_job_outputs_relationship(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr", "es"],
            credits_charged=2,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        for lang in ["fr", "es"]:
            db.add(DubbingOutput(dubbing_job_id=job.id, language=lang))
        db.commit()
        db.refresh(job)
        assert len(job.outputs) == 2

    def test_user_dubbing_jobs_relationship(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["he"],
            credits_charged=1,
        )
        db.add(job)
        db.commit()
        db.refresh(user)
        assert len(user.dubbing_jobs) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dubbing_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.dubbing'`

- [ ] **Step 3: Create the models**

```python
# app/models/dubbing.py
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class DubbingJobStatus(str, enum.Enum):
    pending = "pending"
    downloading = "downloading"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class DubbingOutputStatus(str, enum.Enum):
    pending = "pending"
    dubbing = "dubbing"
    lip_syncing = "lip_syncing"
    completed = "completed"
    failed = "failed"


class DubbingJob(Base):
    __tablename__ = "dubbing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_video_key: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    languages: Mapped[list] = mapped_column(JSON)
    status: Mapped[DubbingJobStatus] = mapped_column(
        Enum(DubbingJobStatus), default=DubbingJobStatus.pending
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_charged: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="dubbing_jobs")
    outputs: Mapped[list["DubbingOutput"]] = relationship(
        back_populates="dubbing_job", cascade="all, delete-orphan"
    )


class DubbingOutput(Base):
    __tablename__ = "dubbing_outputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    dubbing_job_id: Mapped[str] = mapped_column(ForeignKey("dubbing_jobs.id"))
    language: Mapped[str] = mapped_column(String(10))
    elevenlabs_dubbing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dubbed_audio_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synclabs_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_video_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[DubbingOutputStatus] = mapped_column(
        Enum(DubbingOutputStatus), default=DubbingOutputStatus.pending
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dubbing_job: Mapped["DubbingJob"] = relationship(back_populates="outputs")
```

- [ ] **Step 4: Register models in `__init__.py` and add User relationship**

Add to `app/models/__init__.py`:
```python
from app.models.dubbing import DubbingJob, DubbingOutput, DubbingJobStatus, DubbingOutputStatus  # noqa: F401
```

Add to `app/models/user.py` (after existing relationships):
```python
dubbing_jobs: Mapped[list["DubbingJob"]] = relationship(back_populates="user")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dubbing_models.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/models/dubbing.py app/models/__init__.py app/models/user.py tests/test_dubbing_models.py
git commit -m "feat: add DubbingJob and DubbingOutput models"
```

---

### Task 2: Config + Alembic Migration

**Files:**
- Modify: `app/config.py`
- Create: `migrations/versions/xxx_add_dubbing_tables.py` (auto-generated)

- [ ] **Step 1: Add API key settings to config**

Add to `app/config.py` Settings class (after `openai_model`):
```python
elevenlabs_api_key: str = ""
synclabs_api_key: str = ""
```

- [ ] **Step 2: Generate Alembic migration**

Run: `alembic revision --autogenerate -m "add dubbing_jobs and dubbing_outputs tables"`

- [ ] **Step 3: Review the generated migration**

Open the new migration file and verify it creates both tables with all columns and the FK from `dubbing_outputs.dubbing_job_id` → `dubbing_jobs.id`.

- [ ] **Step 4: Apply migration**

Run: `alembic upgrade head`

- [ ] **Step 5: Commit**

```bash
git add app/config.py migrations/versions/
git commit -m "feat: add dubbing config keys and Alembic migration"
```

---

### Task 3: Pydantic Schemas

**Files:**
- Create: `app/schemas/dubbing.py`

- [ ] **Step 1: Create the schemas**

```python
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
    languages: list[str]
    credits_charged: int
    created_at: str

    model_config = {"from_attributes": True}


class DubbingJobListResponse(BaseModel):
    jobs: list[DubbingJobSummaryResponse]
    next_cursor: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add app/schemas/dubbing.py
git commit -m "feat: add dubbing Pydantic schemas"
```

---

### Task 4: ElevenLabs Service

**Files:**
- Create: `app/services/elevenlabs.py`
- Test: `tests/test_elevenlabs.py`

- [ ] **Step 1: Write the service tests**

```python
# tests/test_elevenlabs.py
import json
from unittest.mock import patch, MagicMock
import httpx
import pytest

from app.services.elevenlabs import create_dubbing, poll_dubbing, download_dubbed_audio


class TestCreateDubbing:
    @patch("app.services.elevenlabs.httpx.post")
    def test_create_dubbing_returns_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"dubbing_id": "dub_123"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = create_dubbing("/tmp/video.mp4", "fr")
        assert result == "dub_123"
        mock_post.assert_called_once()

    @patch("app.services.elevenlabs.httpx.post")
    def test_create_dubbing_raises_on_error(self, mock_post):
        mock_post.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=MagicMock(status_code=400)
        )
        with pytest.raises(httpx.HTTPStatusError):
            create_dubbing("/tmp/video.mp4", "fr")


class TestPollDubbing:
    @patch("app.services.elevenlabs.httpx.get")
    def test_poll_returns_status(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "dubbed"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = poll_dubbing("dub_123")
        assert result == "dubbed"


class TestDownloadDubbedAudio:
    @patch("app.services.elevenlabs.subprocess.run")
    @patch("app.services.elevenlabs.httpx.get")
    def test_download_and_extract_audio(self, mock_get, mock_ffmpeg):
        mock_resp = MagicMock()
        mock_resp.content = b"fake-video-data"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        mock_ffmpeg.return_value = MagicMock(returncode=0)

        download_dubbed_audio("dub_123", "fr", "/tmp/output.mp3")
        mock_get.assert_called_once()
        mock_ffmpeg.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_elevenlabs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.elevenlabs'`

- [ ] **Step 3: Implement the service**

```python
# app/services/elevenlabs.py
import logging
import os
import subprocess
import tempfile

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io/v1"


def _headers() -> dict:
    return {"xi-api-key": settings.elevenlabs_api_key}


def create_dubbing(video_path: str, target_lang: str) -> str:
    """Upload video to ElevenLabs Dubbing API, return dubbing_id."""
    logger.info("Creating ElevenLabs dubbing for %s -> %s", os.path.basename(video_path), target_lang)
    with open(video_path, "rb") as f:
        response = httpx.post(
            f"{BASE_URL}/dubbing",
            headers=_headers(),
            files={"file": (os.path.basename(video_path), f, "video/mp4")},
            data={
                "target_lang": target_lang,
                "mode": "automatic",
                "watermark": "false",
            },
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
    response.raise_for_status()
    dubbing_id = response.json()["dubbing_id"]
    logger.info("ElevenLabs dubbing created: %s", dubbing_id)
    return dubbing_id


def poll_dubbing(dubbing_id: str) -> str:
    """Check dubbing status. Returns status string: 'dubbing', 'dubbed', 'failed', etc."""
    response = httpx.get(
        f"{BASE_URL}/dubbing/{dubbing_id}",
        headers=_headers(),
        timeout=30.0,
    )
    response.raise_for_status()
    status = response.json()["status"]
    logger.info("ElevenLabs dubbing %s status: %s", dubbing_id, status)
    return status


def download_dubbed_audio(dubbing_id: str, target_lang: str, output_path: str) -> None:
    """Download the dubbed video from ElevenLabs, extract audio track via ffmpeg."""
    logger.info("Downloading dubbed content for %s (lang=%s)", dubbing_id, target_lang)
    response = httpx.get(
        f"{BASE_URL}/dubbing/{dubbing_id}/audio/{target_lang}",
        headers=_headers(),
        timeout=httpx.Timeout(300.0, connect=30.0),
    )
    response.raise_for_status()

    # ElevenLabs returns dubbed video — extract audio via ffmpeg
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-vn", "-ac", "1", "-ar", "44100",
             "-b:a", "192k", output_path],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr.decode()[-500:]}")
        logger.info("Dubbed audio saved to %s", output_path)
    finally:
        os.unlink(tmp_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_elevenlabs.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/elevenlabs.py tests/test_elevenlabs.py
git commit -m "feat: add ElevenLabs dubbing service"
```

---

### Task 5: Sync Labs Service

**Files:**
- Create: `app/services/synclabs.py`
- Test: `tests/test_synclabs.py`

- [ ] **Step 1: Write the service tests**

```python
# tests/test_synclabs.py
from unittest.mock import patch, MagicMock
import httpx
import pytest

from app.services.synclabs import create_lipsync, poll_lipsync, get_lipsync_url, download_lipsync


class TestCreateLipsync:
    @patch("app.services.synclabs.httpx.post")
    def test_create_returns_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "sync_456"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = create_lipsync("/tmp/video.mp4", "/tmp/audio.mp3")
        assert result == "sync_456"

    @patch("app.services.synclabs.httpx.post")
    def test_create_raises_on_error(self, mock_post):
        mock_post.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        with pytest.raises(httpx.HTTPStatusError):
            create_lipsync("/tmp/video.mp4", "/tmp/audio.mp3")


class TestPollLipsync:
    @patch("app.services.synclabs.httpx.get")
    def test_poll_returns_status(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "completed", "url": "https://sync.so/output.mp4"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = poll_lipsync("sync_456")
        assert result == "completed"


class TestGetLipsyncUrl:
    @patch("app.services.synclabs.httpx.get")
    def test_returns_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "completed", "url": "https://sync.so/output.mp4"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        url = get_lipsync_url("sync_456")
        assert url == "https://sync.so/output.mp4"


class TestDownloadLipsync:
    @patch("app.services.synclabs.httpx.get")
    def test_download_saves_file(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.content = b"fake-video-data"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        output_path = str(tmp_path / "output.mp4")
        download_lipsync("https://sync.so/output.mp4", output_path)
        with open(output_path, "rb") as f:
            assert f.read() == b"fake-video-data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_synclabs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.synclabs'`

- [ ] **Step 3: Implement the service**

```python
# app/services/synclabs.py
import logging
import os

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.synclabs.so/v2"


def _headers() -> dict:
    return {
        "x-api-key": settings.synclabs_api_key,
        "Content-Type": "application/json",
    }


def create_lipsync(video_path: str, audio_path: str) -> str:
    """Upload video + audio to Sync Labs, return job ID."""
    logger.info("Creating Sync Labs lipsync: video=%s audio=%s",
                os.path.basename(video_path), os.path.basename(audio_path))

    # Upload files as multipart
    with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
        response = httpx.post(
            f"{BASE_URL}/lipsync",
            headers={"x-api-key": settings.synclabs_api_key},
            files={
                "videoFile": (os.path.basename(video_path), vf, "video/mp4"),
                "audioFile": (os.path.basename(audio_path), af, "audio/mpeg"),
            },
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
    response.raise_for_status()
    job_id = response.json()["id"]
    logger.info("Sync Labs lipsync created: %s", job_id)
    return job_id


def poll_lipsync(job_id: str) -> str:
    """Check lipsync status. Returns status string."""
    response = httpx.get(
        f"{BASE_URL}/lipsync/{job_id}",
        headers=_headers(),
        timeout=30.0,
    )
    response.raise_for_status()
    status = response.json()["status"]
    logger.info("Sync Labs lipsync %s status: %s", job_id, status)
    return status


def get_lipsync_url(job_id: str) -> str:
    """Get the download URL for a completed lipsync job."""
    response = httpx.get(
        f"{BASE_URL}/lipsync/{job_id}",
        headers=_headers(),
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["url"]


def download_lipsync(url: str, output_path: str) -> None:
    """Download the lip-synced video from the given URL."""
    logger.info("Downloading lip-synced video to %s", output_path)
    response = httpx.get(url, timeout=httpx.Timeout(300.0, connect=30.0))
    response.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(response.content)
    logger.info("Lip-synced video saved: %.1f MB", os.path.getsize(output_path) / (1024 * 1024))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_synclabs.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/synclabs.py tests/test_synclabs.py
git commit -m "feat: add Sync Labs lip-sync service"
```

---

### Task 6: API Routes

**Files:**
- Create: `app/routes/dubbing.py`
- Modify: `app/main.py`
- Test: `tests/test_dubbing_routes.py`

- [ ] **Step 1: Write the route tests**

```python
# tests/test_dubbing_routes.py
from unittest.mock import patch
from app.models.dubbing import DubbingJob, DubbingOutput, DubbingJobStatus, DubbingOutputStatus
from app.models.user import User
from app.services.auth import create_access_token


def _create_user(db, credits=10):
    user = User(email="dub@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


class TestCreateDubbing:
    @patch("app.routes.dubbing._dispatch_dubbing")
    def test_create_dubbing_job(self, mock_dispatch, client, db):
        user = _create_user(db)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "languages": ["fr", "es"],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert set(data["languages"]) == {"fr", "es"}
        assert data["credits_charged"] == 2
        assert len(data["outputs"]) == 2
        mock_dispatch.assert_called_once()

    @patch("app.routes.dubbing._dispatch_dubbing")
    def test_insufficient_credits(self, mock_dispatch, client, db):
        user = _create_user(db, credits=1)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "languages": ["fr", "es"],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 402
        mock_dispatch.assert_not_called()

    def test_invalid_language(self, client, db):
        user = _create_user(db)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "languages": ["de"],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 422

    def test_empty_languages(self, client, db):
        user = _create_user(db)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "languages": [],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 422


class TestGetDubbing:
    def test_get_job_with_outputs(self, client, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            source_url="https://youtube.com/watch?v=abc",
            languages=["fr"],
            credits_charged=1,
            status=DubbingJobStatus.completed,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        output = DubbingOutput(
            dubbing_job_id=job.id,
            language="fr",
            status=DubbingOutputStatus.completed,
            output_video_key="dubbing/test/fr/output.mp4",
        )
        db.add(output)
        db.commit()

        resp = client.get(f"/dubbing/{job.id}", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert len(data["outputs"]) == 1
        assert data["outputs"][0]["language"] == "fr"

    def test_get_nonexistent(self, client, db):
        user = _create_user(db)
        resp = client.get("/dubbing/nonexistent-id", headers=_auth_header(user.id))
        assert resp.status_code == 404

    def test_cannot_see_other_users_job(self, client, db):
        user1 = _create_user(db)
        user2 = User(email="other@example.com", password_hash="hashed", credits_remaining=10)
        db.add(user2)
        db.commit()
        db.refresh(user2)
        job = DubbingJob(
            user_id=user2.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr"],
            credits_charged=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        resp = client.get(f"/dubbing/{job.id}", headers=_auth_header(user1.id))
        assert resp.status_code == 404


class TestListDubbing:
    def test_list_empty(self, client, db):
        user = _create_user(db)
        resp = client.get("/dubbing", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    def test_list_with_items(self, client, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr", "es"],
            credits_charged=2,
        )
        db.add(job)
        db.commit()
        resp = client.get("/dubbing", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dubbing_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routes.dubbing'`

- [ ] **Step 3: Implement the routes**

```python
# app/routes/dubbing.py
import logging
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.dubbing import DubbingJob, DubbingJobStatus, DubbingOutput, DubbingOutputStatus
from app.models.user import User
from app.schemas.dubbing import (
    CreateDubbingRequest,
    DubbingJobListResponse,
    DubbingJobResponse,
    DubbingJobSummaryResponse,
    DubbingOutputResponse,
)
from app.services.credits import deduct_credit
from app.storage import storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dubbing", tags=["dubbing"])


def _is_celery_available() -> bool:
    """Check if Redis/Celery is available for async processing."""
    try:
        from redis import Redis
        from app.config import settings
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


def _dispatch_dubbing(job_id: str) -> None:
    """Dispatch dubbing to Celery if available, otherwise process in background thread."""
    if _is_celery_available():
        from app.dubbing_worker import process_dubbing_task
        process_dubbing_task.delay(job_id)
    else:
        import threading
        from app.dubbing_worker import _process_dubbing_inline
        logger.info("Celery unavailable, processing dubbing %s in background thread", job_id)
        t = threading.Thread(target=_process_dubbing_inline, args=(job_id,), daemon=True)
        t.start()


def _output_to_response(output: DubbingOutput) -> DubbingOutputResponse:
    download_url = None
    if output.output_video_key:
        download_url = storage.get_download_url(output.output_video_key)
    return DubbingOutputResponse(
        id=str(output.id),
        language=output.language,
        status=output.status.value,
        output_video_key=output.output_video_key,
        download_url=download_url,
        error_message=output.error_message,
        started_at=output.started_at.isoformat() if output.started_at else None,
        completed_at=output.completed_at.isoformat() if output.completed_at else None,
    )


def _job_to_response(job: DubbingJob) -> DubbingJobResponse:
    return DubbingJobResponse(
        id=str(job.id),
        status=job.status.value,
        source_url=job.source_url,
        languages=job.languages,
        credits_charged=job.credits_charged,
        error_message=job.error_message,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        outputs=[_output_to_response(o) for o in job.outputs],
    )


@router.post("", response_model=DubbingJobResponse, status_code=status.HTTP_201_CREATED)
def create_dubbing(
    body: CreateDubbingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    num_languages = len(body.languages)

    # Check credits upfront
    if user.credits_remaining < num_languages:
        raise HTTPException(status_code=402, detail="Insufficient credits")

    job = DubbingJob(
        user_id=user.id,
        source_video_key="",  # set by worker after download
        source_url=body.source_url,
        languages=body.languages,
        credits_charged=num_languages,
    )
    # source_video_key is set by the worker after downloading from source_url
    db.add(job)
    db.flush()

    # Create one output per language
    for lang in body.languages:
        db.add(DubbingOutput(dubbing_job_id=job.id, language=lang))

    # Deduct credits in loop with commit=False
    for _ in range(num_languages):
        if not deduct_credit(db, user.id, commit=False):
            db.rollback()
            raise HTTPException(status_code=402, detail="Insufficient credits")

    db.commit()
    db.refresh(job)

    _dispatch_dubbing(str(job.id))

    return _job_to_response(job)


@router.get("/{job_id}", response_model=DubbingJobResponse)
def get_dubbing(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(DubbingJob).options(
        selectinload(DubbingJob.outputs)
    ).filter(
        DubbingJob.id == job_id,
        DubbingJob.user_id == user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Dubbing job not found")
    return _job_to_response(job)


@router.get("", response_model=DubbingJobListResponse)
def list_dubbing(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(DubbingJob).filter(
        DubbingJob.user_id == user.id,
    ).order_by(DubbingJob.created_at.desc())

    if cursor:
        cursor_job = db.query(DubbingJob).filter(DubbingJob.id == cursor).first()
        if cursor_job:
            query = query.filter(DubbingJob.created_at < cursor_job.created_at)

    jobs = query.limit(limit + 1).all()
    next_cursor = str(jobs[-1].id) if len(jobs) > limit else None

    return DubbingJobListResponse(
        jobs=[
            DubbingJobSummaryResponse(
                id=str(j.id),
                status=j.status.value,
                languages=j.languages,
                credits_charged=j.credits_charged,
                created_at=j.created_at.isoformat(),
            )
            for j in jobs[:limit]
        ],
        next_cursor=next_cursor,
    )
```

- [ ] **Step 4: Register router in `app/main.py`**

Add after existing router imports:
```python
from app.routes.dubbing import router as dubbing_router
```

Add after existing `app.include_router(...)` calls:
```python
app.include_router(dubbing_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_dubbing_routes.py -v`
Expected: All 9 tests PASS

Note: The tests mock `_dispatch_dubbing` so they don't need the worker to exist yet. The worker will be created in Task 7.

- [ ] **Step 6: Commit**

```bash
git add app/routes/dubbing.py app/main.py tests/test_dubbing_routes.py
git commit -m "feat: add dubbing API routes"
```

---

### Task 7: Dubbing Worker

**Files:**
- Create: `app/dubbing_worker.py`

- [ ] **Step 1: Implement the worker**

```python
# app/dubbing_worker.py
import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.dubbing import DubbingJob, DubbingJobStatus, DubbingOutput, DubbingOutputStatus
from app.services.credits import refund_credit
from app.services.elevenlabs import create_dubbing, poll_dubbing, download_dubbed_audio
from app.services.synclabs import create_lipsync, poll_lipsync, get_lipsync_url, download_lipsync
from app.services.youtube import download_video
from app.storage import storage
from app.worker import celery_app

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url)
DubbingWorkerSession = sessionmaker(bind=engine)

POLL_BACKOFF = [5, 10, 20, 40, 60]  # seconds, capped at 60
POLL_TIMEOUT = 1800  # 30 minutes
MAX_DUBBING_DURATION = 1800  # 30 minutes


def _poll_with_backoff(poll_fn, job_id: str, success_status: str, fail_status: str = "failed") -> str:
    """Poll an async API with exponential backoff. Returns status string on success."""
    start = time.time()
    attempt = 0
    while time.time() - start < POLL_TIMEOUT:
        status = poll_fn(job_id)
        if status == success_status:
            return status
        if status == fail_status:
            raise RuntimeError(f"External API job {job_id} failed")
        delay = POLL_BACKOFF[min(attempt, len(POLL_BACKOFF) - 1)]
        time.sleep(delay)
        attempt += 1
    raise TimeoutError(f"Polling timed out after {POLL_TIMEOUT}s for job {job_id}")


def _check_parent_completion(db, dubbing_job_id: str) -> None:
    """If all outputs are terminal, finalize the parent job."""
    outputs = db.query(DubbingOutput).filter(
        DubbingOutput.dubbing_job_id == dubbing_job_id
    ).all()

    terminal = {DubbingOutputStatus.completed, DubbingOutputStatus.failed}
    if not all(o.status in terminal for o in outputs):
        return

    job = db.query(DubbingJob).filter(DubbingJob.id == dubbing_job_id).first()
    if not job or job.status in {DubbingJobStatus.completed, DubbingJobStatus.failed}:
        return

    any_success = any(o.status == DubbingOutputStatus.completed for o in outputs)
    job.status = DubbingJobStatus.completed if any_success else DubbingJobStatus.failed
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Dubbing job %s finalized as %s", dubbing_job_id, job.status.value)


@celery_app.task(name="process_dubbing", bind=True, max_retries=0)
def process_dubbing_task(self, job_id: str):
    """Main dubbing task: download source, then fan out per language."""
    db = DubbingWorkerSession()
    try:
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            return

        job.status = DubbingJobStatus.downloading
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Step 1: Acquire source video
        download_dir = os.path.join(settings.storage_dir, "dubbing", job_id)
        os.makedirs(download_dir, exist_ok=True)
        meta = download_video(job.source_url, download_dir)
        source_key = f"dubbing/{job_id}/{os.path.basename(meta['filepath'])}"
        job.source_video_key = source_key
        db.commit()

        # Validate duration (30 min max for dubbing)
        if meta["duration"] > MAX_DUBBING_DURATION:
            raise ValueError(
                f"Video too long ({meta['duration']:.0f}s, max {MAX_DUBBING_DURATION}s / 30 minutes)"
            )

        # Step 2: Fan out per language
        job.status = DubbingJobStatus.processing
        db.commit()

        outputs = db.query(DubbingOutput).filter(
            DubbingOutput.dubbing_job_id == job_id
        ).all()

        for output in outputs:
            process_dubbing_language_task.delay(job_id, str(output.id))

    except Exception as e:
        db.rollback()
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if job:
            job.status = DubbingJobStatus.failed
            job.error_message = str(e)[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            # Refund all credits since no language processing started
            for _ in range(job.credits_charged):
                refund_credit(db, job.user_id, job_id=None, commit=False)
            db.commit()
        logger.exception("Dubbing job %s failed during setup", job_id)
    finally:
        db.close()


@celery_app.task(name="process_dubbing_language", bind=True, max_retries=3)
def process_dubbing_language_task(self, job_id: str, output_id: str):
    """Process dubbing for a single language: ElevenLabs dub -> Sync Labs lipsync."""
    db = DubbingWorkerSession()
    try:
        output = db.query(DubbingOutput).filter(DubbingOutput.id == output_id).first()
        if not output:
            return

        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            return

        source_path = os.path.join(settings.storage_dir, job.source_video_key)
        lang = output.language
        output_dir = os.path.join(settings.storage_dir, "dubbing", job_id, lang)
        os.makedirs(output_dir, exist_ok=True)

        # Step 2a: ElevenLabs dubbing
        output.status = DubbingOutputStatus.dubbing
        output.started_at = datetime.now(timezone.utc)
        db.commit()

        dubbing_id = create_dubbing(source_path, lang)
        output.elevenlabs_dubbing_id = dubbing_id
        db.commit()

        _poll_with_backoff(poll_dubbing, dubbing_id, success_status="dubbed")

        audio_path = os.path.join(output_dir, "dubbed_audio.mp3")
        download_dubbed_audio(dubbing_id, lang, audio_path)
        output.dubbed_audio_key = f"dubbing/{job_id}/{lang}/dubbed_audio.mp3"
        db.commit()

        # Step 2b: Sync Labs lip-sync
        output.status = DubbingOutputStatus.lip_syncing
        db.commit()

        sync_id = create_lipsync(source_path, audio_path)
        output.synclabs_video_id = sync_id
        db.commit()

        _poll_with_backoff(poll_lipsync, sync_id, success_status="completed")

        download_url = get_lipsync_url(sync_id)
        video_path = os.path.join(output_dir, "output.mp4")
        download_lipsync(download_url, video_path)
        output.output_video_key = f"dubbing/{job_id}/{lang}/output.mp4"
        output.status = DubbingOutputStatus.completed
        output.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("Dubbing output %s (%s) completed", output_id, lang)

    except Exception as e:
        db.rollback()
        output = db.query(DubbingOutput).filter(DubbingOutput.id == output_id).first()
        if not output:
            raise

        if self.request.retries < self.max_retries:
            output.status = DubbingOutputStatus.pending
            output.error_message = f"Retry {self.request.retries + 1}: {str(e)[:500]}"
            db.commit()
            raise self.retry(exc=e)
        else:
            output.status = DubbingOutputStatus.failed
            output.error_message = str(e)[:1000]
            output.completed_at = datetime.now(timezone.utc)
            db.flush()
            # Refund 1 credit for this failed output (atomic with status update)
            job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
            if job:
                refund_credit(db, job.user_id, job_id=None, commit=False)
            db.commit()
            logger.exception("Dubbing output %s (%s) failed permanently", output_id, output.language)
    finally:
        # Check if parent should be finalized
        try:
            _check_parent_completion(db, job_id)
        except Exception:
            logger.exception("Error checking parent completion for job %s", job_id)
        db.close()


def _process_dubbing_inline(job_id: str) -> None:
    """Process dubbing synchronously (dev mode, no Celery). No retries."""
    db = DubbingWorkerSession()
    try:
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            return

        job.status = DubbingJobStatus.downloading
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Step 1: Download
        download_dir = os.path.join(settings.storage_dir, "dubbing", job_id)
        os.makedirs(download_dir, exist_ok=True)
        meta = download_video(job.source_url, download_dir)
        job.source_video_key = f"dubbing/{job_id}/{os.path.basename(meta['filepath'])}"
        db.commit()

        if meta["duration"] > MAX_DUBBING_DURATION:
            raise ValueError(
                f"Video too long ({meta['duration']:.0f}s, max {MAX_DUBBING_DURATION}s / 30 minutes)"
            )

        source_path = os.path.join(settings.storage_dir, job.source_video_key)
        job.status = DubbingJobStatus.processing
        db.commit()

        outputs = db.query(DubbingOutput).filter(
            DubbingOutput.dubbing_job_id == job_id
        ).all()

        # Process each language sequentially in dev mode
        for output in outputs:
            try:
                lang = output.language
                output_dir = os.path.join(settings.storage_dir, "dubbing", job_id, lang)
                os.makedirs(output_dir, exist_ok=True)

                output.status = DubbingOutputStatus.dubbing
                output.started_at = datetime.now(timezone.utc)
                db.commit()

                dubbing_id = create_dubbing(source_path, lang)
                output.elevenlabs_dubbing_id = dubbing_id
                db.commit()

                _poll_with_backoff(poll_dubbing, dubbing_id, success_status="dubbed")

                audio_path = os.path.join(output_dir, "dubbed_audio.mp3")
                download_dubbed_audio(dubbing_id, lang, audio_path)
                output.dubbed_audio_key = f"dubbing/{job_id}/{lang}/dubbed_audio.mp3"
                db.commit()

                output.status = DubbingOutputStatus.lip_syncing
                db.commit()

                sync_id = create_lipsync(source_path, audio_path)
                output.synclabs_video_id = sync_id
                db.commit()

                status, download_url = _poll_with_backoff(
                    poll_lipsync, sync_id, success_status="completed"
                )

                video_path = os.path.join(output_dir, "output.mp4")
                download_lipsync(download_url, video_path)
                output.output_video_key = f"dubbing/{job_id}/{lang}/output.mp4"
                output.status = DubbingOutputStatus.completed
                output.completed_at = datetime.now(timezone.utc)
                db.commit()
                logger.info("Dubbing output %s (%s) completed inline", output.id, lang)

            except Exception as e:
                db.rollback()
                output = db.query(DubbingOutput).filter(DubbingOutput.id == output.id).first()
                if output:
                    output.status = DubbingOutputStatus.failed
                    output.error_message = str(e)[:1000]
                    output.completed_at = datetime.now(timezone.utc)
                    db.flush()
                    refund_credit(db, job.user_id, job_id=None, commit=False)
                    db.commit()
                logger.exception("Inline dubbing failed for output %s", output.id if output else "unknown")

        _check_parent_completion(db, job_id)

    except Exception as e:
        db.rollback()
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if job:
            job.status = DubbingJobStatus.failed
            job.error_message = str(e)[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            for _ in range(job.credits_charged):
                refund_credit(db, job.user_id, job_id=None, commit=False)
            db.commit()
        logger.exception("Inline dubbing job %s failed", job_id)
    finally:
        db.close()
```

- [ ] **Step 2: Register tasks with Celery Beat**

Add to bottom of `app/worker.py` (after existing `import app.analytics_worker`):
```python
import app.dubbing_worker  # noqa: F401, E402 — register dubbing tasks
```

- [ ] **Step 3: Commit**

```bash
git add app/dubbing_worker.py app/worker.py
git commit -m "feat: add dubbing Celery worker with fan-out per language"
```

---

### Task 8: Integration Smoke Test

**Files:**
- No new files — manual verification

- [ ] **Step 1: Verify the app starts**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && python -c "from app.main import app; print('OK')"`
Expected: `OK` — confirms all imports resolve

- [ ] **Step 2: Verify migration is applied**

Run: `alembic current`
Expected: Shows the latest migration head including the dubbing tables

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All existing + new tests pass

- [ ] **Step 4: Commit any fixes if needed**

```bash
git add -A
git commit -m "fix: resolve integration issues from dubbing feature"
```
