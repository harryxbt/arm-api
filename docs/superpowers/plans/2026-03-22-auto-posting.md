# Auto-Posting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scheduled video publishing to TikTok, YouTube, and Instagram Reels, extending the existing cluster models and Celery worker infrastructure.

**Architecture:** Extend `ClusterAccount` with a `credentials` JSON column and `AccountPost` with scheduling/status columns. Three platform uploader services behind a common interface. Celery Beat polls every 60s for due posts and dispatches upload tasks.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Celery Beat, httpx (platform API calls), Pydantic

**Spec:** `docs/superpowers/specs/2026-03-22-auto-posting-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/models/cluster.py` | Modify | Add `credentials` to ClusterAccount, add scheduling columns + `PostStatus` enum to AccountPost |
| `app/models/__init__.py` | Modify | Re-export `PostStatus` |
| `migrations/versions/xxx_add_publishing_columns.py` | Create | Alembic migration for new columns |
| `app/services/uploaders/__init__.py` | Create | `BaseUploader` abstract class + `get_uploader` factory |
| `app/services/uploaders/tiktok.py` | Create | TikTok Content Posting API uploader |
| `app/services/uploaders/youtube.py` | Create | YouTube Data API v3 uploader |
| `app/services/uploaders/instagram.py` | Create | Instagram Graph API Reels uploader |
| `app/schemas/publishing.py` | Create | Pydantic request/response schemas for publishing routes |
| `app/routes/publishing.py` | Create | FastAPI router: credentials, scheduling, post-now |
| `app/main.py` | Modify | Register publishing router |
| `app/publishing_worker.py` | Create | `poll_scheduled_posts` Beat task + `upload_to_platform` Celery task |
| `app/worker.py` | Modify | Add Beat schedule config + import publishing_worker |
| `tests/test_publishing_routes.py` | Create | Route tests for all publishing endpoints |
| `tests/test_uploaders.py` | Create | Unit tests for uploader services |
| `tests/test_publishing_worker.py` | Create | Worker task tests |

---

### Task 1: Extend Models with Publishing Columns

**Files:**
- Modify: `app/models/cluster.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_publishing_models.py`

- [ ] **Step 1: Write failing test for PostStatus enum and new columns**

Create `tests/test_publishing_models.py`:

```python
# tests/test_publishing_models.py
from datetime import datetime, timezone
from app.models.cluster import (
    ClusterAccount, AccountPost, PostStatus, Platform, Cluster,
)


class TestPostStatusEnum:
    def test_values(self):
        assert PostStatus.pending.value == "pending"
        assert PostStatus.uploading.value == "uploading"
        assert PostStatus.posted.value == "posted"
        assert PostStatus.failed.value == "failed"


class TestClusterAccountCredentials:
    def test_credentials_column_exists(self, db):
        cluster = Cluster(name="Test Cluster")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@test",
            credentials={"access_token": "tok123", "open_id": "oid456"},
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        assert account.credentials["access_token"] == "tok123"
        assert account.credentials["open_id"] == "oid456"

    def test_credentials_nullable(self, db):
        cluster = Cluster(name="Test Cluster")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.youtube,
            handle="@nocreds",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        assert account.credentials is None


class TestAccountPostSchedulingColumns:
    def test_scheduled_post_columns(self, db):
        cluster = Cluster(name="Test Cluster")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@test",
        )
        db.add(account)
        db.flush()
        post = AccountPost(
            account_id=account.id,
            video_storage_key="clips/abc/clip1.mp4",
            scheduled_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
            status=PostStatus.pending,
            metadata={"caption": "Test post", "hashtags": ["#viral"]},
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        assert post.status == PostStatus.pending
        assert post.video_storage_key == "clips/abc/clip1.mp4"
        assert post.scheduled_at.year == 2026
        assert post.metadata["caption"] == "Test post"
        assert post.error_message is None
        assert post.platform_url is None
        assert post.job_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_publishing_models.py -v`
Expected: ImportError — `PostStatus` does not exist yet

- [ ] **Step 3: Add PostStatus enum and new columns to models**

Modify `app/models/cluster.py` — add the `PostStatus` enum after the `Platform` enum:

```python
class PostStatus(str, enum.Enum):
    pending = "pending"
    uploading = "uploading"
    posted = "posted"
    failed = "failed"
```

Add `credentials` column to `ClusterAccount`:

```python
    credentials: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

Add import for `JSON` and `Text` at the top:

```python
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, UniqueConstraint, JSON, Text
```

Add new columns to `AccountPost`:

```python
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    video_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PostStatus | None] = mapped_column(Enum(PostStatus), nullable=True)
    platform_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

Update `app/models/__init__.py` to re-export `PostStatus`:

```python
from app.models.cluster import Cluster, ClusterAccount, AccountPost, Platform, PostStatus  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_publishing_models.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/cluster.py app/models/__init__.py tests/test_publishing_models.py
git commit -m "feat: add publishing columns to ClusterAccount and AccountPost"
```

---

### Task 2: Alembic Migration

**Files:**
- Create: `migrations/versions/xxx_add_publishing_columns.py`

- [ ] **Step 1: Generate migration**

Run: `alembic revision --autogenerate -m "add publishing columns to cluster models"`

- [ ] **Step 2: Review the generated migration**

Verify it contains:
- `add_column('cluster_accounts', 'credentials', JSON, nullable=True)`
- `add_column('account_posts', 'job_id', String(36), nullable=True)` with FK
- `add_column('account_posts', 'video_storage_key', String(500), nullable=True)`
- `add_column('account_posts', 'scheduled_at', DateTime(timezone=True), nullable=True)`
- `add_column('account_posts', 'status', Enum('pending','uploading','posted','failed', name='poststatus'), nullable=True)`
- `add_column('account_posts', 'platform_url', String(500), nullable=True)`
- `add_column('account_posts', 'error_message', Text, nullable=True)`
- `add_column('account_posts', 'metadata', JSON, nullable=True)`

Adjust if needed (SQLite does not support adding FK constraints via ALTER TABLE — the FK is declared in the model but won't be enforced at DB level on SQLite, which is fine for dev).

- [ ] **Step 3: Run migration**

Run: `alembic upgrade head`

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/
git commit -m "feat: add publishing columns migration"
```

---

### Task 3: Base Uploader Interface + Factory

**Files:**
- Create: `app/services/uploaders/__init__.py`
- Test: `tests/test_uploaders.py`

- [ ] **Step 1: Write failing test for factory**

Create `tests/test_uploaders.py`:

```python
# tests/test_uploaders.py
import pytest
from app.services.uploaders import BaseUploader, get_uploader


class TestBaseUploader:
    def test_upload_not_implemented(self):
        uploader = BaseUploader()
        with pytest.raises(NotImplementedError):
            uploader.upload("path.mp4", {}, {})

    def test_validate_credentials_not_implemented(self):
        uploader = BaseUploader()
        with pytest.raises(NotImplementedError):
            uploader.validate_credentials({})


class TestGetUploader:
    def test_get_tiktok(self):
        uploader = get_uploader("tiktok")
        assert isinstance(uploader, BaseUploader)

    def test_get_youtube(self):
        uploader = get_uploader("youtube")
        assert isinstance(uploader, BaseUploader)

    def test_get_instagram(self):
        uploader = get_uploader("instagram")
        assert isinstance(uploader, BaseUploader)

    def test_unknown_platform(self):
        with pytest.raises(KeyError):
            get_uploader("facebook")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_uploaders.py -v`
Expected: ImportError — module does not exist

- [ ] **Step 3: Create base uploader and factory**

Create `app/services/uploaders/__init__.py`:

```python
# app/services/uploaders/__init__.py


class BaseUploader:
    def upload(self, video_path: str, metadata: dict, credentials: dict) -> dict:
        """Upload video to platform.

        Returns {"platform_post_id": "...", "platform_url": "..."}
        """
        raise NotImplementedError

    def validate_credentials(self, credentials: dict) -> bool:
        """Check that credentials are still valid."""
        raise NotImplementedError


def get_uploader(platform: str) -> BaseUploader:
    from app.services.uploaders.tiktok import TikTokUploader
    from app.services.uploaders.youtube import YouTubeUploader
    from app.services.uploaders.instagram import InstagramReelsUploader

    uploaders = {
        "tiktok": TikTokUploader,
        "youtube": YouTubeUploader,
        "instagram": InstagramReelsUploader,
    }
    return uploaders[platform]()
```

- [ ] **Step 4: Create stub uploaders (will be implemented in Tasks 4-6)**

Create `app/services/uploaders/tiktok.py`:

```python
# app/services/uploaders/tiktok.py
from app.services.uploaders import BaseUploader


class TikTokUploader(BaseUploader):
    def upload(self, video_path: str, metadata: dict, credentials: dict) -> dict:
        raise NotImplementedError("TikTok upload not yet implemented")

    def validate_credentials(self, credentials: dict) -> bool:
        raise NotImplementedError("TikTok validation not yet implemented")
```

Create `app/services/uploaders/youtube.py`:

```python
# app/services/uploaders/youtube.py
from app.services.uploaders import BaseUploader


class YouTubeUploader(BaseUploader):
    def upload(self, video_path: str, metadata: dict, credentials: dict) -> dict:
        raise NotImplementedError("YouTube upload not yet implemented")

    def validate_credentials(self, credentials: dict) -> bool:
        raise NotImplementedError("YouTube validation not yet implemented")
```

Create `app/services/uploaders/instagram.py`:

```python
# app/services/uploaders/instagram.py
from app.services.uploaders import BaseUploader


class InstagramReelsUploader(BaseUploader):
    def upload(self, video_path: str, metadata: dict, credentials: dict) -> dict:
        raise NotImplementedError("Instagram upload not yet implemented")

    def validate_credentials(self, credentials: dict) -> bool:
        raise NotImplementedError("Instagram validation not yet implemented")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_uploaders.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/uploaders/ tests/test_uploaders.py
git commit -m "feat: add base uploader interface, factory, and platform stubs"
```

---

### Task 4: TikTok Uploader Implementation

**Files:**
- Modify: `app/services/uploaders/tiktok.py`
- Test: `tests/test_uploaders.py` (add TikTok-specific tests)

- [ ] **Step 1: Write failing test for TikTok upload**

Add to `tests/test_uploaders.py`:

```python
from unittest.mock import patch, MagicMock
from app.services.uploaders.tiktok import TikTokUploader


class TestTikTokUploader:
    @patch("app.services.uploaders.tiktok.httpx.Client")
    def test_upload_success(self, mock_client_class, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 1000)

        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        # Mock init upload
        mock_client.post.side_effect = [
            # init upload response
            MagicMock(status_code=200, json=lambda: {
                "data": {"publish_id": "pub123", "upload_url": "https://tiktok.com/upload"}
            }),
            # upload video chunk response
            MagicMock(status_code=200),
        ]
        # Mock publish status check
        mock_client.post.side_effect = None
        mock_client.post.return_value = MagicMock(status_code=200, json=lambda: {
            "data": {"publish_id": "pub123", "upload_url": "https://tiktok.com/upload"}
        })

        uploader = TikTokUploader()
        credentials = {"access_token": "tok123", "open_id": "oid456"}
        metadata = {"caption": "Test video #viral"}
        result = uploader.upload(str(video_file), metadata, credentials)

        assert "platform_post_id" in result

    def test_validate_credentials_missing_keys(self):
        uploader = TikTokUploader()
        assert uploader.validate_credentials({}) is False
        assert uploader.validate_credentials({"access_token": "tok"}) is False

    def test_validate_credentials_valid(self):
        uploader = TikTokUploader()
        assert uploader.validate_credentials({"access_token": "tok", "open_id": "oid"}) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_uploaders.py::TestTikTokUploader -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement TikTok uploader**

Replace `app/services/uploaders/tiktok.py`:

```python
# app/services/uploaders/tiktok.py
import os
import logging

import httpx

from app.services.uploaders import BaseUploader

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


class TikTokUploader(BaseUploader):
    def upload(self, video_path: str, metadata: dict, credentials: dict) -> dict:
        access_token = credentials["access_token"]
        file_size = os.path.getsize(video_path)

        # Build caption with hashtags
        caption = metadata.get("caption", "")
        hashtags = metadata.get("hashtags", [])
        if hashtags:
            caption = caption + " " + " ".join(
                tag if tag.startswith("#") else f"#{tag}" for tag in hashtags
            )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        with httpx.Client(timeout=300) as client:
            # Step 1: Init upload
            init_body = {
                "post_info": {
                    "title": caption[:150],
                    "privacy_level": metadata.get("privacy_level", "SELF_ONLY"),
                    "disable_comment": metadata.get("disable_comment", False),
                    "disable_duet": metadata.get("disable_duet", False),
                    "disable_stitch": metadata.get("disable_stitch", False),
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": file_size,
                    "total_chunk_count": 1,
                },
            }
            init_resp = client.post(
                f"{TIKTOK_API_BASE}/post/publish/video/init/",
                headers=headers,
                json=init_body,
            )
            init_resp.raise_for_status()
            init_data = init_resp.json()["data"]
            publish_id = init_data["publish_id"]
            upload_url = init_data["upload_url"]

            # Step 2: Upload video
            with open(video_path, "rb") as f:
                video_data = f.read()
            upload_headers = {
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            }
            upload_resp = client.put(upload_url, content=video_data, headers=upload_headers)
            upload_resp.raise_for_status()

            logger.info("TikTok upload complete, publish_id=%s", publish_id)
            return {
                "platform_post_id": publish_id,
                "platform_url": f"https://www.tiktok.com/@{credentials.get('open_id', '')}/video/{publish_id}",
            }

    def validate_credentials(self, credentials: dict) -> bool:
        return bool(credentials.get("access_token") and credentials.get("open_id"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_uploaders.py::TestTikTokUploader -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/uploaders/tiktok.py tests/test_uploaders.py
git commit -m "feat: implement TikTok Content Posting API uploader"
```

---

### Task 5: YouTube Uploader Implementation

**Files:**
- Modify: `app/services/uploaders/youtube.py`
- Test: `tests/test_uploaders.py` (add YouTube-specific tests)

- [ ] **Step 1: Write failing test for YouTube upload**

Add to `tests/test_uploaders.py`:

```python
from app.services.uploaders.youtube import YouTubeUploader


class TestYouTubeUploader:
    @patch("app.services.uploaders.youtube.httpx.Client")
    def test_upload_success(self, mock_client_class, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 1000)

        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        # Mock resumable upload init
        mock_client.post.return_value = MagicMock(
            status_code=200,
            headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=abc"},
        )
        # Mock upload chunk
        mock_client.put.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "yt_video_123", "snippet": {"title": "Test"}},
        )

        uploader = YouTubeUploader()
        credentials = {
            "access_token": "ya29.tok",
            "refresh_token": "1//ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        metadata = {
            "title": "Test Video",
            "description": "A test",
            "tags": ["test"],
            "privacy_status": "unlisted",
        }
        result = uploader.upload(str(video_file), metadata, credentials)
        assert result["platform_post_id"] == "yt_video_123"
        assert "youtube.com" in result["platform_url"]

    def test_validate_credentials_missing_keys(self):
        uploader = YouTubeUploader()
        assert uploader.validate_credentials({"access_token": "tok"}) is False

    def test_validate_credentials_valid(self):
        uploader = YouTubeUploader()
        creds = {
            "access_token": "tok",
            "refresh_token": "ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        assert uploader.validate_credentials(creds) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_uploaders.py::TestYouTubeUploader -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement YouTube uploader**

Replace `app/services/uploaders/youtube.py`:

```python
# app/services/uploaders/youtube.py
import json
import logging
import os

import httpx

from app.services.uploaders import BaseUploader

logger = logging.getLogger(__name__)

YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class YouTubeUploader(BaseUploader):
    def upload(self, video_path: str, metadata: dict, credentials: dict) -> dict:
        access_token = credentials["access_token"]
        file_size = os.path.getsize(video_path)

        snippet = {
            "title": metadata.get("title", "Untitled"),
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "categoryId": metadata.get("category_id", "22"),
        }
        status = {
            "privacyStatus": metadata.get("privacy_status", "private"),
        }
        body = json.dumps({"snippet": snippet, "status": status})

        with httpx.Client(timeout=600) as client:
            # Step 1: Init resumable upload
            init_resp = client.post(
                YOUTUBE_UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(file_size),
                },
                content=body,
            )
            init_resp.raise_for_status()
            upload_url = init_resp.headers["Location"]

            # Step 2: Upload video
            with open(video_path, "rb") as f:
                video_data = f.read()
            upload_resp = client.put(
                upload_url,
                content=video_data,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(file_size),
                },
            )
            upload_resp.raise_for_status()
            video_id = upload_resp.json()["id"]

            logger.info("YouTube upload complete, video_id=%s", video_id)
            return {
                "platform_post_id": video_id,
                "platform_url": f"https://www.youtube.com/watch?v={video_id}",
            }

    def refresh_access_token(self, credentials: dict) -> str | None:
        """Attempt to refresh the access token. Returns new token or None."""
        try:
            resp = httpx.post(YOUTUBE_TOKEN_URL, data={
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "refresh_token": credentials["refresh_token"],
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            return resp.json()["access_token"]
        except Exception:
            logger.exception("Failed to refresh YouTube access token")
            return None

    def validate_credentials(self, credentials: dict) -> bool:
        required = {"access_token", "refresh_token", "client_id", "client_secret"}
        return required.issubset(credentials.keys())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_uploaders.py::TestYouTubeUploader -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/uploaders/youtube.py tests/test_uploaders.py
git commit -m "feat: implement YouTube Data API v3 uploader with token refresh"
```

---

### Task 6: Instagram Reels Uploader Implementation

**Files:**
- Modify: `app/services/uploaders/instagram.py`
- Test: `tests/test_uploaders.py` (add Instagram-specific tests)

- [ ] **Step 1: Write failing test for Instagram upload**

Add to `tests/test_uploaders.py`:

```python
from app.services.uploaders.instagram import InstagramReelsUploader


class TestInstagramReelsUploader:
    @patch("app.services.uploaders.instagram.httpx.Client")
    @patch("app.services.uploaders.instagram.time.sleep")
    def test_upload_success(self, mock_sleep, mock_client_class, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 1000)

        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_client.post.side_effect = [
            # Create container
            MagicMock(status_code=200, json=lambda: {"id": "container_123"}),
            # Publish
            MagicMock(status_code=200, json=lambda: {"id": "media_456"}),
        ]
        # Status check (FINISHED)
        mock_client.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status_code": "FINISHED", "id": "container_123"},
        )

        uploader = InstagramReelsUploader()
        credentials = {"access_token": "IGtok", "instagram_user_id": "ig_user_1"}
        metadata = {"caption": "Check this out #reels"}
        result = uploader.upload(str(video_file), metadata, credentials)

        assert result["platform_post_id"] == "media_456"
        assert "instagram.com" in result["platform_url"]

    def test_validate_credentials_missing_keys(self):
        uploader = InstagramReelsUploader()
        assert uploader.validate_credentials({}) is False

    def test_validate_credentials_valid(self):
        uploader = InstagramReelsUploader()
        assert uploader.validate_credentials({"access_token": "tok", "instagram_user_id": "uid"}) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_uploaders.py::TestInstagramReelsUploader -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement Instagram Reels uploader**

Replace `app/services/uploaders/instagram.py`:

```python
# app/services/uploaders/instagram.py
import logging
import time

import httpx

from app.services.uploaders import BaseUploader

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramReelsUploader(BaseUploader):
    def upload(self, video_path: str, metadata: dict, credentials: dict) -> dict:
        access_token = credentials["access_token"]
        ig_user_id = credentials["instagram_user_id"]

        caption = metadata.get("caption", "")
        hashtags = metadata.get("hashtags", [])
        if hashtags:
            caption = caption + " " + " ".join(
                tag if tag.startswith("#") else f"#{tag}" for tag in hashtags
            )

        with httpx.Client(timeout=300) as client:
            # Step 1: Create media container
            # Note: video_url must be a publicly accessible URL.
            # For local files, you need to host the video first or use
            # a signed URL from your storage.
            container_resp = client.post(
                f"{GRAPH_API_BASE}/{ig_user_id}/media",
                params={
                    "media_type": "REELS",
                    "video_url": metadata.get("video_url", ""),
                    "caption": caption[:2200],
                    "share_to_feed": str(metadata.get("share_to_feed", True)).lower(),
                    "access_token": access_token,
                },
            )
            container_resp.raise_for_status()
            container_id = container_resp.json()["id"]

            # Step 2: Poll for processing
            for _ in range(30):
                status_resp = client.get(
                    f"{GRAPH_API_BASE}/{container_id}",
                    params={"fields": "status_code", "access_token": access_token},
                )
                status_resp.raise_for_status()
                status_code = status_resp.json().get("status_code")
                if status_code == "FINISHED":
                    break
                if status_code == "ERROR":
                    raise RuntimeError(f"Instagram processing failed for container {container_id}")
                time.sleep(10)
            else:
                raise TimeoutError(f"Instagram processing timed out for container {container_id}")

            # Step 3: Publish
            publish_resp = client.post(
                f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
                params={
                    "creation_id": container_id,
                    "access_token": access_token,
                },
            )
            publish_resp.raise_for_status()
            media_id = publish_resp.json()["id"]

            logger.info("Instagram Reels upload complete, media_id=%s", media_id)
            return {
                "platform_post_id": media_id,
                "platform_url": f"https://www.instagram.com/reel/{media_id}/",
            }

    def validate_credentials(self, credentials: dict) -> bool:
        return bool(credentials.get("access_token") and credentials.get("instagram_user_id"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_uploaders.py::TestInstagramReelsUploader -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/uploaders/instagram.py tests/test_uploaders.py
git commit -m "feat: implement Instagram Reels uploader via Graph API"
```

---

### Task 7: Pydantic Schemas for Publishing API

**Files:**
- Create: `app/schemas/publishing.py`

- [ ] **Step 1: Write failing test for schemas**

Add to `tests/test_publishing_routes.py` (create file):

```python
# tests/test_publishing_routes.py
import pytest
from pydantic import ValidationError
from app.schemas.publishing import (
    UpdateCredentialsRequest,
    SchedulePostItem,
    SchedulePostsRequest,
    ScheduledPostResponse,
    AccountCredentialsResponse,
)


class TestPublishingSchemas:
    def test_update_credentials_request(self):
        req = UpdateCredentialsRequest(credentials={"access_token": "tok"})
        assert req.credentials["access_token"] == "tok"

    def test_schedule_post_item(self):
        item = SchedulePostItem(
            account_id="acc-1",
            scheduled_at="2026-04-01T12:00:00Z",
            metadata={"caption": "Hello"},
        )
        assert item.account_id == "acc-1"

    def test_schedule_posts_request_with_clip(self):
        req = SchedulePostsRequest(
            clip_id="clip-1",
            posts=[SchedulePostItem(
                account_id="acc-1",
                scheduled_at="2026-04-01T12:00:00Z",
                metadata={},
            )],
        )
        assert req.clip_id == "clip-1"
        assert req.job_id is None

    def test_schedule_posts_request_requires_source(self):
        with pytest.raises(ValidationError):
            SchedulePostsRequest(posts=[
                SchedulePostItem(account_id="a", scheduled_at="2026-04-01T12:00:00Z", metadata={}),
            ])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_publishing_routes.py::TestPublishingSchemas -v`
Expected: ImportError — schemas don't exist

- [ ] **Step 3: Create publishing schemas**

Create `app/schemas/publishing.py`:

```python
# app/schemas/publishing.py
from datetime import datetime

from pydantic import BaseModel, model_validator


class UpdateCredentialsRequest(BaseModel):
    credentials: dict


class SchedulePostItem(BaseModel):
    account_id: str
    scheduled_at: datetime
    metadata: dict


class SchedulePostsRequest(BaseModel):
    clip_id: str | None = None
    job_id: str | None = None
    posts: list[SchedulePostItem]

    @model_validator(mode="after")
    def require_video_source(self):
        if not self.clip_id and not self.job_id:
            raise ValueError("Either clip_id or job_id is required")
        return self


class UpdateScheduledPostRequest(BaseModel):
    scheduled_at: datetime | None = None
    metadata: dict | None = None


class ScheduledPostResponse(BaseModel):
    id: str
    account_id: str
    platform: str
    clip_id: str | None = None
    job_id: str | None = None
    video_storage_key: str | None = None
    scheduled_at: str | None = None
    status: str | None = None
    platform_post_id: str | None = None
    platform_url: str | None = None
    error_message: str | None = None
    metadata: dict | None = None
    created_at: str
    posted_at: str | None = None

    model_config = {"from_attributes": True}


class AccountCredentialsResponse(BaseModel):
    id: str
    platform: str
    handle: str
    has_credentials: bool
    cluster_name: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_publishing_routes.py::TestPublishingSchemas -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/publishing.py tests/test_publishing_routes.py
git commit -m "feat: add Pydantic schemas for publishing API"
```

---

### Task 8: Publishing API Routes

**Files:**
- Create: `app/routes/publishing.py`
- Modify: `app/main.py`
- Test: `tests/test_publishing_routes.py` (add route tests)

- [ ] **Step 1: Write failing tests for routes**

Add to `tests/test_publishing_routes.py`:

```python
from datetime import datetime, timezone
from unittest.mock import patch
from app.models.user import User
from app.models.cluster import Cluster, ClusterAccount, AccountPost, Platform, PostStatus
from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction
from app.models.job import Job, JobStatus
from app.services.auth import create_access_token


def _create_user(db, credits=10):
    user = User(email="pub@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


def _create_account(db, platform=Platform.tiktok, handle="@test", credentials=None):
    cluster = Cluster(name="Test Cluster")
    db.add(cluster)
    db.flush()
    account = ClusterAccount(
        cluster_id=cluster.id, platform=platform, handle=handle, credentials=credentials,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _create_clip(db, user):
    extraction = ClipExtraction(user_id=user.id, youtube_url="https://youtube.com/watch?v=abc")
    db.add(extraction)
    db.flush()
    clip = Clip(
        extraction_id=extraction.id, storage_key="clips/test/clip1.mp4",
        start_time=0.0, end_time=30.0, duration=30.0, virality_score=90,
        hook_text="Hook", transcript_text="Transcript", reframed=True,
    )
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


class TestUpdateCredentials:
    def test_set_credentials(self, client, db):
        user = _create_user(db)
        account = _create_account(db)
        resp = client.patch(
            f"/publishing/accounts/{account.id}/credentials",
            json={"credentials": {"access_token": "tok", "open_id": "oid"}},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        db.refresh(account)
        assert account.credentials["access_token"] == "tok"

    def test_nonexistent_account(self, client, db):
        user = _create_user(db)
        resp = client.patch(
            "/publishing/accounts/nonexistent/credentials",
            json={"credentials": {"access_token": "tok"}},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 404


class TestListAccountsWithCredentials:
    def test_list_only_credentialed(self, client, db):
        user = _create_user(db)
        _create_account(db, handle="@nocreds")
        _create_account(db, handle="@hascreds", credentials={"access_token": "tok", "open_id": "oid"})
        resp = client.get("/publishing/accounts", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["handle"] == "@hascreds"
        assert data[0]["has_credentials"] is True


class TestSchedulePosts:
    def test_schedule_clip_to_platform(self, client, db):
        user = _create_user(db)
        account = _create_account(db, credentials={"access_token": "tok", "open_id": "oid"})
        clip = _create_clip(db, user)
        resp = client.post("/publishing/schedule", json={
            "clip_id": clip.id,
            "posts": [{
                "account_id": account.id,
                "scheduled_at": "2026-04-01T12:00:00Z",
                "metadata": {"caption": "Test post"},
            }],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "pending"
        assert data[0]["video_storage_key"] == "clips/test/clip1.mp4"

    def test_schedule_requires_video_source(self, client, db):
        user = _create_user(db)
        account = _create_account(db, credentials={"access_token": "tok", "open_id": "oid"})
        resp = client.post("/publishing/schedule", json={
            "posts": [{
                "account_id": account.id,
                "scheduled_at": "2026-04-01T12:00:00Z",
                "metadata": {},
            }],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 422

    def test_schedule_job_without_output_returns_400(self, client, db):
        user = _create_user(db)
        account = _create_account(db, credentials={"access_token": "tok", "open_id": "oid"})
        job = Job(user_id=user.id, source_video_key="src.mp4", gameplay_key="gp.mp4", status=JobStatus.processing)
        db.add(job)
        db.commit()
        db.refresh(job)
        resp = client.post("/publishing/schedule", json={
            "job_id": job.id,
            "posts": [{
                "account_id": account.id,
                "scheduled_at": "2026-04-01T12:00:00Z",
                "metadata": {},
            }],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 400

    def test_account_missing_credentials_returns_400(self, client, db):
        user = _create_user(db)
        account = _create_account(db)  # no credentials
        clip = _create_clip(db, user)
        resp = client.post("/publishing/schedule", json={
            "clip_id": clip.id,
            "posts": [{
                "account_id": account.id,
                "scheduled_at": "2026-04-01T12:00:00Z",
                "metadata": {},
            }],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 400


class TestGetScheduledPost:
    def test_get_post(self, client, db):
        user = _create_user(db)
        account = _create_account(db)
        post = AccountPost(
            account_id=account.id, status=PostStatus.pending,
            video_storage_key="clips/test/c.mp4",
            scheduled_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            metadata={"caption": "hi"},
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        resp = client.get(f"/publishing/schedule/{post.id}", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"


class TestDeleteScheduledPost:
    def test_delete_pending(self, client, db):
        user = _create_user(db)
        account = _create_account(db)
        post = AccountPost(
            account_id=account.id, status=PostStatus.pending,
            scheduled_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        resp = client.delete(f"/publishing/schedule/{post.id}", headers=_auth_header(user.id))
        assert resp.status_code == 204

    def test_cannot_delete_uploading(self, client, db):
        user = _create_user(db)
        account = _create_account(db)
        post = AccountPost(
            account_id=account.id, status=PostStatus.uploading,
            scheduled_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        resp = client.delete(f"/publishing/schedule/{post.id}", headers=_auth_header(user.id))
        assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_publishing_routes.py -v -k "not TestPublishingSchemas"`
Expected: FAIL — routes don't exist, 404s

- [ ] **Step 3: Create publishing routes**

Create `app/routes/publishing.py`:

```python
# app/routes/publishing.py
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.cluster import ClusterAccount, AccountPost, PostStatus, Cluster
from app.models.clip import Clip
from app.models.job import Job
from app.models.user import User
from app.schemas.publishing import (
    AccountCredentialsResponse,
    SchedulePostsRequest,
    ScheduledPostResponse,
    UpdateCredentialsRequest,
    UpdateScheduledPostRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/publishing", tags=["publishing"])


def _post_to_response(post: AccountPost) -> ScheduledPostResponse:
    return ScheduledPostResponse(
        id=str(post.id),
        account_id=str(post.account_id),
        platform=post.account.platform.value,
        clip_id=str(post.clip_id) if post.clip_id else None,
        job_id=str(post.job_id) if post.job_id else None,
        video_storage_key=post.video_storage_key,
        scheduled_at=post.scheduled_at.isoformat() if post.scheduled_at else None,
        status=post.status.value if post.status else None,
        platform_post_id=post.platform_post_id,
        platform_url=post.platform_url,
        error_message=post.error_message,
        metadata=post.metadata,
        created_at=post.created_at.isoformat(),
        posted_at=post.posted_at.isoformat() if post.posted_at else None,
    )


# --- Platform Accounts ---


@router.patch("/accounts/{account_id}/credentials")
def update_credentials(
    account_id: str,
    body: UpdateCredentialsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.credentials = body.credentials
    db.commit()
    return {"status": "ok"}


@router.get("/accounts", response_model=list[AccountCredentialsResponse])
def list_accounts_with_credentials(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = (
        db.query(ClusterAccount)
        .filter(ClusterAccount.credentials.isnot(None))
        .join(Cluster)
        .all()
    )
    return [
        AccountCredentialsResponse(
            id=str(a.id),
            platform=a.platform.value,
            handle=a.handle,
            has_credentials=True,
            cluster_name=a.cluster.name,
        )
        for a in accounts
    ]


# --- Scheduled Posts ---


@router.post("/schedule", response_model=list[ScheduledPostResponse], status_code=status.HTTP_201_CREATED)
def schedule_posts(
    body: SchedulePostsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Resolve video storage key
    video_storage_key = None
    clip_id = None
    job_id = None

    if body.clip_id:
        clip = db.query(Clip).filter(Clip.id == body.clip_id).first()
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        video_storage_key = clip.storage_key
        clip_id = clip.id
    elif body.job_id:
        job = db.query(Job).filter(Job.id == body.job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.output_video_key:
            raise HTTPException(status_code=400, detail="Job has not completed processing yet")
        video_storage_key = job.output_video_key
        job_id = job.id

    created_posts = []
    for item in body.posts:
        account = db.query(ClusterAccount).filter(ClusterAccount.id == item.account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {item.account_id} not found")
        if not account.credentials:
            raise HTTPException(status_code=400, detail=f"Account {account.handle} has no credentials configured")

        post = AccountPost(
            account_id=account.id,
            clip_id=clip_id,
            job_id=job_id,
            video_storage_key=video_storage_key,
            scheduled_at=item.scheduled_at,
            status=PostStatus.pending,
            metadata=item.metadata,
        )
        db.add(post)
        created_posts.append(post)

    db.commit()
    for p in created_posts:
        db.refresh(p)

    return [_post_to_response(p) for p in created_posts]


@router.get("/schedule", response_model=list[ScheduledPostResponse])
def list_scheduled_posts(
    status_filter: str | None = Query(None, alias="status"),
    platform: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(AccountPost)
        .join(ClusterAccount)
        .filter(AccountPost.status.isnot(None))
    )
    if status_filter:
        query = query.filter(AccountPost.status == PostStatus(status_filter))
    if platform:
        query = query.filter(ClusterAccount.platform == platform)
    query = query.order_by(AccountPost.scheduled_at.asc())
    posts = query.all()
    return [_post_to_response(p) for p in posts]


@router.get("/schedule/{post_id}", response_model=ScheduledPostResponse)
def get_scheduled_post(
    post_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(AccountPost).filter(AccountPost.id == post_id).first()
    if not post or post.status is None:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    return _post_to_response(post)


@router.patch("/schedule/{post_id}", response_model=ScheduledPostResponse)
def update_scheduled_post(
    post_id: str,
    body: UpdateScheduledPostRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(AccountPost).filter(AccountPost.id == post_id).first()
    if not post or post.status is None:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    if post.status != PostStatus.pending:
        raise HTTPException(status_code=409, detail="Can only update pending posts")
    if body.scheduled_at is not None:
        post.scheduled_at = body.scheduled_at
    if body.metadata is not None:
        post.metadata = body.metadata
    db.commit()
    db.refresh(post)
    return _post_to_response(post)


@router.delete("/schedule/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scheduled_post(
    post_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(AccountPost).filter(AccountPost.id == post_id).first()
    if not post or post.status is None:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    if post.status != PostStatus.pending:
        raise HTTPException(status_code=409, detail="Can only cancel pending posts")
    db.delete(post)
    db.commit()


@router.post("/post-now", response_model=list[ScheduledPostResponse], status_code=status.HTTP_201_CREATED)
def post_now(
    body: SchedulePostsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Override scheduled_at to now for all items
    for item in body.posts:
        item.scheduled_at = datetime.now(timezone.utc)

    # Reuse schedule_posts logic but also dispatch immediately
    # Resolve video storage key (same logic as schedule_posts)
    video_storage_key = None
    clip_id = None
    job_id = None

    if body.clip_id:
        clip = db.query(Clip).filter(Clip.id == body.clip_id).first()
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        video_storage_key = clip.storage_key
        clip_id = clip.id
    elif body.job_id:
        job = db.query(Job).filter(Job.id == body.job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.output_video_key:
            raise HTTPException(status_code=400, detail="Job has not completed processing yet")
        video_storage_key = job.output_video_key
        job_id = job.id

    created_posts = []
    for item in body.posts:
        account = db.query(ClusterAccount).filter(ClusterAccount.id == item.account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {item.account_id} not found")
        if not account.credentials:
            raise HTTPException(status_code=400, detail=f"Account {account.handle} has no credentials configured")

        post = AccountPost(
            account_id=account.id,
            clip_id=clip_id,
            job_id=job_id,
            video_storage_key=video_storage_key,
            scheduled_at=item.scheduled_at,
            status=PostStatus.pending,
            metadata=item.metadata,
        )
        db.add(post)
        created_posts.append(post)

    db.commit()

    # Dispatch upload tasks immediately
    for p in created_posts:
        db.refresh(p)
        try:
            from app.publishing_worker import upload_to_platform
            upload_to_platform.delay(str(p.id))
        except Exception:
            logger.warning("Could not dispatch immediate upload for post %s", p.id)

    return [_post_to_response(p) for p in created_posts]
```

- [ ] **Step 4: Register router in main.py**

Add to `app/main.py` after the existing router imports:

```python
from app.routes.publishing import router as publishing_router
```

And after existing `app.include_router()` calls:

```python
app.include_router(publishing_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_publishing_routes.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/routes/publishing.py app/main.py tests/test_publishing_routes.py
git commit -m "feat: add publishing API routes for credentials, scheduling, and post-now"
```

---

### Task 9: Publishing Worker (Celery Beat + Upload Task)

**Files:**
- Create: `app/publishing_worker.py`
- Modify: `app/worker.py`
- Test: `tests/test_publishing_worker.py`

- [ ] **Step 1: Write failing test for worker tasks**

Create `tests/test_publishing_worker.py`:

```python
# tests/test_publishing_worker.py
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.models.cluster import Cluster, ClusterAccount, AccountPost, Platform, PostStatus


class TestPollScheduledPosts:
    @patch("app.publishing_worker.upload_to_platform")
    def test_dispatches_due_posts(self, mock_upload_task, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@t",
            credentials={"access_token": "tok", "open_id": "oid"},
        )
        db.add(account)
        db.flush()
        # Due post
        post = AccountPost(
            account_id=account.id, status=PostStatus.pending,
            scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            video_storage_key="clips/test/c.mp4",
        )
        db.add(post)
        # Future post (should NOT be dispatched)
        future_post = AccountPost(
            account_id=account.id, status=PostStatus.pending,
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            video_storage_key="clips/test/c2.mp4",
        )
        db.add(future_post)
        db.commit()
        db.refresh(post)
        db.refresh(future_post)

        from app.publishing_worker import _poll_scheduled_posts_logic
        _poll_scheduled_posts_logic()

        mock_upload_task.delay.assert_called_once_with(str(post.id))
        # Post status should be uploading
        db.refresh(post)
        assert post.status == PostStatus.uploading
        # Future post untouched
        db.refresh(future_post)
        assert future_post.status == PostStatus.pending


class TestUploadToPlatform:
    @patch("app.publishing_worker.get_uploader")
    def test_successful_upload(self, mock_get_uploader, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.youtube, handle="@yt",
            credentials={"access_token": "tok", "refresh_token": "ref",
                         "client_id": "cid", "client_secret": "csec"},
        )
        db.add(account)
        db.flush()
        post = AccountPost(
            account_id=account.id, status=PostStatus.uploading,
            scheduled_at=datetime.now(timezone.utc),
            video_storage_key="clips/test/c.mp4",
            metadata={"title": "Test"},
        )
        db.add(post)
        db.commit()
        db.refresh(post)

        mock_uploader = MagicMock()
        mock_uploader.upload.return_value = {
            "platform_post_id": "yt123",
            "platform_url": "https://youtube.com/watch?v=yt123",
        }
        mock_get_uploader.return_value = mock_uploader

        from app.publishing_worker import _upload_to_platform_logic
        _upload_to_platform_logic(str(post.id))

        db.refresh(post)
        assert post.status == PostStatus.posted
        assert post.platform_post_id == "yt123"
        assert post.platform_url == "https://youtube.com/watch?v=yt123"
        assert post.posted_at is not None

    @patch("app.publishing_worker.get_uploader")
    def test_failed_upload(self, mock_get_uploader, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@t",
            credentials={"access_token": "tok", "open_id": "oid"},
        )
        db.add(account)
        db.flush()
        post = AccountPost(
            account_id=account.id, status=PostStatus.uploading,
            scheduled_at=datetime.now(timezone.utc),
            video_storage_key="clips/test/c.mp4",
        )
        db.add(post)
        db.commit()
        db.refresh(post)

        mock_uploader = MagicMock()
        mock_uploader.upload.side_effect = RuntimeError("API error")
        mock_get_uploader.return_value = mock_uploader

        from app.publishing_worker import _upload_to_platform_logic
        _upload_to_platform_logic(str(post.id))

        db.refresh(post)
        assert post.status == PostStatus.failed
        assert "API error" in post.error_message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_publishing_worker.py -v`
Expected: ImportError — `publishing_worker` doesn't exist

- [ ] **Step 3: Create publishing worker**

Create `app/publishing_worker.py`:

```python
# app/publishing_worker.py
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.cluster import AccountPost, ClusterAccount, PostStatus
from app.services.uploaders import get_uploader
from app.worker import celery_app

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url)
PublishingSession = sessionmaker(bind=engine)


def _poll_scheduled_posts_logic():
    """Core logic extracted for testability."""
    db = PublishingSession()
    try:
        due_posts = (
            db.query(AccountPost)
            .filter(
                AccountPost.status == PostStatus.pending,
                AccountPost.scheduled_at <= datetime.now(timezone.utc),
            )
            .all()
        )
        for post in due_posts:
            post.status = PostStatus.uploading
            db.commit()
            upload_to_platform.delay(str(post.id))
            logger.info("Dispatched upload for post %s", post.id)
    finally:
        db.close()


def _upload_to_platform_logic(account_post_id: str, is_final_attempt: bool = True):
    """Core logic extracted for testability.

    Args:
        account_post_id: The AccountPost ID to upload.
        is_final_attempt: If True, marks post as failed on error.
            If False, re-raises the exception for Celery retry.
    """
    db = PublishingSession()
    try:
        post = db.query(AccountPost).filter(AccountPost.id == account_post_id).first()
        if not post:
            logger.error("AccountPost %s not found", account_post_id)
            return

        account = db.query(ClusterAccount).filter(ClusterAccount.id == post.account_id).first()
        if not account or not account.credentials:
            post.status = PostStatus.failed
            post.error_message = "Account or credentials missing"
            db.commit()
            return

        # Resolve video path
        video_path = os.path.join(settings.storage_dir, post.video_storage_key)
        if not os.path.exists(video_path):
            post.status = PostStatus.failed
            post.error_message = f"Video file not found: {post.video_storage_key}"
            db.commit()
            return

        # YouTube token refresh
        if account.platform.value == "youtube":
            from app.services.uploaders.youtube import YouTubeUploader
            yt = YouTubeUploader()
            new_token = yt.refresh_access_token(account.credentials)
            if new_token:
                account.credentials = {**account.credentials, "access_token": new_token}
                db.commit()

        uploader = get_uploader(account.platform.value)
        result = uploader.upload(video_path, post.metadata or {}, account.credentials)

        post.status = PostStatus.posted
        post.platform_post_id = result.get("platform_post_id")
        post.platform_url = result.get("platform_url")
        post.posted_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Successfully posted %s to %s", post.id, account.platform.value)

    except Exception as e:
        db.rollback()
        if is_final_attempt:
            post = db.query(AccountPost).filter(AccountPost.id == account_post_id).first()
            if post:
                post.status = PostStatus.failed
                post.error_message = str(e)[:1000]
                db.commit()
            logger.exception("Upload failed (final attempt) for post %s", account_post_id)
        else:
            # Re-raise so Celery can retry
            post = db.query(AccountPost).filter(AccountPost.id == account_post_id).first()
            if post:
                post.error_message = f"Retry: {str(e)[:500]}"
                post.status = PostStatus.pending
                db.commit()
            logger.warning("Upload failed (will retry) for post %s: %s", account_post_id, e)
            raise
    finally:
        db.close()


@celery_app.task(name="poll_scheduled_posts")
def poll_scheduled_posts():
    _poll_scheduled_posts_logic()


@celery_app.task(name="upload_to_platform", bind=True, max_retries=3)
def upload_to_platform(self, account_post_id: str):
    is_final = self.request.retries >= self.max_retries
    try:
        _upload_to_platform_logic(account_post_id, is_final_attempt=is_final)
    except Exception as e:
        if not is_final:
            raise self.retry(exc=e, countdown=60)
        raise
```

- [ ] **Step 4: Update worker.py with Beat schedule and import**

Modify `app/worker.py` — add the Beat schedule inside `celery_app.conf.update()`:

```python
beat_schedule = {
    "poll-scheduled-posts": {
        "task": "poll_scheduled_posts",
        "schedule": 60.0,
    },
},
```

Add import at the bottom of `app/worker.py`:

```python
import app.publishing_worker  # noqa: F401, E402 — register publishing tasks with Beat
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_publishing_worker.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/publishing_worker.py app/worker.py tests/test_publishing_worker.py
git commit -m "feat: add Celery Beat polling and upload_to_platform worker task"
```

---

### Task 10: Integration Test — Full Scheduling Flow

**Files:**
- Test: `tests/test_publishing_routes.py` (add integration test)

- [ ] **Step 1: Write end-to-end test**

Add to `tests/test_publishing_routes.py`:

```python
class TestPostNow:
    @patch("app.routes.publishing.upload_to_platform")
    def test_post_now_dispatches_immediately(self, mock_upload_task, client, db):
        user = _create_user(db)
        account = _create_account(db, credentials={"access_token": "tok", "open_id": "oid"})
        clip = _create_clip(db, user)
        resp = client.post("/publishing/post-now", json={
            "clip_id": clip.id,
            "posts": [{
                "account_id": account.id,
                "scheduled_at": "2099-01-01T00:00:00Z",  # will be overridden
                "metadata": {"caption": "Now!"},
            }],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "pending"
        # Verify dispatch was called
        mock_upload_task.delay.assert_called_once()


class TestUpdateScheduledPost:
    def test_update_metadata(self, client, db):
        user = _create_user(db)
        account = _create_account(db)
        post = AccountPost(
            account_id=account.id, status=PostStatus.pending,
            video_storage_key="clips/test/c.mp4",
            scheduled_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            metadata={"caption": "old"},
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        resp = client.patch(f"/publishing/schedule/{post.id}", json={
            "metadata": {"caption": "new"},
        }, headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["metadata"]["caption"] == "new"

    def test_cannot_update_posted(self, client, db):
        user = _create_user(db)
        account = _create_account(db)
        post = AccountPost(
            account_id=account.id, status=PostStatus.posted,
            video_storage_key="clips/test/c.mp4",
            scheduled_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        resp = client.patch(f"/publishing/schedule/{post.id}", json={
            "metadata": {"caption": "new"},
        }, headers=_auth_header(user.id))
        assert resp.status_code == 409
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/test_publishing_routes.py tests/test_publishing_worker.py tests/test_uploaders.py tests/test_publishing_models.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_publishing_routes.py
git commit -m "test: add integration tests for post-now and update flows"
```

---

### Task 11: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `pytest --tb=short -q`
Expected: All tests pass, no regressions

- [ ] **Step 2: Verify the API starts**

Run: `uvicorn app.main:app --reload` and confirm `/docs` shows the new `/publishing` endpoints.

- [ ] **Step 3: Final commit if any loose changes**

```bash
git status
```
