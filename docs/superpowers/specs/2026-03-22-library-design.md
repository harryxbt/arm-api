# Library, Clip Re-generation & Multi-Source Import Design

## Overview

Add a "Library" tab that lets users browse all past extractions, view clips, edit transcripts, adjust caption settings, pick gameplay, and re-generate splitscreen videos. The same clip interaction experience is embedded in the Cluster detail view so users can work with clips from either entry point.

Additionally, expand the input flow (Step 1) to accept three source types:
1. **YouTube URLs** — existing full extraction pipeline (download, transcribe, analyze, split into clips)
2. **Instagram URLs** — download the reel/post video, auto-transcribe, create as a single clip (no extraction/splitting)
3. **Local files** — upload a video file, auto-transcribe, create as a single clip (no extraction/splitting)

IG and local imports skip the clip analysis step since they're already short-form content. They get transcribed via Whisper for captions, then appear in the library as a single-clip extraction ready for splitscreen generation.

## UI

### Step 1 — Expanded Input (CLIPS tab)

The existing "Paste a YouTube URL" step becomes a multi-source input:

- **URL input**: accepts both YouTube and Instagram URLs. Auto-detects which type based on URL pattern.
- **File upload button**: "UPLOAD FILE" button next to the URL input. Opens file picker for `.mp4`, `.mov`, `.webm` files.
- **Optional cluster dropdown**: already planned (from clusters feature), applies to all source types.

**Behavior by source type:**

| Source | Flow |
|--------|------|
| YouTube URL | Existing pipeline: download → transcribe → analyze → extract clips → library |
| Instagram URL | Download via yt-dlp → transcribe → create single-clip extraction → library |
| Local file | Upload to storage → transcribe → create single-clip extraction → library |

For IG and local files, the UI skips steps 2-3 (no clip picking needed since there's one clip). After transcription completes, the extraction appears in the library with a single clip ready for splitscreen generation.

### Library Tab

New tab alongside CLIPS and CLUSTERS. Shows all past extractions as a list:
- Video title (or YouTube URL if no title)
- Date
- Clip count
- Status badge (completed/failed/in-progress)

Ordered by most recent first. Click an extraction to open the **Extraction Detail View**.

### Extraction Detail View

Accessed from Library tab or from within Cluster detail view.

**Header**: video title, YouTube URL (linkable), date, status.

**Clips list**: all clips from that extraction displayed as cards:
- Virality score badge
- Hook text
- Duration
- Preview button (opens existing video modal)
- Selectable (click to toggle, same pattern as existing step 2)

**Transcript editor**: clicking a clip card expands it to show:
- Textarea with `transcript_text`, editable
- "SAVE" button that calls `PUT /clips/{extraction_id}/{clip_id}` to persist changes

**Caption settings panel**: same controls as existing step 3 (font, size, words-per-line, position, text color, outline color). Not persisted to DB — session-level settings applied at generation time.

**Gameplay selector**: dropdown of gameplay clips (from `GET /gameplay`), pre-filled with the last-used gameplay for this extraction (stored in `ClipExtraction.last_gameplay_ids`). Multi-select to match existing batch flow.

**"GENERATE" button**: enabled when at least one clip and one gameplay are selected. Calls `POST /jobs/batch` once per selected clip (each clip's `storage_key` as the `source_video_key`, with all chosen gameplay IDs). Updates `last_gameplay_ids` on the extraction via `PUT /clips/{extraction_id}/last-gameplay`. Shows per-job progress inline (same polling pattern as step 4 — partial failures are expected, each job shows its own status).

### Cluster Detail View (enhanced)

The existing cluster detail view keeps its accounts + stats sections. The extractions section becomes interactive:
- Each extraction is expandable — click to reveal the same clip list + transcript editor + caption settings + gameplay selector + generate controls
- Same underlying UI component as the Library's extraction detail view

## Data Changes

### Modified Tables

#### `clip_extractions`

Add columns:
- `last_gameplay_ids`: JSON, nullable. Stores list of gameplay IDs last used when generating from this extraction. Updated on each generation.
- `source_type`: Enum (`youtube`, `instagram`, `upload`), default `youtube`. Indicates how the video was sourced.

The existing `youtube_url` column (String 2048) is reused for Instagram URLs. For local file uploads, it stores the original filename. No rename needed — it's just a source identifier.

### No new tables needed.

## API Changes

### New Endpoint — Import

`POST /clips/import` — Import a video from Instagram URL or local file upload.

- Auth: `get_current_user` required
- Accepts `multipart/form-data`:
  - `url`: string (optional) — Instagram post/reel URL
  - `file`: file upload (optional) — `.mp4`, `.mov`, `.webm` (max 500MB)
  - `cluster_id`: string (optional) — assign to a cluster
  - One of `url` or `file` must be provided
- Creates a `ClipExtraction` with source type indicator
- Background processing: downloads (if URL), saves to storage, transcribes via Whisper, creates a single `Clip` with full video as the clip
- Returns: `ExtractionResponse` (status will be `pending`, then progresses to `completed`)

The `ClipExtraction` model gets a new column `source_type` (enum: `youtube`, `instagram`, `upload`) to distinguish how the video was sourced. The existing `youtube_url` field is reused for IG URLs too (renamed semantically to `source_url` or kept as-is with IG URLs stored there).

### New Endpoint — Update Clip

`PUT /clips/{extraction_id}/{clip_id}` — Update a clip's transcript text.

- Auth: `get_current_user` required
- Validates extraction belongs to requesting user
- Body: `{ transcript_text: str }` (max 50,000 characters)
- Returns: updated `ClipResponse`

### Modified Schemas

- `ExtractionResponse`: add `last_gameplay_ids: list[str] | None = None`
- `ExtractionSummaryResponse`: add `clip_count: int`
- Update `list_extractions` route to include clip count per extraction

### New Endpoint

`PUT /clips/{extraction_id}/last-gameplay` — Update last-used gameplay IDs.

- Auth: `get_current_user` required
- Body: `{ gameplay_ids: list[str] }` (1-20 items, validated)
- Updates `ClipExtraction.last_gameplay_ids`
- Returns: updated `ExtractionResponse`

### Existing Endpoints (no changes)

- `GET /clips` — list extractions (already exists, used by library)
- `GET /clips/{extraction_id}` — get extraction detail with clips (already exists)
- `POST /jobs/batch` — create splitscreen jobs (already exists)
- `GET /gameplay` — list gameplay clips (already exists)

## Implementation Notes

- Alembic migration to add `last_gameplay_ids` (JSON) and `source_type` (Enum) columns to `clip_extractions`
- New `SourceType` enum in `app/models/clip_extraction.py`: `youtube`, `instagram`, `upload`
- New Pydantic schema: `UpdateClipRequest` with `transcript_text: str` (max_length=50000 validator)
- New Pydantic schema: `UpdateLastGameplayRequest` with `gameplay_ids: list[str]` (min 1, max 20 items)
- Add `last_gameplay_ids` and `source_type` to `ExtractionResponse` schema
- Add `clip_count` to `ExtractionSummaryResponse` schema
- Import endpoint accepts `multipart/form-data` (not JSON) since it handles file uploads
- Instagram download uses yt-dlp (same as YouTube — yt-dlp already supports Instagram)
- Import background processing creates a `ClipExtraction` in `pending` state, then: download/save → transcribe → create single `Clip` → mark `completed`
- For imports, the single clip's `start_time` is 0, `end_time` is the video duration, `virality_score` is 0 (not analyzed), `hook_text` is empty
- URL validation: accept `instagram.com/p/`, `instagram.com/reel/`, `instagram.com/reels/` patterns
- File upload validation: accept `.mp4`, `.mov`, `.webm`, max 500MB
- The extraction detail UI component should be reusable between Library tab and Cluster detail view — same JS functions, just rendered in different containers
- Existing `/jobs/batch` already handles the generation pipeline, no backend changes needed for that flow
- Step 1 URL input: auto-detect YouTube vs Instagram by URL pattern, show appropriate status messages
