# Analytics Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automated TikTok profile analytics — scrape public profiles via yt-dlp every 6 hours, store snapshots, serve growth and aggregate stats via API.

**Architecture:** `TikTokScraper` service uses yt-dlp to extract profile metadata. Celery Beat dispatches per-account scrape tasks every 6 hours. `ProfileSnapshot` model stores every scrape forever. API routes serve current stats, history, growth deltas, and cluster-wide aggregates.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Celery Beat, yt-dlp, Pydantic

**Spec:** `docs/superpowers/specs/2026-03-22-analytics-suite-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/models/profile_snapshot.py` | Create | ProfileSnapshot model with composite index |
| `app/models/__init__.py` | Modify | Re-export ProfileSnapshot |
| `migrations/versions/xxx_add_profile_snapshots.py` | Create | Alembic migration for profile_snapshots table |
| `app/services/tiktok_scraper.py` | Create | yt-dlp based TikTok profile scraper |
| `app/schemas/analytics.py` | Create | Pydantic request/response schemas |
| `app/routes/analytics.py` | Create | Analytics API routes (5 endpoints) |
| `app/main.py` | Modify | Register analytics router |
| `app/analytics_worker.py` | Create | Beat task + per-account scrape task |
| `app/worker.py` | Modify | Add Beat schedule + import analytics_worker |
| `tests/test_tiktok_scraper.py` | Create | Scraper unit tests |
| `tests/test_analytics_routes.py` | Create | Route tests |
| `tests/test_analytics_worker.py` | Create | Worker task tests |

---

### Task 1: ProfileSnapshot Model

**Files:**
- Create: `app/models/profile_snapshot.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_analytics_models.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_analytics_models.py`:

```python
# tests/test_analytics_models.py
from datetime import datetime, timezone
from app.models.profile_snapshot import ProfileSnapshot
from app.models.cluster import Cluster, ClusterAccount, Platform


class TestProfileSnapshot:
    def test_create_snapshot(self, db):
        cluster = Cluster(name="Test Client")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@joefazer",
        )
        db.add(account)
        db.flush()

        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=125000,
            following=340,
            total_likes=8500000,
            total_videos=210,
            bio="Fitness content creator",
            avatar_url="https://p16.tiktok.com/avatar.jpg",
            recent_videos=[
                {
                    "url": "https://www.tiktok.com/@joefazer/video/123",
                    "views": 150000,
                    "likes": 12000,
                    "comments": 340,
                    "shares": 890,
                    "caption": "Morning routine",
                    "posted_at": "2026-03-20T14:30:00Z",
                }
            ],
            scraped_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.id is not None
        assert snapshot.followers == 125000
        assert snapshot.total_likes == 8500000
        assert snapshot.recent_videos[0]["views"] == 150000
        assert snapshot.scraped_at.year == 2026

    def test_cascade_delete(self, db):
        cluster = Cluster(name="Test Client")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@test",
        )
        db.add(account)
        db.flush()
        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=100,
            following=50,
            total_likes=1000,
            total_videos=10,
            scraped_at=datetime.now(timezone.utc),
        )
        db.add(snapshot)
        db.commit()

        # Delete account — snapshot should cascade
        db.delete(account)
        db.commit()
        remaining = db.query(ProfileSnapshot).filter(
            ProfileSnapshot.account_id == account.id
        ).all()
        assert len(remaining) == 0

    def test_nullable_fields(self, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@min",
        )
        db.add(account)
        db.flush()
        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=0,
            following=0,
            total_likes=0,
            total_videos=0,
            scraped_at=datetime.now(timezone.utc),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        assert snapshot.bio is None
        assert snapshot.avatar_url is None
        assert snapshot.recent_videos is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_models.py -v`
Expected: ImportError — `ProfileSnapshot` doesn't exist

- [ ] **Step 3: Create ProfileSnapshot model**

Create `app/models/profile_snapshot.py`:

```python
# app/models/profile_snapshot.py
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, BigInteger, Text, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"
    __table_args__ = (
        Index("ix_profile_snapshots_account_scraped", "account_id", "scraped_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("cluster_accounts.id", ondelete="CASCADE")
    )
    followers: Mapped[int] = mapped_column(Integer)
    following: Mapped[int] = mapped_column(Integer)
    total_likes: Mapped[int] = mapped_column(BigInteger)
    total_videos: Mapped[int] = mapped_column(Integer)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recent_videos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

Update `app/models/__init__.py` — add at the end:

```python
from app.models.profile_snapshot import ProfileSnapshot  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analytics_models.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/profile_snapshot.py app/models/__init__.py tests/test_analytics_models.py
git commit -m "feat: add ProfileSnapshot model with composite index"
```

---

### Task 2: Alembic Migration

**Files:**
- Create: `migrations/versions/xxx_add_profile_snapshots.py`

- [ ] **Step 1: Generate migration**

Run: `alembic revision --autogenerate -m "add profile_snapshots table"`

- [ ] **Step 2: Review the generated migration**

Verify it contains:
- `create_table('profile_snapshots', ...)` with all columns
- `id` String(36) PK
- `account_id` String(36) FK -> cluster_accounts.id with ondelete CASCADE
- `followers` Integer
- `following` Integer
- `total_likes` BigInteger
- `total_videos` Integer
- `bio` Text nullable
- `avatar_url` String(500) nullable
- `recent_videos` JSON nullable
- `scraped_at` DateTime(timezone=True)
- Composite index on (account_id, scraped_at)

Adjust if needed for SQLite compatibility (FK CASCADE is declared in model but not enforced by SQLite).

- [ ] **Step 3: Run migration**

Run: `alembic upgrade head`

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/
git commit -m "feat: add profile_snapshots migration"
```

---

### Task 3: TikTok Scraper Service

**Files:**
- Create: `app/services/tiktok_scraper.py`
- Test: `tests/test_tiktok_scraper.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_tiktok_scraper.py`:

```python
# tests/test_tiktok_scraper.py
import pytest
from unittest.mock import patch, MagicMock
from app.services.tiktok_scraper import TikTokScraper


class TestTikTokScraper:
    def test_build_url(self):
        scraper = TikTokScraper()
        assert scraper._build_url("@joefazer") == "https://www.tiktok.com/@joefazer"
        assert scraper._build_url("joefazer") == "https://www.tiktok.com/@joefazer"

    @patch("app.services.tiktok_scraper.yt_dlp.YoutubeDL")
    def test_scrape_success(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {
            "channel_follower_count": 125000,
            "channel_following_count": 340,
            "like_count": 8500000,
            "description": "Fitness content creator",
            "thumbnails": [{"url": "https://p16.tiktok.com/avatar.jpg"}],
            "entries": [
                {
                    "url": "https://www.tiktok.com/@joefazer/video/123",
                    "view_count": 150000,
                    "like_count": 12000,
                    "comment_count": 340,
                    "repost_count": 890,
                    "title": "Morning routine",
                    "upload_date": "20260320",
                },
                {
                    "url": "https://www.tiktok.com/@joefazer/video/456",
                    "view_count": 80000,
                    "like_count": 6000,
                    "comment_count": 120,
                    "repost_count": 200,
                    "title": "Workout tips",
                    "upload_date": "20260319",
                },
            ],
        }

        scraper = TikTokScraper()
        result = scraper.scrape("@joefazer")

        assert result["followers"] == 125000
        assert result["following"] == 340
        assert result["total_likes"] == 8500000
        assert result["total_videos"] == 2
        assert result["bio"] == "Fitness content creator"
        assert len(result["recent_videos"]) == 2
        assert result["recent_videos"][0]["views"] == 150000
        assert result["recent_videos"][0]["caption"] == "Morning routine"

    @patch("app.services.tiktok_scraper.yt_dlp.YoutubeDL")
    def test_scrape_failure(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("Network error")

        scraper = TikTokScraper()
        with pytest.raises(Exception, match="Network error"):
            scraper.scrape("@joefazer")

    @patch("app.services.tiktok_scraper.yt_dlp.YoutubeDL")
    def test_scrape_empty_profile(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {
            "channel_follower_count": 0,
            "entries": [],
        }

        scraper = TikTokScraper()
        result = scraper.scrape("@newaccount")
        assert result["followers"] == 0
        assert result["total_videos"] == 0
        assert result["recent_videos"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tiktok_scraper.py -v`
Expected: ImportError — `TikTokScraper` doesn't exist

- [ ] **Step 3: Implement TikTok scraper**

Create `app/services/tiktok_scraper.py`:

```python
# app/services/tiktok_scraper.py
import logging
from datetime import datetime, timezone

import yt_dlp

logger = logging.getLogger(__name__)


class TikTokScraper:
    def _build_url(self, handle: str) -> str:
        clean = handle.lstrip("@")
        return f"https://www.tiktok.com/@{clean}"

    def _parse_upload_date(self, date_str: str | None) -> str | None:
        if not date_str or len(date_str) != 8:
            return None
        try:
            dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return None

    def scrape(self, handle: str) -> dict:
        url = self._build_url(handle)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "dump_single_json": True,
            "playlistend": 30,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries") or []
        recent_videos = []
        for entry in entries:
            recent_videos.append({
                "url": entry.get("url") or entry.get("webpage_url", ""),
                "views": entry.get("view_count", 0) or 0,
                "likes": entry.get("like_count", 0) or 0,
                "comments": entry.get("comment_count", 0) or 0,
                "shares": entry.get("repost_count", 0) or 0,
                "caption": entry.get("title") or entry.get("description", ""),
                "posted_at": self._parse_upload_date(entry.get("upload_date")),
            })

        avatar_url = None
        thumbnails = info.get("thumbnails") or []
        if thumbnails:
            avatar_url = thumbnails[-1].get("url")

        return {
            "followers": info.get("channel_follower_count", 0) or 0,
            "following": info.get("channel_following_count", 0) or 0,
            "total_likes": info.get("like_count", 0) or 0,
            "total_videos": len(entries),
            "bio": info.get("description") or None,
            "avatar_url": avatar_url,
            "recent_videos": recent_videos,
            "scraped_at": datetime.now(timezone.utc),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tiktok_scraper.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/tiktok_scraper.py tests/test_tiktok_scraper.py
git commit -m "feat: add TikTok profile scraper using yt-dlp"
```

---

### Task 4: Pydantic Schemas for Analytics API

**Files:**
- Create: `app/schemas/analytics.py`
- Test: `tests/test_analytics_routes.py` (schema tests only)

- [ ] **Step 1: Write failing test**

Create `tests/test_analytics_routes.py`:

```python
# tests/test_analytics_routes.py
from app.schemas.analytics import (
    SnapshotResponse,
    GrowthResponse,
    ClusterOverviewResponse,
    AccountSummary,
)


class TestAnalyticsSchemas:
    def test_snapshot_response(self):
        resp = SnapshotResponse(
            id="abc",
            account_id="acc1",
            followers=1000,
            following=50,
            total_likes=50000,
            total_videos=30,
            bio="Test bio",
            avatar_url=None,
            recent_videos=[],
            scraped_at="2026-03-22T12:00:00Z",
        )
        assert resp.followers == 1000

    def test_growth_response(self):
        resp = GrowthResponse(
            current_followers=1000,
            previous_followers=800,
            follower_change=200,
            current_likes=50000,
            previous_likes=45000,
            likes_change=5000,
            current_videos=30,
            previous_videos=25,
            videos_change=5,
            period_days=7,
            avg_views=15000,
            avg_likes=1200,
            avg_comments=80,
        )
        assert resp.follower_change == 200

    def test_cluster_overview(self):
        resp = ClusterOverviewResponse(
            cluster_id="c1",
            cluster_name="Joe Fazer",
            total_followers=250000,
            total_likes=12000000,
            total_videos=500,
            account_count=3,
            accounts=[],
        )
        assert resp.account_count == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_routes.py::TestAnalyticsSchemas -v`
Expected: ImportError

- [ ] **Step 3: Create analytics schemas**

Create `app/schemas/analytics.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analytics_routes.py::TestAnalyticsSchemas -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/analytics.py tests/test_analytics_routes.py
git commit -m "feat: add Pydantic schemas for analytics API"
```

---

### Task 5: Analytics API Routes

**Files:**
- Create: `app/routes/analytics.py`
- Modify: `app/main.py`
- Test: `tests/test_analytics_routes.py` (add route tests)

- [ ] **Step 1: Write failing tests for routes**

Add to `tests/test_analytics_routes.py`:

```python
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from app.models.user import User
from app.models.cluster import Cluster, ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from app.services.auth import create_access_token


def _create_user(db):
    user = User(email="analytics@example.com", password_hash="hashed", credits_remaining=10)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


def _create_account_with_snapshots(db, handle="@joefazer", num_snapshots=3):
    cluster = Cluster(name="Test Client")
    db.add(cluster)
    db.flush()
    account = ClusterAccount(
        cluster_id=cluster.id,
        platform=Platform.tiktok,
        handle=handle,
    )
    db.add(account)
    db.flush()

    now = datetime.now(timezone.utc)
    snapshots = []
    for i in range(num_snapshots):
        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=1000 + (i * 100),
            following=50,
            total_likes=50000 + (i * 5000),
            total_videos=30 + i,
            bio="Test bio",
            recent_videos=[
                {"url": "https://tiktok.com/v/1", "views": 10000 + (i * 1000),
                 "likes": 500, "comments": 20, "shares": 10,
                 "caption": "Video", "posted_at": "2026-03-20T12:00:00Z"},
            ],
            scraped_at=now - timedelta(days=i * 3),
        )
        db.add(snapshot)
        snapshots.append(snapshot)
    db.commit()
    return cluster, account, snapshots


class TestGetCurrentSnapshot:
    def test_returns_latest(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/accounts/{account.id}/current",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Latest snapshot has highest followers (1000 + 2*100 = 1200)
        assert data["followers"] == 1200

    def test_no_snapshots_404(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Empty")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@empty",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.get(
            f"/analytics/accounts/{account.id}/current",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 404


class TestGetHistory:
    def test_returns_snapshots(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/accounts/{account.id}/history",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    def test_filter_by_date_range(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        # Only get snapshots from last 4 days (should get 2: today and 3 days ago)
        from_date = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        resp = client.get(
            f"/analytics/accounts/{account.id}/history?from={from_date}",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


class TestGetGrowth:
    def test_growth_over_7_days(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/accounts/{account.id}/growth?days=7",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 7
        assert data["current_followers"] == 1200
        assert data["follower_change"] is not None


class TestClusterOverview:
    def test_overview(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/clusters/{cluster.id}/overview",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cluster_name"] == "Test Client"
        assert data["account_count"] == 1
        assert data["total_followers"] == 1200
        assert len(data["accounts"]) == 1


class TestManualScrape:
    @patch("app.routes.analytics._dispatch_scrape")
    def test_manual_scrape(self, mock_dispatch, client, db):
        user = _create_user(db)
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@test",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.post(
            f"/analytics/accounts/{account.id}/scrape",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 202
        mock_dispatch.assert_called_once()

    def test_non_tiktok_account_400(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.youtube, handle="@ytchannel",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.post(
            f"/analytics/accounts/{account.id}/scrape",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analytics_routes.py -v -k "not TestAnalyticsSchemas"`
Expected: FAIL — routes don't exist

- [ ] **Step 3: Create analytics routes**

Create `app/routes/analytics.py`:

```python
# app/routes/analytics.py
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.cluster import Cluster, ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from app.models.user import User
from app.schemas.analytics import (
    AccountSummary,
    ClusterOverviewResponse,
    GrowthResponse,
    SnapshotResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _snapshot_to_response(snapshot: ProfileSnapshot) -> SnapshotResponse:
    return SnapshotResponse(
        id=str(snapshot.id),
        account_id=str(snapshot.account_id),
        followers=snapshot.followers,
        following=snapshot.following,
        total_likes=snapshot.total_likes,
        total_videos=snapshot.total_videos,
        bio=snapshot.bio,
        avatar_url=snapshot.avatar_url,
        recent_videos=snapshot.recent_videos,
        scraped_at=snapshot.scraped_at.isoformat(),
    )


def _get_latest_snapshot(db: Session, account_id: str) -> ProfileSnapshot | None:
    return (
        db.query(ProfileSnapshot)
        .filter(ProfileSnapshot.account_id == account_id)
        .order_by(ProfileSnapshot.scraped_at.desc())
        .first()
    )


def _dispatch_scrape(account_id: str) -> None:
    """Dispatch scrape task to Celery if available, otherwise log."""
    try:
        from app.analytics_worker import scrape_tiktok_profile
        scrape_tiktok_profile.delay(account_id)
    except Exception:
        logger.warning("Could not dispatch scrape for account %s", account_id)


@router.get("/accounts/{account_id}/current", response_model=SnapshotResponse)
def get_current_snapshot(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    snapshot = _get_latest_snapshot(db, account_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshots found for this account")
    return _snapshot_to_response(snapshot)


@router.get("/accounts/{account_id}/history", response_model=list[SnapshotResponse])
def get_history(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=500),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    query = (
        db.query(ProfileSnapshot)
        .filter(ProfileSnapshot.account_id == account_id)
    )

    if from_date:
        query = query.filter(ProfileSnapshot.scraped_at >= from_date)
    else:
        # Default to last 30 days
        default_from = datetime.now(timezone.utc) - timedelta(days=30)
        query = query.filter(ProfileSnapshot.scraped_at >= default_from)

    if to_date:
        query = query.filter(ProfileSnapshot.scraped_at <= to_date)

    snapshots = (
        query.order_by(ProfileSnapshot.scraped_at.desc())
        .limit(limit)
        .all()
    )
    return [_snapshot_to_response(s) for s in snapshots]


@router.get("/accounts/{account_id}/growth", response_model=GrowthResponse)
def get_growth(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=365),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    latest = _get_latest_snapshot(db, account_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No snapshots found")

    # Find snapshot closest to `days` ago
    target_date = datetime.now(timezone.utc) - timedelta(days=days)
    previous = (
        db.query(ProfileSnapshot)
        .filter(
            ProfileSnapshot.account_id == account_id,
            ProfileSnapshot.scraped_at <= target_date,
        )
        .order_by(ProfileSnapshot.scraped_at.desc())
        .first()
    )

    # Compute avg views/likes/comments from recent_videos
    avg_views = None
    avg_likes = None
    avg_comments = None
    if latest.recent_videos:
        videos = latest.recent_videos
        if videos:
            avg_views = sum(v.get("views", 0) for v in videos) / len(videos)
            avg_likes = sum(v.get("likes", 0) for v in videos) / len(videos)
            avg_comments = sum(v.get("comments", 0) for v in videos) / len(videos)

    return GrowthResponse(
        current_followers=latest.followers,
        previous_followers=previous.followers if previous else None,
        follower_change=(latest.followers - previous.followers) if previous else None,
        current_likes=latest.total_likes,
        previous_likes=previous.total_likes if previous else None,
        likes_change=(latest.total_likes - previous.total_likes) if previous else None,
        current_videos=latest.total_videos,
        previous_videos=previous.total_videos if previous else None,
        videos_change=(latest.total_videos - previous.total_videos) if previous else None,
        period_days=days,
        avg_views=avg_views,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
    )


@router.get("/clusters/{cluster_id}/overview", response_model=ClusterOverviewResponse)
def get_cluster_overview(
    cluster_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    accounts = (
        db.query(ClusterAccount)
        .filter(
            ClusterAccount.cluster_id == cluster_id,
            ClusterAccount.platform == Platform.tiktok,
        )
        .all()
    )

    total_followers = 0
    total_likes = 0
    total_videos = 0
    account_summaries = []

    for account in accounts:
        latest = _get_latest_snapshot(db, account.id)
        summary = AccountSummary(
            account_id=str(account.id),
            handle=account.handle,
            platform=account.platform.value,
            followers=latest.followers if latest else None,
            total_likes=latest.total_likes if latest else None,
            total_videos=latest.total_videos if latest else None,
            last_scraped=latest.scraped_at.isoformat() if latest else None,
        )
        account_summaries.append(summary)
        if latest:
            total_followers += latest.followers
            total_likes += latest.total_likes
            total_videos += latest.total_videos

    return ClusterOverviewResponse(
        cluster_id=str(cluster.id),
        cluster_name=cluster.name,
        total_followers=total_followers,
        total_likes=total_likes,
        total_videos=total_videos,
        account_count=len(accounts),
        accounts=account_summaries,
    )


@router.post("/accounts/{account_id}/scrape", status_code=status.HTTP_202_ACCEPTED)
def manual_scrape(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.platform != Platform.tiktok:
        raise HTTPException(status_code=400, detail="Analytics scraping is only supported for TikTok accounts")

    _dispatch_scrape(str(account.id))
    return {"status": "scrape dispatched", "account_id": str(account.id)}
```

- [ ] **Step 4: Register router in main.py**

Add to `app/main.py` after existing router imports:

```python
from app.routes.analytics import router as analytics_router
```

And after existing `app.include_router()` calls:

```python
app.include_router(analytics_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_analytics_routes.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/routes/analytics.py app/main.py tests/test_analytics_routes.py
git commit -m "feat: add analytics API routes for snapshots, growth, and cluster overview"
```

---

### Task 6: Analytics Worker (Celery Beat + Scrape Task)

**Files:**
- Create: `app/analytics_worker.py`
- Modify: `app/worker.py`
- Test: `tests/test_analytics_worker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_analytics_worker.py`:

```python
# tests/test_analytics_worker.py
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from app.models.cluster import Cluster, ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from tests.conftest import TestSession


def _patch_session():
    """Patch AnalyticsSession to use the test database."""
    return patch("app.analytics_worker.AnalyticsSession", TestSession)


class TestPollAccountAnalytics:
    @patch("app.analytics_worker.scrape_tiktok_profile")
    def test_dispatches_for_tiktok_accounts(self, mock_scrape_task, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        # TikTok account — should be dispatched
        tt_account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@tt",
        )
        db.add(tt_account)
        # YouTube account — should NOT be dispatched
        yt_account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.youtube, handle="@yt",
        )
        db.add(yt_account)
        db.commit()
        db.refresh(tt_account)

        with _patch_session():
            from app.analytics_worker import _poll_account_analytics_logic
            _poll_account_analytics_logic()

        mock_scrape_task.delay.assert_called_once_with(str(tt_account.id))


class TestScrapeTikTokProfile:
    @patch("app.analytics_worker.TikTokScraper")
    def test_successful_scrape_creates_snapshot(self, mock_scraper_class, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@joefazer",
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        mock_scraper = MagicMock()
        mock_scraper.scrape.return_value = {
            "followers": 125000,
            "following": 340,
            "total_likes": 8500000,
            "total_videos": 210,
            "bio": "Fitness creator",
            "avatar_url": "https://example.com/avatar.jpg",
            "recent_videos": [{"url": "https://tiktok.com/v/1", "views": 50000}],
            "scraped_at": datetime.now(timezone.utc),
        }
        mock_scraper_class.return_value = mock_scraper

        with _patch_session():
            from app.analytics_worker import _scrape_tiktok_profile_logic
            _scrape_tiktok_profile_logic(str(account.id))

        snapshots = db.query(ProfileSnapshot).filter(
            ProfileSnapshot.account_id == account.id
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].followers == 125000
        assert snapshots[0].total_likes == 8500000

    @patch("app.analytics_worker.TikTokScraper")
    def test_failed_scrape_no_snapshot(self, mock_scraper_class, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@broken",
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        mock_scraper = MagicMock()
        mock_scraper.scrape.side_effect = RuntimeError("Rate limited")
        mock_scraper_class.return_value = mock_scraper

        with _patch_session():
            from app.analytics_worker import _scrape_tiktok_profile_logic
            try:
                _scrape_tiktok_profile_logic(str(account.id))
            except RuntimeError:
                pass  # Expected — Celery retry will catch this

        snapshots = db.query(ProfileSnapshot).filter(
            ProfileSnapshot.account_id == account.id
        ).all()
        assert len(snapshots) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analytics_worker.py -v`
Expected: ImportError — `analytics_worker` doesn't exist

- [ ] **Step 3: Create analytics worker**

Create `app/analytics_worker.py`:

```python
# app/analytics_worker.py
import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.cluster import ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from app.services.tiktok_scraper import TikTokScraper
from app.worker import celery_app

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url)
AnalyticsSession = sessionmaker(bind=engine)


def _poll_account_analytics_logic():
    """Core logic extracted for testability."""
    db = AnalyticsSession()
    try:
        accounts = (
            db.query(ClusterAccount)
            .filter(ClusterAccount.platform == Platform.tiktok)
            .all()
        )
        for account in accounts:
            scrape_tiktok_profile.delay(str(account.id))
            logger.info("Dispatched scrape for account %s (%s)", account.id, account.handle)
    finally:
        db.close()


def _scrape_tiktok_profile_logic(account_id: str):
    """Core logic extracted for testability."""
    db = AnalyticsSession()
    try:
        account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
        if not account:
            logger.error("ClusterAccount %s not found", account_id)
            return

        scraper = TikTokScraper()
        data = scraper.scrape(account.handle)

        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=data["followers"],
            following=data["following"],
            total_likes=data["total_likes"],
            total_videos=data["total_videos"],
            bio=data.get("bio"),
            avatar_url=data.get("avatar_url"),
            recent_videos=data.get("recent_videos"),
            scraped_at=data.get("scraped_at", datetime.now(timezone.utc)),
        )
        db.add(snapshot)
        db.commit()
        logger.info("Snapshot created for account %s: %d followers", account.handle, data["followers"])

    except Exception as e:
        db.rollback()
        logger.exception("Scrape failed for account %s: %s", account_id, e)
        raise
    finally:
        db.close()


@celery_app.task(name="poll_account_analytics")
def poll_account_analytics():
    _poll_account_analytics_logic()


@celery_app.task(name="scrape_tiktok_profile", bind=True, max_retries=3)
def scrape_tiktok_profile(self, account_id: str):
    try:
        _scrape_tiktok_profile_logic(account_id)
    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)
        logger.error("Scrape permanently failed for account %s after %d retries", account_id, self.max_retries)
```

- [ ] **Step 4: Update worker.py with Beat schedule and import**

Modify `app/worker.py` — add to the Beat schedule in `celery_app.conf.update()`:

```python
"poll-account-analytics": {
    "task": "poll_account_analytics",
    "schedule": 21600.0,  # 6 hours
},
```

Add import at the bottom of `app/worker.py`:

```python
import app.analytics_worker  # noqa: F401, E402 — register analytics tasks with Beat
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_analytics_worker.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/analytics_worker.py app/worker.py tests/test_analytics_worker.py
git commit -m "feat: add Celery Beat analytics polling and scrape task"
```

---

### Task 7: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `pytest --tb=short -q`
Expected: All tests pass, no regressions

- [ ] **Step 2: Verify the API starts**

Run: `uvicorn app.main:app --reload` and confirm `/docs` shows the new `/analytics` endpoints.

- [ ] **Step 3: Test manual scrape end-to-end (optional)**

If a real TikTok handle is available, test the scraper manually:

```python
from app.services.tiktok_scraper import TikTokScraper
scraper = TikTokScraper()
result = scraper.scrape("@joefazer")
print(result)
```

- [ ] **Step 4: Final commit if any loose changes**

```bash
git status
```
