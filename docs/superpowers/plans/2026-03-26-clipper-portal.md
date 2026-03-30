# Clipper Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clipper distribution system where admin assigns finished videos to platform accounts, and clippers log into a separate portal to download, post, and submit links.

**Architecture:** New `Clipper`, `ClipperAccount`, and `ClipAssignment` models with separate auth. Admin manages clippers and creates assignments from the dashboard. Clippers use a standalone portal at `/clipper` with their own JWT auth. Backend is Python/FastAPI/SQLAlchemy, frontend is vanilla HTML/CSS/JS.

**Tech Stack:** FastAPI, SQLAlchemy, PyJWT, bcrypt, Alembic, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-26-clipper-portal-design.md`

---

## File Structure

### New files
- `app/models/clipper.py` — Clipper, ClipperAccount, ClipAssignment ORM models
- `app/schemas/clipper.py` — Pydantic request/response schemas
- `app/routes/clippers.py` — Admin CRUD routes for clippers and assignments
- `app/routes/clipper_portal.py` — Clipper-facing routes (assignments, submit)
- `app/static/clipper.html` — Clipper portal frontend (separate page)
- `migrations/versions/xxx_add_clippers.py` — Alembic migration

### Modified files
- `app/main.py` — register new routers, serve clipper.html
- `app/routes/auth.py` — add clipper login endpoint
- `app/dependencies.py` — add `get_current_clipper()`, guard `get_current_user()`
- `app/services/auth.py` — add `create_clipper_access_token()`
- `app/static/index.html` — ASSIGN button on results, CLIPPERS nav tab

---

### Task 1: Clipper models and migration

**Files:**
- Create: `app/models/clipper.py`

- [ ] **Step 1: Create the clipper models file**

```python
# app/models/clipper.py
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class AssignmentStatus(enum.Enum):
    assigned = "assigned"
    posted = "posted"


class Clipper(Base):
    __tablename__ = "clippers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    accounts: Mapped[list["ClipperAccount"]] = relationship(
        back_populates="clipper", cascade="all, delete-orphan"
    )


class ClipperAccount(Base):
    __tablename__ = "clipper_accounts"
    __table_args__ = (
        UniqueConstraint("clipper_id", "account_id", name="uq_clipper_account"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    clipper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clippers.id", ondelete="CASCADE")
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cluster_accounts.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    clipper: Mapped["Clipper"] = relationship(back_populates="accounts")
    account: Mapped["ClusterAccount"] = relationship()


class ClipAssignment(Base):
    __tablename__ = "clip_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cluster_accounts.id", ondelete="CASCADE")
    )
    video_key: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus), default=AssignmentStatus.assigned
    )
    post_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    account: Mapped["ClusterAccount"] = relationship()
```

- [ ] **Step 2: Generate Alembic migration**

```bash
cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api"
alembic revision --autogenerate -m "add clippers, clipper_accounts, clip_assignments tables"
```

Review the generated migration to ensure it creates all 3 tables with correct FKs and constraints.

- [ ] **Step 3: Run migration**

```bash
alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add app/models/clipper.py migrations/versions/
git commit -m "feat: add Clipper, ClipperAccount, ClipAssignment models and migration"
```

---

### Task 2: Clipper schemas

**Files:**
- Create: `app/schemas/clipper.py`

- [ ] **Step 1: Create the schemas file**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add app/schemas/clipper.py
git commit -m "feat: add clipper Pydantic schemas"
```

---

### Task 3: Clipper auth (token generation + dependencies)

**Files:**
- Modify: `app/services/auth.py`
- Modify: `app/dependencies.py`
- Modify: `app/routes/auth.py`

- [ ] **Step 1: Add clipper token generation to auth service**

In `app/services/auth.py`, add this function after `create_access_token`:

```python
def create_clipper_access_token(clipper_id: str, clipper_name: str) -> str:
    """Create a long-lived access token for a clipper (7 days)."""
    payload = {
        "sub": clipper_id,
        "type": "clipper",
        "name": clipper_name,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
```

- [ ] **Step 2: Guard get_current_user against clipper tokens**

In `app/dependencies.py`, update `get_current_user` to reject clipper tokens. Find the line after `payload = decode_access_token(...)` and add:

```python
    if payload.get("type") == "clipper":
        raise HTTPException(status_code=401, detail="Clipper tokens cannot access this endpoint")
```

- [ ] **Step 3: Add get_current_clipper dependency**

In `app/dependencies.py`, add after `get_current_user`:

```python
def get_current_clipper(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> "Clipper":
    from app.models.clipper import Clipper
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != "clipper":
        raise HTTPException(status_code=401, detail="Not a clipper token")
    clipper = db.query(Clipper).filter(Clipper.id == payload["sub"]).first()
    if not clipper or not clipper.is_active:
        raise HTTPException(status_code=401, detail="Clipper not found or inactive")
    return clipper
```

Add the necessary imports at the top of dependencies.py: `Session` from sqlalchemy.orm, `get_db` from app.database.

- [ ] **Step 4: Add clipper login endpoint to auth routes**

In `app/routes/auth.py`, add:

```python
@router.post("/clipper/login", response_model=ClipperTokenResponse)
def clipper_login(body: ClipperLoginRequest, db: Session = Depends(get_db)):
    from app.models.clipper import Clipper
    clipper = db.query(Clipper).filter(Clipper.email == body.email).first()
    if not clipper or not verify_password(body.password, clipper.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not clipper.is_active:
        raise HTTPException(status_code=401, detail="Account deactivated")
    token = create_clipper_access_token(clipper.id, clipper.name)
    return ClipperTokenResponse(access_token=token, name=clipper.name)
```

Add imports at the top: `ClipperLoginRequest`, `ClipperTokenResponse` from `app.schemas.clipper`, and `create_clipper_access_token` from `app.services.auth`.

- [ ] **Step 5: Commit**

```bash
git add app/services/auth.py app/dependencies.py app/routes/auth.py
git commit -m "feat: add clipper auth — token generation, dependencies, login endpoint"
```

---

### Task 4: Admin clipper management routes

**Files:**
- Create: `app/routes/clippers.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create clipper admin routes**

```python
# app/routes/clippers.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.clipper import Clipper, ClipperAccount, ClipAssignment, AssignmentStatus
from app.models.cluster import ClusterAccount, Cluster
from app.models.user import User
from app.schemas.clipper import (
    AssignmentListResponse,
    AssignmentResponse,
    ClipperDetailResponse,
    ClipperAccountResponse,
    ClipperListResponse,
    ClipperSummaryResponse,
    CreateAssignmentRequest,
    CreateClipperRequest,
    LinkAccountRequest,
)
from app.services.auth import hash_password
from app.storage import storage

router = APIRouter(prefix="/clippers", tags=["clippers"])


def _assignment_to_response(a: ClipAssignment) -> AssignmentResponse:
    download_url = storage.get_download_url(a.video_key) if a.video_key else None
    return AssignmentResponse(
        id=a.id,
        account_id=a.account_id,
        platform=a.account.platform.value if a.account else "",
        handle=a.account.handle if a.account else "",
        video_key=a.video_key,
        download_url=download_url,
        caption=a.caption,
        hashtags=a.hashtags,
        status=a.status.value,
        post_url=a.post_url,
        posted_at=a.posted_at.isoformat() if a.posted_at else None,
        created_at=a.created_at.isoformat(),
    )


# --- Clipper CRUD ---

@router.post("", response_model=ClipperDetailResponse, status_code=status.HTTP_201_CREATED)
def create_clipper(
    body: CreateClipperRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Clipper).filter(Clipper.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Clipper with this email already exists")
    clipper = Clipper(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
    )
    db.add(clipper)
    db.commit()
    db.refresh(clipper)
    return ClipperDetailResponse(
        id=clipper.id, email=clipper.email, name=clipper.name,
        is_active=clipper.is_active, accounts=[], created_at=clipper.created_at.isoformat(),
    )


@router.get("", response_model=ClipperListResponse)
def list_clippers(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clippers = db.query(Clipper).order_by(Clipper.created_at.desc()).all()
    return ClipperListResponse(clippers=[
        ClipperSummaryResponse(
            id=c.id, email=c.email, name=c.name, is_active=c.is_active,
            account_count=len(c.accounts), created_at=c.created_at.isoformat(),
        ) for c in clippers
    ])


@router.get("/{clipper_id}", response_model=ClipperDetailResponse)
def get_clipper(
    clipper_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clipper = db.query(Clipper).filter(Clipper.id == clipper_id).first()
    if not clipper:
        raise HTTPException(status_code=404, detail="Clipper not found")
    accounts = []
    for ca in clipper.accounts:
        acct = ca.account
        cluster = db.query(Cluster).filter(Cluster.id == acct.cluster_id).first() if acct else None
        accounts.append(ClipperAccountResponse(
            id=acct.id, platform=acct.platform.value, handle=acct.handle,
            cluster_name=cluster.name if cluster else "",
        ))
    return ClipperDetailResponse(
        id=clipper.id, email=clipper.email, name=clipper.name,
        is_active=clipper.is_active, accounts=accounts,
        created_at=clipper.created_at.isoformat(),
    )


@router.delete("/{clipper_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_clipper(
    clipper_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clipper = db.query(Clipper).filter(Clipper.id == clipper_id).first()
    if not clipper:
        raise HTTPException(status_code=404, detail="Clipper not found")
    clipper.is_active = False
    db.commit()


# --- Account linking ---

@router.post("/{clipper_id}/accounts", status_code=status.HTTP_201_CREATED)
def link_account(
    clipper_id: str,
    body: LinkAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clipper = db.query(Clipper).filter(Clipper.id == clipper_id).first()
    if not clipper:
        raise HTTPException(status_code=404, detail="Clipper not found")
    account = db.query(ClusterAccount).filter(ClusterAccount.id == body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    existing = db.query(ClipperAccount).filter(
        ClipperAccount.clipper_id == clipper_id,
        ClipperAccount.account_id == body.account_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Account already linked")
    link = ClipperAccount(clipper_id=clipper_id, account_id=body.account_id)
    db.add(link)
    db.commit()
    return {"status": "linked"}


@router.delete("/{clipper_id}/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_account(
    clipper_id: str,
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    link = db.query(ClipperAccount).filter(
        ClipperAccount.clipper_id == clipper_id,
        ClipperAccount.account_id == account_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()


# --- Assignments (admin) ---

assignments_router = APIRouter(prefix="/assignments", tags=["assignments"])


@assignments_router.post("", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(
    body: CreateAssignmentRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    assignment = ClipAssignment(
        account_id=body.account_id,
        video_key=body.video_key,
        caption=body.caption,
        hashtags=body.hashtags,
        created_by=user.id,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return _assignment_to_response(assignment)


@assignments_router.get("", response_model=AssignmentListResponse)
def list_assignments(
    status_filter: str | None = Query(None, alias="status"),
    account_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ClipAssignment).order_by(ClipAssignment.created_at.desc())
    if status_filter:
        query = query.filter(ClipAssignment.status == AssignmentStatus(status_filter))
    if account_id:
        query = query.filter(ClipAssignment.account_id == account_id)
    assignments = query.limit(100).all()
    return AssignmentListResponse(
        assignments=[_assignment_to_response(a) for a in assignments]
    )
```

- [ ] **Step 2: Register routers in main.py**

In `app/main.py`, add after the existing router imports:

```python
from app.routes.clippers import router as clippers_router, assignments_router
```

And in the router registration section:

```python
app.include_router(clippers_router)
app.include_router(assignments_router)
```

- [ ] **Step 3: Commit**

```bash
git add app/routes/clippers.py app/main.py
git commit -m "feat: add admin clipper management and assignment routes"
```

---

### Task 5: Clipper portal routes

**Files:**
- Create: `app/routes/clipper_portal.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create clipper portal routes**

```python
# app/routes/clipper_portal.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_clipper
from app.models.clipper import Clipper, ClipperAccount, ClipAssignment, AssignmentStatus
from app.schemas.clipper import AssignmentListResponse, AssignmentResponse, SubmitPostRequest
from app.storage import storage

router = APIRouter(prefix="/clipper", tags=["clipper-portal"])


def _assignment_to_response(a: ClipAssignment) -> AssignmentResponse:
    download_url = storage.get_download_url(a.video_key) if a.video_key else None
    return AssignmentResponse(
        id=a.id,
        account_id=a.account_id,
        platform=a.account.platform.value if a.account else "",
        handle=a.account.handle if a.account else "",
        video_key=a.video_key,
        download_url=download_url,
        caption=a.caption,
        hashtags=a.hashtags,
        status=a.status.value,
        post_url=a.post_url,
        posted_at=a.posted_at.isoformat() if a.posted_at else None,
        created_at=a.created_at.isoformat(),
    )


@router.get("/assignments", response_model=AssignmentListResponse)
def get_clipper_assignments(
    clipper: Clipper = Depends(get_current_clipper),
    db: Session = Depends(get_db),
):
    # Only assignments for accounts linked to this clipper
    assignments = (
        db.query(ClipAssignment)
        .join(ClipperAccount, ClipperAccount.account_id == ClipAssignment.account_id)
        .filter(ClipperAccount.clipper_id == clipper.id)
        .order_by(ClipAssignment.created_at.desc())
        .all()
    )
    return AssignmentListResponse(
        assignments=[_assignment_to_response(a) for a in assignments]
    )


@router.put("/assignments/{assignment_id}/submit")
def submit_post_link(
    assignment_id: str,
    body: SubmitPostRequest,
    clipper: Clipper = Depends(get_current_clipper),
    db: Session = Depends(get_db),
):
    # Verify assignment exists and clipper owns the account
    assignment = db.query(ClipAssignment).filter(ClipAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Check clipper is linked to this account
    link = db.query(ClipperAccount).filter(
        ClipperAccount.clipper_id == clipper.id,
        ClipperAccount.account_id == assignment.account_id,
    ).first()
    if not link:
        raise HTTPException(status_code=403, detail="You are not assigned to this account")

    assignment.post_url = body.post_url
    assignment.status = AssignmentStatus.posted
    assignment.posted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assignment)
    return _assignment_to_response(assignment)
```

- [ ] **Step 2: Register clipper portal router in main.py**

In `app/main.py`, add:

```python
from app.routes.clipper_portal import router as clipper_portal_router
```

And:

```python
app.include_router(clipper_portal_router)
```

- [ ] **Step 3: Commit**

```bash
git add app/routes/clipper_portal.py app/main.py
git commit -m "feat: add clipper portal routes — assignments list and submit"
```

---

### Task 6: Serve clipper portal HTML and add ASSIGN button to admin dashboard

**Files:**
- Modify: `app/main.py` — serve clipper.html at `/clipper`
- Modify: `app/static/index.html` — add ASSIGN button + modal to pipeline results

- [ ] **Step 1: Add clipper.html route to main.py**

In `app/main.py`, add a route to serve the clipper page. Add after the existing `"/"` route:

```python
@app.get("/clipper", include_in_schema=False)
def clipper_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "clipper.html"))
```

Make sure `FileResponse` is imported: `from starlette.responses import FileResponse`

- [ ] **Step 2: Add ASSIGN button to renderPipelineResults in index.html**

In `app/static/index.html`, find the `renderPipelineResults` function. In the dubbing result row where WATCH and DL buttons are rendered, add an ASSIGN button after the DL link. Find:

```javascript
`<a href="${o.download_url}" download>DL</a>` : ''}
```

in the dubbing section and add after the DL link (but still inside the completed check):

```javascript
<button onclick="event.stopPropagation(); openAssignModal('${o.download_url}', '${a.video_key || ''}')" style="background:#1a1a1a;border:1px solid #2a2a2a;color:#888;padding:5px 10px;border-radius:3px;cursor:pointer;font-family:inherit;font-size:11px;">ASSIGN</button>
```

Do the same for the splitscreen result row — find the `j.output_url` WATCH/DL section and add:

```javascript
<button onclick="event.stopPropagation(); openAssignModal('${j.output_url}', '${j.source_video_key || ''}')" style="background:#1a1a1a;border:1px solid #2a2a2a;color:#888;padding:5px 10px;border-radius:3px;cursor:pointer;font-family:inherit;font-size:11px;">ASSIGN</button>
```

Note: For splitscreen jobs, the `video_key` needs to come from the job response. The job response has `output_video_key` or similar. Check the actual field name from the job response — it may need to be the output storage key. Use the URL for now as the video_key if needed.

- [ ] **Step 3: Add assign modal HTML**

In `app/static/index.html`, add this modal HTML before the closing `</div>` of the app div (before the video preview modal):

```html
<!-- Assign modal -->
<div class="modal-overlay" id="assignModal">
  <div class="modal-body" style="background:#0a0a0a;border:1px solid #1a1a1a;border-radius:8px;padding:32px;width:500px;max-width:90vw;" onclick="event.stopPropagation()">
    <h3 style="font-size:18px;font-weight:700;margin-bottom:24px;color:#fff;">ASSIGN TO CHANNEL</h3>
    <input type="hidden" id="assignVideoKey">
    <div class="form-group" style="margin-bottom:20px;">
      <label style="display:block;font-size:11px;color:#666;margin-bottom:6px;letter-spacing:1px;">ACCOUNT</label>
      <select id="assignAccountSelect" style="width:100%;background:#141414;border:1px solid #2a2a2a;color:#e0e0e0;padding:12px 14px;font-family:inherit;font-size:13px;border-radius:4px;outline:none;">
        <option value="">-- Select account --</option>
      </select>
    </div>
    <div class="form-group" style="margin-bottom:20px;">
      <label style="display:block;font-size:11px;color:#666;margin-bottom:6px;letter-spacing:1px;">CAPTION</label>
      <textarea id="assignCaption" rows="4" style="width:100%;background:#141414;border:1px solid #2a2a2a;color:#e0e0e0;padding:12px 14px;font-family:inherit;font-size:13px;border-radius:4px;outline:none;resize:vertical;" placeholder="Write the post caption..."></textarea>
    </div>
    <div class="form-group" style="margin-bottom:20px;">
      <label style="display:block;font-size:11px;color:#666;margin-bottom:6px;letter-spacing:1px;">HASHTAGS</label>
      <input type="text" id="assignHashtags" style="width:100%;background:#141414;border:1px solid #2a2a2a;color:#e0e0e0;padding:12px 14px;font-family:inherit;font-size:13px;border-radius:4px;outline:none;" placeholder="#topic #niche #viral">
    </div>
    <div class="modal-actions" style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-secondary" onclick="closeAssignModal()">CANCEL</button>
      <button class="btn" onclick="submitAssignment()">ASSIGN</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add assign modal JS**

Add these functions in the JS section of index.html:

```javascript
// --- Assign modal ---
async function openAssignModal(downloadUrl, videoKey) {
  // Use the storage path from the download URL if no videoKey
  if (!videoKey && downloadUrl) {
    // Extract storage key from URL like /storage/dubbing/job-id/lang/output.mp4
    const match = downloadUrl.match(/\/storage\/(.+)$/);
    videoKey = match ? match[1] : downloadUrl;
  }
  document.getElementById('assignVideoKey').value = videoKey || '';
  document.getElementById('assignCaption').value = '';
  document.getElementById('assignHashtags').value = '';

  // Load all cluster accounts
  const select = document.getElementById('assignAccountSelect');
  select.innerHTML = '<option value="">-- Select account --</option>';
  try {
    const resp = await api('/clusters');
    const data = await resp.json();
    for (const cluster of (data.clusters || [])) {
      const detailResp = await api(`/clusters/${cluster.id}`);
      const detail = await detailResp.json();
      for (const acct of (detail.accounts || [])) {
        select.innerHTML += `<option value="${acct.id}">${acct.platform.toUpperCase()} — ${acct.handle} (${cluster.name})</option>`;
      }
    }
  } catch(e) { console.error('Failed to load accounts', e); }

  document.getElementById('assignModal').classList.add('active');
}

function closeAssignModal() {
  document.getElementById('assignModal').classList.remove('active');
}

async function submitAssignment() {
  const videoKey = document.getElementById('assignVideoKey').value;
  const accountId = document.getElementById('assignAccountSelect').value;
  const caption = document.getElementById('assignCaption').value;
  const hashtags = document.getElementById('assignHashtags').value;

  if (!accountId) return alert('Select an account');
  if (!videoKey) return alert('No video to assign');

  try {
    const resp = await api('/assignments', {
      method: 'POST',
      body: JSON.stringify({ video_key: videoKey, account_id: accountId, caption, hashtags })
    });
    if (resp.ok) {
      closeAssignModal();
      alert('Assigned!');
    } else {
      const data = await resp.json();
      alert(data.detail || 'Failed to assign');
    }
  } catch(e) {
    alert('Error: ' + e.message);
  }
}

// Close assign modal on backdrop click
document.getElementById('assignModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeAssignModal();
});
```

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/static/index.html
git commit -m "feat: add ASSIGN button to pipeline results and assign modal"
```

---

### Task 7: CLIPPERS nav tab on admin dashboard

**Files:**
- Modify: `app/static/index.html`

- [ ] **Step 1: Add CLIPPERS nav tab**

In the nav tabs HTML, add a CLIPPERS tab after the CLUSTERS tab:

```html
<button class="nav-tab" onclick="switchView('clippers')" id="tabClippers">CLIPPERS</button>
```

- [ ] **Step 2: Add clippers view container HTML**

Add after the clusters view container (before the closing `</div>` of the app):

```html
<!-- Clippers view -->
<div class="view-container" id="clippersView">
  <div class="container">
    <div id="clipperListView">
      <div class="clusters-header">
        <h2>Clippers</h2>
        <button class="btn" onclick="openCreateClipperModal()">CREATE CLIPPER</button>
      </div>
      <div id="clippersList"></div>
      <p id="noClippersMsg" style="display:none; color:#555; font-size:13px; text-align:center; padding:40px 0;">No clippers yet. Create one to start distributing content.</p>

      <div style="margin-top:32px;">
        <div class="section-title">RECENT ASSIGNMENTS</div>
        <div id="adminAssignmentsList"></div>
      </div>
    </div>

    <!-- Clipper detail -->
    <div id="clipperDetailView" style="display:none;">
      <div class="cluster-detail-header">
        <button class="back-btn" onclick="showClipperList()">&lt; BACK</button>
        <h2 id="clipperDetailName"></h2>
      </div>
      <div class="section-title">LINKED ACCOUNTS <button onclick="toggleLinkAccountForm()">+ LINK ACCOUNT</button></div>
      <div class="add-account-form" id="linkAccountForm">
        <select id="linkAccountSelect" style="flex:1;background:#0a0a0a;border:1px solid #2a2a2a;color:#e0e0e0;padding:10px 12px;font-family:inherit;font-size:13px;border-radius:4px;"></select>
        <button class="btn" style="padding:10px 18px;" onclick="linkAccountToClipper()">LINK</button>
      </div>
      <div id="clipperAccountsList"></div>
      <div style="margin-top:24px;">
        <div class="section-title">ASSIGNMENTS</div>
        <div id="clipperAssignmentsList"></div>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add create clipper modal HTML**

Add before the closing `</body>`:

```html
<!-- Create Clipper modal -->
<div class="create-cluster-modal" id="createClipperModal">
  <div class="modal-body">
    <h3>CREATE CLIPPER</h3>
    <div class="form-group">
      <label>NAME</label>
      <input type="text" id="newClipperName" placeholder="e.g. John">
    </div>
    <div class="form-group">
      <label>EMAIL</label>
      <input type="email" id="newClipperEmail" placeholder="clipper@example.com">
    </div>
    <div class="form-group">
      <label>PASSWORD</label>
      <input type="password" id="newClipperPassword" placeholder="min 8 characters">
    </div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeCreateClipperModal()">CANCEL</button>
      <button class="btn" onclick="createClipper()">CREATE</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Update switchView to handle clippers tab**

In the `switchView` function, add a case for 'clippers':

```javascript
} else if (view === 'clippers') {
    document.getElementById('tabClippers').classList.add('active');
    document.getElementById('clippersView').classList.add('active');
    loadClippers();
}
```

- [ ] **Step 5: Add clipper management JS functions**

```javascript
// --- Clippers ---
let currentClipperId = null;

async function loadClippers() {
  try {
    const resp = await api('/clippers');
    const data = await resp.json();
    const clippers = data.clippers || [];
    const el = document.getElementById('clippersList');
    const noMsg = document.getElementById('noClippersMsg');

    if (clippers.length === 0) {
      el.innerHTML = '';
      noMsg.style.display = 'block';
    } else {
      noMsg.style.display = 'none';
      el.innerHTML = clippers.map(c => `
        <div class="cluster-card" onclick="openClipperDetail('${c.id}')" style="margin-bottom:12px;">
          <div class="cluster-name">${c.name}</div>
          <div class="cluster-meta">${c.email} — ${c.account_count} account${c.account_count !== 1 ? 's' : ''} ${!c.is_active ? '(inactive)' : ''}</div>
        </div>
      `).join('');
    }

    // Load recent assignments
    const aResp = await api('/assignments?limit=20');
    const aData = await aResp.json();
    const alist = document.getElementById('adminAssignmentsList');
    if ((aData.assignments || []).length === 0) {
      alist.innerHTML = '<p style="color:#555;font-size:13px;">No assignments yet.</p>';
    } else {
      alist.innerHTML = (aData.assignments || []).map(a => `
        <div class="job-row">
          <div class="dot ${a.status === 'posted' ? 'completed' : 'pending'}"></div>
          <div class="account-platform ${a.platform}" style="background:#1a1a1a;padding:4px 8px;border-radius:3px;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;">${a.platform}</div>
          <div style="flex:1;color:#ccc;">${a.handle} — ${a.caption.substring(0,40)}${a.caption.length > 40 ? '...' : ''}</div>
          <div style="color:#666;font-size:12px;">${a.status}</div>
          ${a.post_url ? `<a href="${a.post_url}" target="_blank" style="color:#ff3a2f;font-size:11px;">VIEW POST</a>` : ''}
        </div>
      `).join('');
    }
  } catch(e) { console.error('Failed to load clippers', e); }
}

async function openClipperDetail(id) {
  currentClipperId = id;
  document.getElementById('clipperListView').style.display = 'none';
  document.getElementById('clipperDetailView').style.display = 'block';
  await refreshClipperDetail();
}

async function refreshClipperDetail() {
  if (!currentClipperId) return;
  try {
    const resp = await api(`/clippers/${currentClipperId}`);
    const c = await resp.json();
    document.getElementById('clipperDetailName').textContent = `${c.name} (${c.email})`;

    // Accounts
    const acctEl = document.getElementById('clipperAccountsList');
    if (c.accounts.length === 0) {
      acctEl.innerHTML = '<p style="color:#555;font-size:13px;padding:8px 0;">No linked accounts.</p>';
    } else {
      acctEl.innerHTML = c.accounts.map(a => `
        <div class="account-card-wrap" style="margin-bottom:8px;">
          <div class="account-card-top">
            <div class="account-platform ${a.platform}">${a.platform}</div>
            <div class="account-handle">${a.handle}</div>
            <div style="font-size:11px;color:#555;">${a.cluster_name}</div>
            <button class="account-remove" onclick="unlinkAccount('${a.id}')">X</button>
          </div>
        </div>
      `).join('');
    }

    // Assignments for this clipper's accounts
    const assignEl = document.getElementById('clipperAssignmentsList');
    // Fetch all assignments and filter by this clipper's account IDs
    const accountIds = new Set(c.accounts.map(a => a.id));
    const aResp = await api('/assignments');
    const aData = await aResp.json();
    const relevant = (aData.assignments || []).filter(a => accountIds.has(a.account_id));
    if (relevant.length === 0) {
      assignEl.innerHTML = '<p style="color:#555;font-size:13px;">No assignments.</p>';
    } else {
      assignEl.innerHTML = relevant.map(a => `
        <div class="job-row">
          <div class="dot ${a.status === 'posted' ? 'completed' : 'pending'}"></div>
          <div style="flex:1;color:#ccc;">${a.handle} — ${a.caption.substring(0,40)}</div>
          <div style="color:#666;font-size:12px;">${a.status}</div>
          ${a.post_url ? `<a href="${a.post_url}" target="_blank" style="color:#ff3a2f;font-size:11px;">VIEW</a>` : ''}
        </div>
      `).join('');
    }
  } catch(e) { console.error('Failed to load clipper detail', e); }
}

function showClipperList() {
  currentClipperId = null;
  document.getElementById('clipperDetailView').style.display = 'none';
  document.getElementById('linkAccountForm').classList.remove('visible');
  document.getElementById('clipperListView').style.display = 'block';
  loadClippers();
}

function toggleLinkAccountForm() {
  const form = document.getElementById('linkAccountForm');
  form.classList.toggle('visible');
  if (form.classList.contains('visible')) loadAccountOptions();
}

async function loadAccountOptions() {
  const select = document.getElementById('linkAccountSelect');
  select.innerHTML = '<option value="">-- Select account --</option>';
  try {
    const resp = await api('/clusters');
    const data = await resp.json();
    for (const cluster of (data.clusters || [])) {
      const dr = await api(`/clusters/${cluster.id}`);
      const d = await dr.json();
      for (const acct of (d.accounts || [])) {
        select.innerHTML += `<option value="${acct.id}">${acct.platform.toUpperCase()} — ${acct.handle} (${cluster.name})</option>`;
      }
    }
  } catch(e) {}
}

async function linkAccountToClipper() {
  if (!currentClipperId) return;
  const accountId = document.getElementById('linkAccountSelect').value;
  if (!accountId) return;
  try {
    await api(`/clippers/${currentClipperId}/accounts`, {
      method: 'POST', body: JSON.stringify({ account_id: accountId })
    });
    document.getElementById('linkAccountForm').classList.remove('visible');
    await refreshClipperDetail();
  } catch(e) { console.error('Failed to link account', e); }
}

async function unlinkAccount(accountId) {
  if (!currentClipperId) return;
  try {
    await api(`/clippers/${currentClipperId}/accounts/${accountId}`, { method: 'DELETE' });
    await refreshClipperDetail();
  } catch(e) { console.error('Failed to unlink account', e); }
}

// Create clipper modal
function openCreateClipperModal() {
  document.getElementById('newClipperName').value = '';
  document.getElementById('newClipperEmail').value = '';
  document.getElementById('newClipperPassword').value = '';
  document.getElementById('createClipperModal').classList.add('active');
}

function closeCreateClipperModal() {
  document.getElementById('createClipperModal').classList.remove('active');
}

async function createClipper() {
  const name = document.getElementById('newClipperName').value.trim();
  const email = document.getElementById('newClipperEmail').value.trim();
  const password = document.getElementById('newClipperPassword').value;
  if (!name || !email || !password) return;
  try {
    const resp = await api('/clippers', {
      method: 'POST', body: JSON.stringify({ name, email, password })
    });
    if (resp.ok) {
      closeCreateClipperModal();
      loadClippers();
    } else {
      const data = await resp.json();
      alert(data.detail || 'Failed');
    }
  } catch(e) { alert('Error: ' + e.message); }
}

// Close modal on backdrop
document.getElementById('createClipperModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeCreateClipperModal();
});
```

- [ ] **Step 6: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add CLIPPERS nav tab with clipper management and assignment list"
```

---

### Task 8: Clipper portal frontend

**Files:**
- Create: `app/static/clipper.html`

- [ ] **Step 1: Create the clipper portal HTML**

Create `app/static/clipper.html` — a self-contained page with login, assignment list, download, and submit link functionality. This is a standalone page that uses the same dark theme as the admin dashboard but is much simpler.

The page should include:
- Login form (email + password) → `POST /auth/clipper/login`
- After login, fetch assignments via `GET /clipper/assignments` with Bearer token
- Group assignments by account (platform + handle)
- Each assignment shows: caption (copyable), hashtags (copyable), DOWNLOAD button, WATCH button, and SUBMIT LINK input
- Submit link calls `PUT /clipper/assignments/{id}/submit`
- Store JWT in memory (not localStorage for security), clipper name from login response
- Same dark theme, JetBrains Mono font, #ff3a2f accent color

The HTML file should be complete and self-contained (~300-400 lines). Follow the CLAUDE.md brand guidelines: intense, professional, dark theme with #ff3a2f accents, JetBrains Mono font.

- [ ] **Step 2: Commit**

```bash
git add app/static/clipper.html
git commit -m "feat: add clipper portal frontend at /clipper"
```

---

### Task 9: End-to-end verification

- [ ] **Step 1: Start the server and test the full flow**

```bash
cd "/Users/harry/Desktop/life/Project Folders/armageddon/arm-api"
uvicorn app.main:app --reload
```

Test:
1. Login as admin
2. Go to CLIPPERS tab → Create a clipper
3. Click the clipper → Link an account from a cluster
4. Run a pipeline (extract + dub/splitscreen)
5. On results, click ASSIGN on a completed video → pick the account, write caption + hashtags
6. Open `/clipper` in a new browser/incognito
7. Login as the clipper
8. See the assignment with caption + hashtags
9. Download the video
10. Submit a post link
11. Go back to admin → CLIPPERS tab → verify the assignment shows as "posted" with the link

- [ ] **Step 2: Commit any fixes**

```bash
git add -A
git commit -m "fix: end-to-end clipper portal fixes"
```
