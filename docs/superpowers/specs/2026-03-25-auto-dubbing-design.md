# Auto-Dubbing Feature Design

Standalone job type that takes a source video and produces dubbed + lip-synced versions in multiple languages. Uses ElevenLabs Dubbing API for audio translation/voice cloning and Sync Labs API for visual lip-sync.

## Supported Languages

- French (`fr`)
- Spanish (`es`)
- Hebrew (`he`)

## Data Model

### DubbingJob

Tracks the overall dubbing request.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | FK → users | |
| source_video_key | str | Storage path to source video |
| source_url | str, nullable | URL if provided instead of upload |
| languages | JSON | e.g. `["fr", "es", "he"]` |
| status | enum | pending → downloading → processing → completed / failed |
| error_message | str, nullable | |
| credits_charged | int | Number of credits deducted (= number of languages) |
| created_at | datetime | |
| started_at | datetime, nullable | |
| completed_at | datetime, nullable | |

Status notes: `downloading` matches `ExtractionStatus` precedent in `clip_extraction.py`. `processing` covers the fan-out phase where individual languages are being dubbed/lip-synced. Individual language progress is tracked on `DubbingOutput`.

### DubbingOutput

One row per language per job. Tracks each language independently so partial success is possible.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| dubbing_job_id | FK → dubbing_jobs | |
| language | str | e.g. `"fr"` |
| elevenlabs_dubbing_id | str, nullable | ElevenLabs async job ID |
| dubbed_audio_key | str, nullable | Storage path to dubbed audio |
| synclabs_video_id | str, nullable | Sync Labs async job ID |
| output_video_key | str, nullable | Storage path to final lip-synced video |
| status | enum | pending → dubbing → lip_syncing → completed / failed |
| error_message | str, nullable | |
| started_at | datetime, nullable | |
| completed_at | datetime, nullable | |

## Credits

- **Cost:** 1 credit per language (so a 3-language job costs 3 credits)
- **Deduction:** Check `credits_remaining >= len(languages)` upfront. Then call `deduct_credit()` in a loop with `commit=False` for each language. Commit once all succeed. If the balance check passes but a deduction fails mid-loop, rollback the session (no partial deduction).
- **Refund:** If an individual output fails after all retries, call `refund_credit(db, user_id, job_id=None, commit=False)` for that output (pass `job_id=None` since `CreditTransaction.job_id` FK points to the `jobs` table, not `dubbing_jobs` — matches how `clip_worker.py` already handles this).
- **Tracking:** Add `credits_charged: int` to `DubbingJob` (set to `len(languages)` at creation) for audit purposes.

## API Endpoints

Router: `APIRouter(prefix="/dubbing", tags=["dubbing"])` — matches existing pattern (`/clips`, `/jobs`).

All endpoints use `Depends(get_current_user)` and filter queries by `user_id`.

### POST `/dubbing`

Create a new dubbing job.

- **Input:** `{ "source_url": "...", "languages": ["fr", "es", "he"] }` or multipart file upload + languages
- **Validation:** Languages must be subset of `["fr", "es", "he"]`. Max video duration: 30 minutes.
- **Credits:** Deduct `len(languages)` credits. Return 402 if insufficient.
- **Action:** Creates `DubbingJob` + one `DubbingOutput` per language, dispatches Celery task
- **Dev fallback:** Uses `_is_celery_available()` check with background thread fallback (matches `jobs.py` and `clips.py` pattern)
- **Response:** Job ID + status

### GET `/dubbing`

List user's dubbing jobs with all outputs and statuses. Supports `cursor` and `limit` query params (matches existing pagination pattern).

### GET `/dubbing/{job_id}`

Get job detail with all outputs. Includes download URLs for completed outputs. Returns 404 if job not found or not owned by user.

### GET `/dubbing/{job_id}/outputs/{output_id}/download`

Stream the final dubbed video file from storage.

## Worker Pipeline

### Main Task: `process_dubbing`

**Step 1 — Acquire source video**
- URL provided: download via `yt-dlp` (reuses existing `youtube.py` service)
- File upload: resolve from storage
- Update job status to `processing`

**Step 2 — Fan out per language**

Dispatch a `process_dubbing_language` sub-task for each `DubbingOutput` via `.delay()`. Each sub-task is fully independent — no Celery group/chord primitives needed.

### Sub-task: `process_dubbing_language`

**Step 2a — ElevenLabs Dubbing**
- POST source video + target language to ElevenLabs Dubbing API (source language: auto-detect)
- Poll with exponential backoff (5s, 10s, 20s, capped at 60s) until complete
- Timeout: 30 minutes (dubbing longer videos can take time)
- On timeout: treat as failure, counts toward retry limit
- Download dubbed video and extract audio track via ffmpeg (ElevenLabs returns a full video, we only need the audio for Sync Labs)
- Save dubbed audio to storage
- Update output status to `lip_syncing`

**Step 2b — Sync Labs Lip-sync**
- POST original video + dubbed audio to Sync Labs API
- Poll with exponential backoff (5s, 10s, 20s, capped at 60s) until complete
- Timeout: 30 minutes
- On timeout: treat as failure, counts toward retry limit
- Download lip-synced video, save to storage
- Update output status to `completed`

**Step 2c — Check parent completion**

After each sub-task completes (success or final failure), query all sibling `DubbingOutput` rows. If all are in a terminal state (`completed` or `failed`):
- If any succeeded: mark parent `DubbingJob` as `completed`
- If all failed: mark parent as `failed`
- Set `completed_at` on parent

This "last one out turns off the lights" approach avoids Celery coordination primitives while still finalizing the parent job.

### Retry Strategy

Each language sub-task retries up to 3 times independently (matches existing worker pattern). On final failure, refund 1 credit for that output.

## Services

### `app/services/elevenlabs.py`

- `create_dubbing(video_path: str, target_lang: str) -> str` — uploads video, returns dubbing ID
- `poll_dubbing(dubbing_id: str) -> str` — polls until done, returns status
- `download_dubbed_audio(dubbing_id: str, target_lang: str, output_path: str) -> None` — downloads dubbed audio
- Uses `httpx` (consistent with existing services)

Note: ElevenLabs Dubbing API returns a dubbed video, but we extract just the audio track (via ffmpeg) since we need to pass it to Sync Labs for proper lip-sync. ElevenLabs does not do visual lip-sync.

### `app/services/synclabs.py`

- `create_lipsync(video_path: str, audio_path: str) -> str` — uploads video + audio, returns job ID
- `poll_lipsync(job_id: str) -> str` — polls until done, returns status
- `download_lipsync(job_id: str, output_path: str) -> None` — downloads final video

Both services: create async job → poll → download result. Polling logic encapsulated in the service.

### Config Additions (`app/config.py`)

- `elevenlabs_api_key: str = ""`
- `synclabs_api_key: str = ""`

## Storage Layout

```
storage/
  dubbing/
    {job_id}/
      source.mp4
      fr/
        dubbed_audio.mp3
        output.mp4
      es/
        dubbed_audio.mp3
        output.mp4
      he/
        dubbed_audio.mp3
        output.mp4
```

Temp files use `tempfile.TemporaryDirectory()` during processing. Only final outputs persisted to storage.

## Input Validation

- Max video duration: 30 minutes (consistent with existing YouTube download limit)
- Languages must be a non-empty subset of `["fr", "es", "he"]`
- Source must be either a URL or a file upload, not both

## Migration

Two new tables (`dubbing_jobs`, `dubbing_outputs`) require an Alembic migration.

## Dependencies

- ElevenLabs API (new) — dubbing + voice cloning + translation
- Sync Labs API (new) — video lip-sync
- Existing: yt-dlp, FFmpeg, Celery, Redis, storage system
