# Armageddon Dashboard UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an internal single-page dashboard for the video multiplication pipeline with posting queue backend and ADB TikTok automation.

**Architecture:** New PostingQueueItem model + posting queue API routes + phone status endpoint + single HTML dashboard served at `/dashboard` + standalone ADB poster script. Backend first (model → routes → tests), then frontend, then ADB script.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic, vanilla HTML/CSS/JS, Tailwind CDN, ADB (Android Debug Bridge)

**Spec:** `docs/superpowers/specs/2026-03-22-dashboard-ui-design.md`

---

## File Structure

### New Files
- `app/models/posting_queue.py` — PostingQueueItem SQLAlchemy model
- `app/schemas/posting_queue.py` — Pydantic request/response schemas
- `app/routes/posting_queue.py` — Posting queue CRUD endpoints
- `app/routes/phone.py` — Phone status endpoint
- `tests/test_posting_queue_routes.py` — Route tests
- `tests/test_phone_routes.py` — Phone status tests
- `app/static/dashboard.html` — Single-page dashboard UI
- `scripts/tiktok_poster.py` — ADB automation script

### Modified Files
- `app/models/__init__.py` — Export new model
- `app/main.py` — Register new routers, serve dashboard HTML
- `migrations/versions/` — New migration for posting_queue_items table

---

## Task 1: PostingQueueItem Model

**Files:**
- Create: `app/models/posting_queue.py`
- Modify: `app/models/__init__.py`

- [ ] **Step 1: Create the model file**

```python
# app/models/posting_queue.py
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PostingStatus(str, enum.Enum):
    queued = "queued"
    posting = "posting"
    posted = "posted"
    failed = "failed"


class PostingQueueItem(Base):
    __tablename__ = "posting_queue_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(PostingStatus), default=PostingStatus.queued, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    caption_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job = relationship("Job", lazy="joined")
```

- [ ] **Step 2: Export the model in `__init__.py`**

Add to `app/models/__init__.py`:
```python
from app.models.posting_queue import PostingQueueItem, PostingStatus
```

- [ ] **Step 3: Generate Alembic migration**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && alembic revision --autogenerate -m "add posting_queue_items table"`

- [ ] **Step 4: Run migration**

Run: `alembic upgrade head`

- [ ] **Step 5: Commit**

```bash
git add app/models/posting_queue.py app/models/__init__.py migrations/versions/
git commit -m "feat: add PostingQueueItem model and migration"
```

---

## Task 2: Posting Queue Schemas

**Files:**
- Create: `app/schemas/posting_queue.py`

- [ ] **Step 1: Create schemas file**

```python
# app/schemas/posting_queue.py
from pydantic import BaseModel, field_validator


class AddToQueueRequest(BaseModel):
    job_id: str
    caption_text: str | None = None


class UpdateQueueItemRequest(BaseModel):
    status: str | None = None
    position: int | None = None
    caption_text: str | None = None
    error_message: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("queued", "posting", "posted", "failed"):
            raise ValueError("status must be one of: queued, posting, posted, failed")
        return v


class ReorderItem(BaseModel):
    id: str
    position: int


class ReorderRequest(BaseModel):
    order: list[ReorderItem]

    @field_validator("order")
    @classmethod
    def validate_order(cls, v: list) -> list:
        if not v:
            raise ValueError("order must not be empty")
        return v


class QueueItemResponse(BaseModel):
    id: str
    job_id: str
    status: str
    position: int
    caption_text: str | None
    posted_at: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    output_url: str | None = None
    source_video_name: str | None = None
    gameplay_name: str | None = None

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Commit**

```bash
git add app/schemas/posting_queue.py
git commit -m "feat: add posting queue request/response schemas"
```

---

## Task 3: Posting Queue Routes — Tests First

**Files:**
- Create: `tests/test_posting_queue_routes.py`

- [ ] **Step 1: Write tests for all posting queue endpoints**

```python
# tests/test_posting_queue_routes.py
from unittest.mock import patch

import pytest

from app.models.job import Job, JobStatus
from app.models.posting_queue import PostingQueueItem, PostingStatus
from app.models.user import User
from app.services.auth import create_access_token


def _create_user_and_job(db, status=JobStatus.completed):
    """Helper: create a user with a job."""
    user = User(
        email="test@example.com",
        password_hash="hashed",
        credits_remaining=10,
    )
    db.add(user)
    db.flush()
    job = Job(
        user_id=user.id,
        status=status,
        source_video_key="uploads/abc123_my_video.mp4",
        gameplay_key="gameplay/def456_subway.mp4",
        output_video_key="outputs/ghi789_output.mp4",
    )
    db.add(job)
    db.commit()
    db.refresh(user)
    db.refresh(job)
    return user, job


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


class TestAddToQueue:
    def test_add_completed_job(self, client, db):
        user, job = _create_user_and_job(db)
        resp = client.post(
            "/posting-queue",
            json={"job_id": job.id},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["job_id"] == job.id
        assert data["status"] == "queued"
        assert data["position"] >= 1

    def test_add_non_completed_job_fails(self, client, db):
        user, job = _create_user_and_job(db, status=JobStatus.processing)
        resp = client.post(
            "/posting-queue",
            json={"job_id": job.id},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 400

    def test_add_duplicate_fails(self, client, db):
        user, job = _create_user_and_job(db)
        headers = _auth_header(user.id)
        client.post("/posting-queue", json={"job_id": job.id}, headers=headers)
        resp = client.post("/posting-queue", json={"job_id": job.id}, headers=headers)
        assert resp.status_code == 409

    def test_add_nonexistent_job_fails(self, client, db):
        user, _ = _create_user_and_job(db)
        resp = client.post(
            "/posting-queue",
            json={"job_id": "nonexistent-id"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 404


class TestListQueue:
    def test_list_empty(self, client, db):
        user, _ = _create_user_and_job(db)
        resp = client.get("/posting-queue", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_items(self, client, db):
        user, job = _create_user_and_job(db)
        headers = _auth_header(user.id)
        client.post("/posting-queue", json={"job_id": job.id}, headers=headers)
        resp = client.get("/posting-queue", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_filter_by_status(self, client, db):
        user, job = _create_user_and_job(db)
        headers = _auth_header(user.id)
        client.post("/posting-queue", json={"job_id": job.id}, headers=headers)
        resp = client.get("/posting-queue?status=posted", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 0


class TestUpdateQueueItem:
    def test_update_status(self, client, db):
        user, job = _create_user_and_job(db)
        headers = _auth_header(user.id)
        create_resp = client.post(
            "/posting-queue", json={"job_id": job.id}, headers=headers
        )
        item_id = create_resp.json()["id"]
        resp = client.patch(
            f"/posting-queue/{item_id}",
            json={"status": "posting"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "posting"

    def test_invalid_status_transition_fails(self, client, db):
        user, job = _create_user_and_job(db)
        headers = _auth_header(user.id)
        create_resp = client.post(
            "/posting-queue", json={"job_id": job.id}, headers=headers
        )
        item_id = create_resp.json()["id"]
        # Move to posted
        client.patch(f"/posting-queue/{item_id}", json={"status": "posting"}, headers=headers)
        client.patch(f"/posting-queue/{item_id}", json={"status": "posted"}, headers=headers)
        # Try invalid transition: posted -> queued
        resp = client.patch(
            f"/posting-queue/{item_id}",
            json={"status": "queued"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_update_nonexistent_fails(self, client, db):
        user, _ = _create_user_and_job(db)
        resp = client.patch(
            "/posting-queue/nonexistent",
            json={"status": "posting"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 404


class TestDeleteQueueItem:
    def test_delete_queued_item(self, client, db):
        user, job = _create_user_and_job(db)
        headers = _auth_header(user.id)
        create_resp = client.post(
            "/posting-queue", json={"job_id": job.id}, headers=headers
        )
        item_id = create_resp.json()["id"]
        resp = client.delete(f"/posting-queue/{item_id}", headers=headers)
        assert resp.status_code == 204

    def test_delete_posting_item_fails(self, client, db):
        user, job = _create_user_and_job(db)
        headers = _auth_header(user.id)
        create_resp = client.post(
            "/posting-queue", json={"job_id": job.id}, headers=headers
        )
        item_id = create_resp.json()["id"]
        client.patch(
            f"/posting-queue/{item_id}", json={"status": "posting"}, headers=headers
        )
        resp = client.delete(f"/posting-queue/{item_id}", headers=headers)
        assert resp.status_code == 409


class TestReorder:
    def test_reorder_items(self, client, db):
        user = User(
            email="test@example.com", password_hash="hashed", credits_remaining=10
        )
        db.add(user)
        db.flush()
        jobs = []
        for i in range(3):
            j = Job(
                user_id=user.id,
                status=JobStatus.completed,
                source_video_key=f"uploads/vid{i}.mp4",
                gameplay_key="gameplay/gp.mp4",
                output_video_key=f"outputs/out{i}.mp4",
            )
            db.add(j)
            jobs.append(j)
        db.commit()
        for j in jobs:
            db.refresh(j)
        db.refresh(user)

        headers = _auth_header(user.id)
        item_ids = []
        for j in jobs:
            resp = client.post(
                "/posting-queue", json={"job_id": j.id}, headers=headers
            )
            item_ids.append(resp.json()["id"])

        # Reverse order
        new_order = [
            {"id": item_ids[2], "position": 1},
            {"id": item_ids[1], "position": 2},
            {"id": item_ids[0], "position": 3},
        ]
        resp = client.post(
            "/posting-queue/reorder", json={"order": new_order}, headers=headers
        )
        assert resp.status_code == 200

        # Verify new order
        list_resp = client.get("/posting-queue", headers=headers)
        items = list_resp.json()
        assert items[0]["id"] == item_ids[2]
        assert items[1]["id"] == item_ids[1]
        assert items[2]["id"] == item_ids[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && python -m pytest tests/test_posting_queue_routes.py -v`
Expected: FAIL (routes don't exist yet)

- [ ] **Step 3: Commit test file**

```bash
git add tests/test_posting_queue_routes.py
git commit -m "test: add posting queue route tests (red)"
```

---

## Task 4: Posting Queue Routes — Implementation

**Files:**
- Create: `app/routes/posting_queue.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create the routes file**

```python
# app/routes/posting_queue.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.job import Job, JobStatus
from app.models.posting_queue import PostingQueueItem, PostingStatus
from app.models.user import User
from app.schemas.posting_queue import (
    AddToQueueRequest,
    QueueItemResponse,
    ReorderRequest,
    UpdateQueueItemRequest,
)


router = APIRouter(prefix="/posting-queue", tags=["posting-queue"])


def _item_to_response(item: PostingQueueItem) -> dict:
    """Convert a PostingQueueItem to response dict with joined job data."""
    job = item.job
    # Extract display name from storage key: "uploads/abc123_name.mp4" -> "name.mp4"
    source_name = None
    gameplay_name = None
    if job and job.source_video_key:
        parts = job.source_video_key.split("/")[-1]
        source_name = "_".join(parts.split("_")[1:]) if "_" in parts else parts
    if job and job.gameplay_key:
        parts = job.gameplay_key.split("/")[-1]
        gameplay_name = "_".join(parts.split("_")[1:]) if "_" in parts else parts

    output_url = None
    if job and job.output_video_key:
        output_url = f"/storage/{job.output_video_key}"

    return {
        "id": item.id,
        "job_id": item.job_id,
        "status": item.status.value if hasattr(item.status, "value") else item.status,
        "position": item.position,
        "caption_text": item.caption_text,
        "posted_at": item.posted_at.isoformat() if item.posted_at else None,
        "error_message": item.error_message,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "output_url": output_url,
        "source_video_name": source_name,
        "gameplay_name": gameplay_name,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def add_to_queue(
    body: AddToQueueRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == body.job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.completed:
        raise HTTPException(status_code=400, detail="Job is not completed")

    existing = (
        db.query(PostingQueueItem)
        .filter(PostingQueueItem.job_id == body.job_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Job already in posting queue")

    max_pos = (
        db.query(func.coalesce(func.max(PostingQueueItem.position), 0)).scalar()
    )

    item = PostingQueueItem(
        job_id=body.job_id,
        caption_text=body.caption_text,
        position=max_pos + 1,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_to_response(item)


@router.get("")
def list_queue(
    status_filter: str | None = Query(None, alias="status"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(PostingQueueItem)
        .join(Job, PostingQueueItem.job_id == Job.id)
        .filter(Job.user_id == user.id)
        .order_by(PostingQueueItem.position)
    )
    if status_filter:
        query = query.filter(PostingQueueItem.status == status_filter)
    items = query.all()
    return [_item_to_response(item) for item in items]


@router.patch("/{item_id}")
def update_queue_item(
    item_id: str,
    body: UpdateQueueItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(PostingQueueItem)
        .join(Job, PostingQueueItem.job_id == Job.id)
        .filter(PostingQueueItem.id == item_id, Job.user_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    if body.status is not None:
        VALID_TRANSITIONS = {
            "queued": {"posting", "failed"},
            "posting": {"posted", "failed"},
            "failed": {"queued"},
            "posted": set(),
        }
        current = item.status.value if hasattr(item.status, "value") else item.status
        if body.status not in VALID_TRANSITIONS.get(current, set()):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid transition from {current} to {body.status}",
            )
        item.status = PostingStatus(body.status)
        if body.status == "posted":
            item.posted_at = datetime.now(timezone.utc)
    if body.position is not None:
        item.position = body.position
    if body.caption_text is not None:
        item.caption_text = body.caption_text
    if body.error_message is not None:
        item.error_message = body.error_message

    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return _item_to_response(item)


@router.post("/reorder")
def reorder_queue(
    body: ReorderRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for entry in body.order:
        item = (
            db.query(PostingQueueItem)
            .join(Job, PostingQueueItem.job_id == Job.id)
            .filter(PostingQueueItem.id == entry.id, Job.user_id == user.id)
            .first()
        )
        if item:
            item.position = entry.position
    db.commit()
    return {"ok": True}


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_queue_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(PostingQueueItem)
        .join(Job, PostingQueueItem.job_id == Job.id)
        .filter(PostingQueueItem.id == item_id, Job.user_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    current_status = item.status.value if hasattr(item.status, "value") else item.status
    if current_status == "posting":
        raise HTTPException(status_code=409, detail="Cannot delete item being posted")
    db.delete(item)
    db.commit()
```

- [ ] **Step 2: Register router in `app/main.py`**

Add import and include_router:
```python
from app.routes.posting_queue import router as posting_queue_router
# ...
app.include_router(posting_queue_router)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && python -m pytest tests/test_posting_queue_routes.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add app/routes/posting_queue.py app/main.py
git commit -m "feat: add posting queue CRUD routes"
```

---

## Task 5: Phone Status Endpoint

**Files:**
- Create: `app/routes/phone.py`
- Create: `tests/test_phone_routes.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_phone_routes.py
import json
import os
from unittest.mock import patch

from app.models.user import User
from app.services.auth import create_access_token


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


class TestPhoneStatus:
    def test_no_status_file(self, client, db):
        user = User(email="test@example.com", password_hash="hashed", credits_remaining=0)
        db.add(user)
        db.commit()
        db.refresh(user)
        resp = client.get("/phone/status", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["activity"] == "No status available"

    def test_with_status_file(self, client, db, tmp_path):
        user = User(email="test@example.com", password_hash="hashed", credits_remaining=0)
        db.add(user)
        db.commit()
        db.refresh(user)

        status_data = {
            "connected": True,
            "activity": "Idle",
            "last_checked": "2026-03-22T12:00:00",
        }
        status_file = tmp_path / "phone_status.json"
        status_file.write_text(json.dumps(status_data))

        with patch("app.routes.phone.get_phone_status_path", return_value=str(status_file)):
            resp = client.get("/phone/status", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["activity"] == "Idle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_phone_routes.py -v`
Expected: FAIL

- [ ] **Step 3: Create the routes file**

```python
# app/routes/phone.py
import json
import os

from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/phone", tags=["phone"])


def get_phone_status_path() -> str:
    return os.path.join(settings.storage_dir, "phone_status.json")


@router.get("/status")
def phone_status(user: User = Depends(get_current_user)):
    default = {
        "connected": False,
        "activity": "No status available",
        "last_checked": None,
    }
    path = get_phone_status_path()
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError):
        return default
```

- [ ] **Step 4: Register router in `app/main.py`**

```python
from app.routes.phone import router as phone_router
# ...
app.include_router(phone_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_phone_routes.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add app/routes/phone.py tests/test_phone_routes.py app/main.py
git commit -m "feat: add phone status endpoint"
```

---

## Task 6: Serve Dashboard HTML

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add dashboard route to `app/main.py`**

```python
from fastapi.responses import HTMLResponse

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    with open(html_path) as f:
        return f.read()
```

- [ ] **Step 2: Create placeholder dashboard file**

Create `app/static/dashboard.html` with minimal content:
```html
<!DOCTYPE html>
<html><head><title>Armageddon Dashboard</title></head>
<body><h1>Dashboard loading...</h1></body></html>
```

- [ ] **Step 3: Verify it serves**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && python -c "from app.main import app; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/static/dashboard.html
git commit -m "feat: serve dashboard HTML at /dashboard"
```

---

## Task 7: Dashboard HTML — Login & App Shell

**Files:**
- Modify: `app/static/dashboard.html`

Build the full dashboard in a single HTML file. This is the largest task. The HTML includes all CSS and JS inline.

- [ ] **Step 1: Write the complete dashboard HTML**

The dashboard must include:

**Head:**
- Tailwind CSS via CDN
- JetBrains Mono from Google Fonts
- CSS variables: `--bg: #0a0a0a`, `--accent: #ff3a2f`, `--surface: #141414`, `--border: #2a2a2a`, `--text: #e0e0e0`, `--text-muted: #888`

**Login screen:**
- Email + password form, centered on screen
- Calls `POST /auth/login`, stores `access_token` in JS variable
- On success, hides login and shows dashboard
- On error, shows error message

**App shell (hidden until login):**
- Top bar: "ARMAGEDDON" branding left, credits display right, tab navigation center
- Four tabs with badge counts: Upload & Generate, Jobs, Review Queue, Posting Queue
- Tab content areas (only active tab visible)
- `apiFetch(url, options)` helper that adds auth header, handles 401 refresh

**Polling system:**
- Only polls on active tab
- Jobs tab: polls `GET /jobs?limit=100` every 5s
- Posting Queue tab: polls `GET /posting-queue` every 5s and `GET /phone/status` every 10s
- Review Queue: refreshes on tab switch (computed from jobs + posting queue)

- [ ] **Step 2: Verify login works**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && python -m uvicorn app.main:app --port 8000`
Open: `http://localhost:8000/dashboard`
Test: Login with existing credentials

- [ ] **Step 3: Commit**

```bash
git add app/static/dashboard.html
git commit -m "feat: dashboard login and app shell with tab navigation"
```

---

## Task 8: Dashboard — Upload & Generate View

**Files:**
- Modify: `app/static/dashboard.html`

- [ ] **Step 1: Implement Upload & Generate tab content**

**Left panel (Source Videos):**
- Drag-and-drop zone with dashed border, accepts video files
- On drop/select: upload each file via `POST /videos/upload` (FormData with `file` field)
- Show upload progress per file
- After upload: show file in list with checkbox, name, and client-side thumbnail
- Client-side thumbnail: load video into hidden `<video>`, seek to 0.5s, draw to `<canvas>`, extract dataURL

**Right panel (Gameplay Selection):**
- Fetch `GET /gameplay` on tab activation
- Render grid of gameplay clips: name, duration, click-to-toggle-select (highlighted border)
- Upload button opens file picker, uploads via `POST /videos/upload-gameplay`

**Bottom bar:**
- Compute: `selectedSources.length × selectedGameplay.length = totalJobs`
- Show credits remaining (from `/auth/me`)
- Generate button: for each selected source, call `POST /jobs/batch` with `{ source_video_key, gameplay_ids }`
- Disable button if 0 selections or insufficient credits
- On success: switch to Jobs tab, clear selections

- [ ] **Step 2: Test manually**

Upload a test video, select gameplay, verify the generate flow works end-to-end.

- [ ] **Step 3: Commit**

```bash
git add app/static/dashboard.html
git commit -m "feat: dashboard upload and generate view"
```

---

## Task 9: Dashboard — Jobs View

**Files:**
- Modify: `app/static/dashboard.html`

- [ ] **Step 1: Implement Jobs tab content**

**Filter bar:**
- Toggle buttons: All / Pending / Processing / Completed / Failed
- Active filter highlighted with accent color
- Filters applied client-side on the fetched jobs array

**Jobs table:**
- Columns: status dot, source name, gameplay name, created time, status text, actions
- Status dots: yellow (#eab308) pending, blue (#3b82f6) processing, green (#22c55e) completed, red (#ef4444) failed
- Display names extracted from storage keys: `uploads/abc123_my_video.mp4` → `my_video.mp4`
- Created time: relative format ("2m ago", "1h ago")
- Failed rows: show error message in expandable section below the row
- Completed rows: "Preview" button (opens `<video>` inline in an overlay/modal)

**Polling:**
- When Jobs tab is active, `GET /jobs?limit=100` every 5 seconds
- Update table in-place (don't re-render if data hasn't changed)

- [ ] **Step 2: Test manually**

Create some jobs, watch them appear and update in the table.

- [ ] **Step 3: Commit**

```bash
git add app/static/dashboard.html
git commit -m "feat: dashboard jobs view with filtering and polling"
```

---

## Task 10: Dashboard — Review Queue View

**Files:**
- Modify: `app/static/dashboard.html`

- [ ] **Step 1: Implement Review Queue tab content**

**Review state computation:**
```javascript
function getReviewQueue(jobs, postingQueue) {
    const postedJobIds = new Set(postingQueue.map(p => p.job_id));
    const rejectedIds = JSON.parse(localStorage.getItem('rejectedJobIds') || '[]');
    const rejectedSet = new Set(rejectedIds);
    return jobs.filter(j =>
        j.status === 'completed' &&
        !postedJobIds.has(j.id) &&
        !rejectedSet.has(j.id)
    );
}
```

**Layout:**
- Left sidebar (narrow): vertical strip of video thumbnails for all review items, with count badge at top
- Main area: large `<video>` player with controls, source + gameplay name below
- Action buttons below player: Approve (green, accent), Skip (gray), Reject (red)

**Actions:**
- **Approve:** `POST /posting-queue` with `{ job_id }`, remove from review list, advance to next
- **Reject:** add job ID to localStorage `rejectedJobIds` array, advance to next
- **Skip:** advance to next without any action
- After last item: show "All caught up" message

**On tab switch to Review:** fetch latest jobs + posting queue to recompute

- [ ] **Step 2: Test manually**

Complete some jobs, verify they appear in review, test approve/reject flow.

- [ ] **Step 3: Commit**

```bash
git add app/static/dashboard.html
git commit -m "feat: dashboard review queue with approve/reject flow"
```

---

## Task 11: Dashboard — Posting Queue View

**Files:**
- Modify: `app/static/dashboard.html`

- [ ] **Step 1: Implement Posting Queue tab content**

**Phone status bar (top):**
- Fetch `GET /phone/status` every 10s when tab is active
- Green dot + "Samsung connected" or red dot + "Disconnected"
- Activity text: shows `activity` field from response

**Posting queue list:**
- Fetch `GET /posting-queue` every 5s
- Each row: position number, thumbnail (from output_url video), source name, gameplay name, status badge
- Status badges: queued (yellow), posting (blue pulse animation), posted (green), failed (red)
- Failed items: show error, "Retry" button (PATCH status back to `queued`)
- Drag-to-reorder: use HTML5 drag-and-drop API
  - On drag end: compute new positions, call `POST /posting-queue/reorder`
- "Post Next" button: PATCH first queued item to `posting` status (the ADB script picks it up)

**Posted section (bottom):**
- Collapsible section with posted count
- Simple list: name, posted timestamp
- Filter posting queue items where status === "posted"

- [ ] **Step 2: Test manually**

Approve some videos, verify they appear in posting queue, test reorder and retry.

- [ ] **Step 3: Commit**

```bash
git add app/static/dashboard.html
git commit -m "feat: dashboard posting queue view with drag-reorder"
```

---

## Task 12: ADB TikTok Poster Script

**Files:**
- Create: `scripts/tiktok_poster.py`

- [ ] **Step 1: Write the poster script**

```python
#!/usr/bin/env python3
"""
ADB TikTok Poster — polls the Armageddon API posting queue
and automates TikTok uploads on a connected Android phone.

Usage:
    python scripts/tiktok_poster.py

Environment variables:
    API_URL              - API base URL (default: http://localhost:8000)
    POSTER_EMAIL         - Login email
    POSTER_PASSWORD      - Login password
    POST_INTERVAL_SECONDS - Delay between posts (default: 1800)
    STORAGE_DIR          - Local storage directory (default: ./storage)
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API_URL = os.environ.get("API_URL", "http://localhost:8000")
POSTER_EMAIL = os.environ.get("POSTER_EMAIL", "")
POSTER_PASSWORD = os.environ.get("POSTER_PASSWORD", "")
POST_INTERVAL = int(os.environ.get("POST_INTERVAL_SECONDS", "1800"))
STORAGE_DIR = os.environ.get("STORAGE_DIR", "./storage")
PHONE_STATUS_PATH = os.path.join(STORAGE_DIR, "phone_status.json")


class TikTokPoster:
    def __init__(self):
        self.token = None
        self.session = requests.Session()

    def login(self):
        resp = self.session.post(
            f"{API_URL}/auth/login",
            json={"email": POSTER_EMAIL, "password": POSTER_PASSWORD},
        )
        resp.raise_for_status()
        self.token = resp.json()["access_token"]
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        print(f"[LOGIN] Authenticated as {POSTER_EMAIL}")

    def check_phone(self) -> bool:
        """Check if an Android device is connected via ADB."""
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")[1:]
            connected = any("device" in line and "offline" not in line for line in lines)
            return connected
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def update_phone_status(self, connected: bool, activity: str = "Idle"):
        """Write phone status to JSON file for the API to read."""
        status = {
            "connected": connected,
            "activity": activity,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.dirname(PHONE_STATUS_PATH), exist_ok=True)
        with open(PHONE_STATUS_PATH, "w") as f:
            json.dump(status, f)

    def get_next_queued(self) -> dict | None:
        """Get the next queued item from the posting queue."""
        resp = self.session.get(f"{API_URL}/posting-queue", params={"status": "queued"})
        resp.raise_for_status()
        items = resp.json()
        return items[0] if items else None

    def update_item_status(self, item_id: str, status: str, error: str | None = None):
        body = {"status": status}
        if error:
            body["error_message"] = error
        resp = self.session.patch(f"{API_URL}/posting-queue/{item_id}", json=body)
        resp.raise_for_status()

    def push_video_to_phone(self, video_path: str) -> bool:
        """Push a video file to the phone's Downloads folder."""
        phone_path = f"/sdcard/Download/{os.path.basename(video_path)}"
        try:
            result = subprocess.run(
                ["adb", "push", video_path, phone_path],
                capture_output=True, text=True, timeout=120,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def automate_tiktok_upload(self, phone_video_path: str) -> bool:
        """
        Automate TikTok upload via ADB.
        This is a placeholder — tap coordinates will need calibration
        for the specific Samsung device and TikTok version.
        """
        filename = os.path.basename(phone_video_path)
        phone_path = f"/sdcard/Download/{filename}"
        try:
            # Open TikTok via intent
            subprocess.run(
                ["adb", "shell", "am", "start", "-n",
                 "com.zhiliaoapp.musically/.MainActivityScheme"],
                capture_output=True, timeout=10,
            )
            time.sleep(3)

            # TODO: Calibrate these tap coordinates for your Samsung device
            # The flow is: + button -> upload -> select video -> next -> post
            # Each tap needs x,y coordinates specific to screen resolution
            print(f"[TIKTOK] Manual upload required for: {phone_path}")
            print("[TIKTOK] ADB tap automation needs calibration for your device")
            return True  # Placeholder — replace with actual tap sequence

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[TIKTOK] Automation error: {e}")
            return False

    def process_one(self, item: dict) -> bool:
        """Process a single posting queue item."""
        item_id = item["id"]
        output_url = item.get("output_url", "")

        # output_url is like /storage/outputs/xyz.mp4
        # Convert to local path
        local_path = os.path.join(
            STORAGE_DIR, output_url.replace("/storage/", "")
        )

        if not os.path.exists(local_path):
            self.update_item_status(item_id, "failed", f"File not found: {local_path}")
            return False

        self.update_item_status(item_id, "posting")
        self.update_phone_status(True, f"Posting: {item.get('source_video_name', 'video')}")

        # Push to phone
        if not self.push_video_to_phone(local_path):
            self.update_item_status(item_id, "failed", "Failed to push video to phone")
            return False

        # Automate TikTok
        if not self.automate_tiktok_upload(local_path):
            self.update_item_status(item_id, "failed", "TikTok automation failed")
            return False

        self.update_item_status(item_id, "posted")
        return True

    def run(self):
        """Main loop."""
        if not POSTER_EMAIL or not POSTER_PASSWORD:
            print("ERROR: Set POSTER_EMAIL and POSTER_PASSWORD env vars")
            sys.exit(1)

        self.login()

        print(f"[POSTER] Starting — interval: {POST_INTERVAL}s")
        while True:
            try:
                connected = self.check_phone()
                self.update_phone_status(connected)

                if not connected:
                    print("[POSTER] No phone connected, waiting...")
                    time.sleep(30)
                    continue

                item = self.get_next_queued()
                if not item:
                    print("[POSTER] No items in queue, waiting...")
                    time.sleep(30)
                    continue

                print(f"[POSTER] Processing item {item['id']}")
                self.process_one(item)

                print(f"[POSTER] Waiting {POST_INTERVAL}s before next post...")
                time.sleep(POST_INTERVAL)

            except requests.exceptions.HTTPError as e:
                if e.response and e.response.status_code == 401:
                    print("[POSTER] Token expired, re-authenticating...")
                    self.login()
                else:
                    print(f"[POSTER] HTTP error: {e}")
                    time.sleep(30)
            except Exception as e:
                print(f"[POSTER] Error: {e}")
                time.sleep(30)


if __name__ == "__main__":
    poster = TikTokPoster()
    poster.run()
```

- [ ] **Step 2: Verify script syntax**

Run: `python -c "import ast; ast.parse(open('scripts/tiktok_poster.py').read()); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add scripts/tiktok_poster.py
git commit -m "feat: add ADB TikTok poster script with phone status reporting"
```

---

## Task 13: Final Integration & Manual Test

**Files:** None new — this is verification.

- [ ] **Step 1: Run all tests**

Run: `cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api" && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Start the server and test the full flow**

Run: `python -m uvicorn app.main:app --reload --port 8000`

Manual test checklist:
1. Open `http://localhost:8000/dashboard`
2. Login with credentials
3. Upload a source video
4. Select gameplay clips
5. Click Generate → verify jobs appear in Jobs tab
6. Wait for jobs to complete → verify they appear in Review Queue
7. Approve a video → verify it appears in Posting Queue
8. Reject a video → verify it disappears from Review Queue
9. Test drag-to-reorder in Posting Queue

- [ ] **Step 3: Commit any fixes from manual testing**

```bash
git add -A
git commit -m "fix: address issues found during integration testing"
```
