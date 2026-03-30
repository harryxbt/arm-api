# Clipper Portal Design

**Date:** 2026-03-26
**Status:** Approved

## Overview

Add a clipper distribution system where the admin assigns finished videos to platform accounts with captions and hashtags, and clippers log in to a separate portal to download videos, post them, and submit the post link back.

## Actors

- **Admin** — the existing user (Harry). Extracts clips, runs pipeline, assigns finished videos to channels.
- **Clipper** — separate account type. Linked to specific cluster accounts. Downloads assigned videos, posts them, submits the post link.

## Data Model

### Clipper (new table: `clippers`)
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| email | string | Unique, used for login |
| password_hash | string | bcrypt |
| name | string | Display name |
| is_active | bool | Default true |
| created_at | datetime | |

No credits, no Stripe — clippers don't pay, they just do work.

### ClipperAccount (new table: `clipper_accounts`)
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| clipper_id | UUID | FK → clippers, ondelete CASCADE |
| account_id | UUID | FK → cluster_accounts, ondelete CASCADE |
| created_at | datetime | |

Links a clipper to one or more cluster accounts. A clipper only sees assignments for accounts they're linked to. Unique constraint on (clipper_id, account_id).

### ClipAssignment (new table: `clip_assignments`)
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| account_id | UUID | FK → cluster_accounts, ondelete CASCADE |
| video_key | string | Storage key of the finished video |
| caption | text | Caption text for the post |
| hashtags | text | Hashtags string |
| status | enum | `assigned` or `posted` |
| post_url | string, nullable | Submitted by clipper after posting |
| posted_at | datetime, nullable | When clipper submitted the link |
| created_by | UUID | FK → users, ondelete SET NULL, nullable |
| created_at | datetime | |
| updated_at | datetime | Auto-updated on change |

Note: `download_url` is not stored — it is generated from `video_key` via `storage.get_download_url()` at read time, included in the API response schema only.

### Cascade behavior
- Deleting a clipper cascades to `clipper_accounts` (link rows removed, assignments remain on the account)
- Deleting a cluster account cascades to both `clipper_accounts` and `clip_assignments` for that account
- Deleting the admin user sets `created_by` to NULL (preserves assignment history)
- Unlinking a clipper from an account (`DELETE /clippers/{id}/accounts/{account_id}`) is allowed even with pending assignments — the assignments remain on the account and become visible to any clipper later linked to that account. Admin can always see them via `GET /assignments`.

### Status Flow
```
assigned → posted
```
- `assigned`: admin created the assignment, clipper can see it
- `posted`: clipper submitted the post link

## Admin Side

### Assignment from Step 4 Results

On the pipeline results view (step 4), each completed video row gets an **ASSIGN** button next to WATCH and DL.

Clicking ASSIGN opens a modal:
- **Account picker** — dropdown of all cluster accounts (across all clusters). Shows "platform — @handle (cluster name)".
- **Caption** — textarea
- **Hashtags** — text input
- **ASSIGN** button — creates the assignment via `POST /assignments`

Assigning to an account with no linked clipper is allowed — admin can link a clipper later.

### Clipper Management

Add a **CLIPPERS** nav tab to the admin dashboard with:
- List of clippers with their assigned accounts
- "CREATE CLIPPER" button → modal with email, password, name
- Click a clipper → see their accounts, add/remove accounts
- Also show their recent assignments and statuses

### Assignment List

Admin can see all assignments from the CLIPPERS tab:
- Grouped by account or by clipper
- Shows status (assigned/posted), post link if submitted
- Filter by status

## Clipper Side

### Separate page: `/clipper`

A separate HTML file (`app/static/clipper.html`) served at `/clipper`. Completely independent from the admin dashboard.

### Login
- Email + password form
- Uses `POST /auth/clipper/login` endpoint
- Returns a JWT with clipper identity including `name` in payload
- Token payload: `{ "sub": clipper_id, "type": "clipper", "name": clipper_name }`
- No refresh tokens for clippers — access tokens only, long-lived (7 days). Clippers re-login when expired.

### Dashboard
After login, the clipper sees:

**Header:** "ARMAGEDDON" + clipper name (read from JWT payload, no `/me` endpoint needed)

**Assignment list** grouped by account:
```
@finance_tiktok (TikTok)
├── "The secret to scaling..." — assigned
│   Caption: "This changed everything..."
│   Hashtags: #finance #money #investing
│   [DOWNLOAD] [SUBMIT LINK]
└── "Why most people fail..." — posted
    Post: https://tiktok.com/@finance/video/123

@finance_youtube (YouTube)
└── "Top 5 mistakes..." — assigned
    Caption: "Watch till the end..."
    [DOWNLOAD] [SUBMIT LINK]
```

**Per assignment:**
- Video preview (WATCH button)
- Caption text (copyable)
- Hashtags (copyable)
- Platform + account handle
- DOWNLOAD button — uses the `download_url` from the assignment response (generated from `video_key` via `storage.get_download_url()`)
- SUBMIT LINK — text input + submit button. Once submitted, status changes to `posted` and the row shows the post URL.

## API Endpoints

### Admin endpoints (require admin user auth)

| Method | Path | Description |
|--------|------|-------------|
| POST | /clippers | Create a new clipper |
| GET | /clippers | List all clippers |
| GET | /clippers/{id} | Get clipper detail with linked accounts |
| DELETE | /clippers/{id} | Soft-delete: sets `is_active = false` |
| POST | /clippers/{id}/accounts | Link clipper to a cluster account |
| DELETE | /clippers/{id}/accounts/{account_id} | Unlink clipper from account |
| POST | /assignments | Create assignment (video_key, account_id, caption, hashtags) |
| GET | /assignments | List all assignments (optional filters: status, account_id) |

### Clipper endpoints (require clipper auth)

| Method | Path | Description |
|--------|------|-------------|
| POST | /auth/clipper/login | Clipper login, returns JWT with name + type |
| GET | /clipper/assignments | List assignments for clipper's linked accounts |
| PUT | /clipper/assignments/{id}/submit | Submit post link (must verify clipper owns the account) |

### Auth separation

**JWT tokens:**
- Admin tokens: payload `{ "sub": user_id }` — no `type` field (backward compatible with existing tokens)
- Clipper tokens: payload `{ "sub": clipper_id, "type": "clipper", "name": clipper_name }` — 7 day expiry, no refresh

**Dependencies:**
- `get_current_user()` — existing function. Add a guard: reject tokens that have `type: "clipper"`. Accept tokens with no `type` field (backward compat) or `type: "admin"`.
- `get_current_clipper()` — new function. Require `type: "clipper"` in payload. Look up clipper in `clippers` table. Reject if `is_active = false`.

**Security on clipper endpoints:**
- `GET /clipper/assignments` must join through `clipper_accounts` to scope to the clipper's accounts:
  ```sql
  SELECT a.* FROM clip_assignments a
  JOIN clipper_accounts ca ON ca.account_id = a.account_id
  WHERE ca.clipper_id = :current_clipper_id AND a.status = :filter
  ```
- `PUT /clipper/assignments/{id}/submit` must verify the assignment's `account_id` is in the clipper's linked accounts before allowing the update.

## File Structure

### New files
- `app/models/clipper.py` — Clipper, ClipperAccount, ClipAssignment models
- `app/schemas/clipper.py` — Request/response schemas
- `app/routes/clippers.py` — Admin clipper management routes
- `app/routes/clipper_portal.py` — Clipper-facing routes
- `app/static/clipper.html` — Clipper portal frontend
- `migrations/versions/xxx_add_clippers.py` — Alembic migration

### Modified files
- `app/main.py` — register new routers, mount clipper.html
- `app/routes/auth.py` — add clipper login endpoint
- `app/dependencies.py` — add `get_current_clipper()`, guard `get_current_user()` against clipper tokens
- `app/static/index.html` — add ASSIGN button to results, CLIPPERS tab, clipper management UI
- `app/services/auth.py` — add clipper token generation with type claim

## Scope

### In scope
- Clipper CRUD (admin creates/manages, soft-delete)
- Clipper <> account linking
- Assignment creation from pipeline results
- Clipper portal (login, view assignments, download, submit link)
- Assignment status tracking (assigned -> posted)
- Admin view of all assignments
- CLIPPERS nav tab on admin dashboard
- Auth separation (clipper vs admin JWT)

### Out of scope
- Clipper self-registration
- Clipper refresh tokens
- Assignment notifications (email/push)
- Auto-posting to platforms
- Performance analytics per clipper
- Bulk assignment
- Assignment deadlines/scheduling
- Duplicate assignment prevention (same video + same account)
