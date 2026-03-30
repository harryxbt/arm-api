# Armageddon Dashboard UI — Design Spec

## Overview

Internal single-page dashboard for managing the full video multiplication pipeline: upload source videos, pair with gameplay clips, generate splitscreen variations, review outputs, and queue them for automated TikTok posting via an ADB-controlled Samsung phone.

Runs locally at `localhost`, served from the FastAPI app. Single self-contained HTML file — vanilla HTML/CSS/JS with Tailwind via CDN. Dark theme, JetBrains Mono font, functional and dense.

## User & Context

- Single internal user (the operator)
- Runs on the same machine as the API (`localhost:8000`)
- Samsung phone connected via USB for TikTok automation
- Workflow: upload → generate → review → post

---

## Architecture

### Frontend
- Single HTML file served by FastAPI at `/dashboard` (same-origin, no CORS issues)
- Four tabbed views: Upload & Generate, Jobs, Review Queue, Posting Queue
- Polls API on active tab only: Jobs and Posting Queue every 5s, Phone Status every 10s
- Talks to existing API + new posting queue endpoints

### Authentication Strategy
- Dashboard served at same origin as API (`localhost:8000`)
- On load, dashboard shows a simple login form (email + password)
- Calls `POST /auth/login`, stores the returned `access_token` in memory (JS variable)
- All subsequent API calls include `Authorization: Bearer {token}` header
- On 401 response, attempts refresh via `POST /auth/refresh` (cookie-based), then re-login if that fails
- No hardcoded tokens — uses existing auth system as-is

### New API Endpoints

#### `POST /posting-queue`
Add an approved video to the posting queue.
- **Request:** `{ "job_id": "uuid", "caption_text": "optional string" }`
- **Response (201):** `{ "id": "uuid", "job_id": "uuid", "status": "queued", "position": 5, "caption_text": null, "created_at": "..." }`
- **Errors:** 404 if job not found, 409 if job already in queue, 400 if job not completed

#### `GET /posting-queue`
List posting queue items, ordered by position.
- **Query params:** `status` (optional filter: queued / posting / posted / failed)
- **Response (200):** `[{ "id", "job_id", "status", "position", "caption_text", "posted_at", "error_message", "created_at", "output_url", "source_video_name", "gameplay_name" }, ...]`

#### `PATCH /posting-queue/{id}`
Update a queue item's status, position, or caption.
- **Request:** `{ "status?": "queued|posting|posted|failed", "position?": 3, "caption_text?": "new caption", "error_message?": "..." }`
- **Response (200):** Updated item object
- **Errors:** 404 if not found, 400 if invalid status transition (e.g., posted → queued)

#### `POST /posting-queue/reorder`
Batch reorder queue items (for drag-and-drop).
- **Request:** `{ "order": [{ "id": "uuid", "position": 1 }, { "id": "uuid", "position": 2 }, ...] }`
- **Response (200):** `{ "ok": true }`

#### `DELETE /posting-queue/{id}`
Remove an item from the queue. Cannot delete items with status `posting`.
- **Response (204):** No content
- **Errors:** 404 if not found, 409 if currently posting

#### `GET /phone/status`
Get ADB phone connection status. FastAPI shells out to `adb devices` and reads a status file written by the poster script.
- **Response (200):** `{ "connected": true, "activity": "Idle", "last_checked": "2026-03-22T..." }`

### New DB Model: PostingQueueItem
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| job_id | UUID (FK) | Reference to completed job |
| status | Enum | queued / posting / posted / failed |
| position | Integer | Queue order |
| caption_text | Text (nullable) | TikTok post caption |
| posted_at | DateTime (nullable) | When successfully posted |
| error_message | Text (nullable) | Failure details |
| created_at | DateTime | When added to queue |
| updated_at | DateTime | Last status change |

### ADB Automation Script
- Separate Python process (`scripts/tiktok_poster.py`)
- Authenticates with API using email/password from env vars, holds JWT token
- Polls `GET /posting-queue?status=queued` for next item
- Calls `PATCH /posting-queue/{id}` to set status to `posting`
- Downloads video from `output_url`, pushes to phone via `adb push`
- Automates TikTok app via ADB shell input (tap coordinates, UI Automator)
- Calls `PATCH /posting-queue/{id}` to set status to `posted` or `failed`
- Configurable delay between posts to avoid rate limiting (env var `POST_INTERVAL_SECONDS`, default 1800)
- Writes phone status to a JSON file (`storage/phone_status.json`) — FastAPI reads this file for `GET /phone/status`
- Periodically checks `adb devices` and updates the status file

---

## View 1: Upload & Generate

### Layout
Two panels side by side.

### Left Panel — Source Videos
- Drag-and-drop zone (or click to browse) for uploading multiple source videos
- Uploaded files appear as a list: filename and storage key
- Thumbnails generated client-side by loading video into a `<video>` element, seeking to first frame, drawing to `<canvas>`, and extracting as data URL
- Checkboxes to select which source videos to include in the batch
- Files upload to existing `POST /videos/upload` endpoint

### Right Panel — Gameplay Selection
- Grid of gameplay clips fetched from `GET /gameplay`
- Each tile: thumbnail, name, duration
- Multi-select (click to toggle selection)
- Small upload button to add custom gameplay via `POST /videos/upload-gameplay`

### Bottom Bar — Generate
- Summary line: "4 source videos × 3 gameplay clips = 12 jobs (12 credits)"
- "Generate" button — creates batch jobs for every source × gameplay combination
- Each source video gets its own `POST /jobs/batch` call with selected gameplay IDs
- Button disabled if no source or gameplay selected, or insufficient credits
- Credits remaining shown in the bar

---

## View 2: Jobs

### Layout
Filterable table of all jobs.

### Table Columns
- Status dot (yellow=pending, blue=processing, green=completed, red=failed)
- Source video name
- Gameplay clip name
- Created time
- Status text

### Behavior
- Polls `GET /jobs` every 5 seconds
- Newest jobs at top
- Failed jobs show error message on row expand/hover
- Completed jobs have a "Preview" button (inline video playback)
- Completed jobs have a "Send to Review" action

### Filtering
Toggle buttons at top: All / Pending / Processing / Completed / Failed. Calls `GET /jobs?limit=100` — single-user tool, 100 jobs is sufficient. Older jobs beyond 100 are not shown (acceptable trade-off).

### Display Names
The existing `JobResponse` returns storage keys (`uploads/uuid_filename.mp4`), not human-readable names. The dashboard extracts a display name client-side by stripping the UUID prefix and path from the key (e.g., `uploads/abc123_my_video.mp4` → `my_video.mp4`).

---

## View 3: Review Queue

### Layout
Focused single-video review interface.

### Main Area
- Large HTML5 `<video>` player showing the output video
- Below: source name + gameplay name for context
- Two action buttons: **Approve** (green) and **Reject** (red)
- Optional "Skip" to defer

### Sidebar
- Vertical thumbnail strip of all videos awaiting review
- Badge showing count: "7 to review"
- Click any thumbnail to jump to it

### Review State Model
Review state is tracked **client-side only** — no new job statuses needed. The review queue is computed as:
- All completed jobs that are NOT in the posting queue AND NOT in a local `rejectedJobIds` set (stored in localStorage)

This avoids modifying the existing `JobStatus` enum or adding a `PATCH /jobs/{id}` endpoint.

### Flow
- Review queue = completed jobs minus posting queue items minus rejected IDs
- **Approve** → calls `POST /posting-queue` with the job ID, advances to next video
- **Reject** → adds job ID to `rejectedJobIds` in localStorage, advances to next
- "Send to Review" in Jobs view is implicit — all completed jobs not yet approved/rejected appear in review
- Auto-advances after each action

---

## View 4: Posting Queue

### Layout
Two sections stacked.

### Phone Status Bar (top)
- Connection indicator: green "Samsung connected" / red "Disconnected"
- Current activity: "Idle" / "Posting video 3 of 7" / "Waiting for TikTok upload"
- Data from `GET /phone/status`

### Posting Queue (main)
- Ordered list of approved videos
- Each row: thumbnail, source name, gameplay name, status (queued / posting / posted / failed)
- Drag-to-reorder for priority (calls `POST /posting-queue/reorder` with new positions)
- "Post Next" button for manual trigger
- Auto-post is handled by the ADB poster script (server-side), not the frontend. The dashboard just shows current state.
- Failed items show error, can retry (resets status to `queued` via PATCH)

### Posted Section (bottom)
- Collapsed/expandable list of successfully posted videos
- Shows: thumbnail, name, posted timestamp

---

## Navigation

- Persistent tab bar across the top
- Four tabs: Upload & Generate, Jobs, Review Queue, Posting Queue
- Badge counts on tabs:
  - Jobs: number of currently processing jobs
  - Review Queue: number of videos awaiting review
  - Posting Queue: number of queued videos

---

## Design & Aesthetic

- **Theme:** Dark — near-black background (#0a0a0a), sharp accent color (hot red/orange #ff3a2f)
- **Font:** JetBrains Mono — code-ops internal tool feel
- **Density:** Functional and dense, no wasted space
- **Animations:** Minimal — status transitions, smooth tab switches. Nothing that slows workflow
- **Video:** Native HTML5 `<video>` elements
- **Layout:** CSS Grid / Flexbox, responsive enough for one screen but not mobile-optimized (internal tool)

---

## API Integration Summary

### Existing Endpoints Used
- `POST /auth/login` — dashboard login
- `POST /auth/refresh` — token refresh
- `POST /videos/upload` — upload source videos
- `POST /videos/upload-gameplay` — upload custom gameplay
- `GET /gameplay` — list gameplay library
- `POST /jobs/batch` — create batch jobs
- `GET /jobs?limit=100` — list jobs with status
- `GET /jobs/{id}` — get single job details

### New Endpoints Required
- `POST /posting-queue` — add job to posting queue
- `GET /posting-queue` — list posting queue (filterable by status)
- `PATCH /posting-queue/{id}` — update item (status, position, caption)
- `POST /posting-queue/reorder` — batch reorder items
- `DELETE /posting-queue/{id}` — remove item
- `GET /phone/status` — ADB phone connection status (reads from status file)

### New DB Model
- `PostingQueueItem` — as defined in Architecture section above

### New Component
- `scripts/tiktok_poster.py` — ADB automation script (separate process)

---

## Out of Scope (for now)

- Scheduling posts at specific times
- Multiple TikTok accounts
- Analytics / post performance tracking
- Auto-sourcing videos (manual upload only)
- Mobile-optimized UI
- Multi-user support (single operator, uses existing auth)
