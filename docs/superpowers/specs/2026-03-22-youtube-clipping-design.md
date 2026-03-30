# YouTube Smart Clipping — Design Spec

## Overview

Pipeline that takes a YouTube URL, downloads the video, transcribes it, uses OpenAI GPT-4o to identify the most viral 30-90 second segments, extracts those clips, and reframes landscape video to 9:16 vertical using MediaPipe face tracking. Extracted clips become source videos for the existing splitscreen pipeline.

## User Flow

1. Submit a YouTube URL via `POST /clips/extract`
2. Pipeline runs async: download → transcribe → AI analysis → extract → reframe
3. Check status and view results via `GET /clips/{extraction_id}`
4. Review clips — each has a virality score, hook text, duration, and preview
5. Use any clip's `storage_key` as `source_video_key` in existing `POST /jobs/batch` to create splitscreen videos

---

## Architecture

### New API Endpoints

#### `POST /clips/extract`
Submit a YouTube URL for clip extraction.
- **Request:** `{ "youtube_url": "https://youtube.com/watch?v=..." }`
- **Validation:** URL must be a valid YouTube URL. Video must be under 60 minutes (checked after yt-dlp metadata fetch; extraction fails with "Video too long" if exceeded).
- **Response (201):** `{ "id": "uuid", "status": "pending", "youtube_url": "...", "created_at": "..." }`
- **Errors:** 400 if invalid URL, 402 if insufficient credits
- **Credits:** 1 credit deducted per extraction (refunded on failure). Credit transaction uses `job_id=None` — the `CreditTransaction.job_id` FK is already nullable. The extraction_id is not tracked in the transaction table (acceptable trade-off — extraction records themselves provide the audit trail).
- **Auth:** Required (Bearer token)

#### `GET /clips/{extraction_id}`
Get extraction status and clips.
- **Response (200):**
```json
{
  "id": "uuid",
  "status": "pending|downloading|transcribing|analyzing|extracting|completed|failed",
  "youtube_url": "...",
  "video_title": "Video Title",
  "video_duration": 1234.5,
  "error_message": null,
  "created_at": "...",
  "completed_at": "...",
  "clips": [
    {
      "id": "uuid",
      "storage_key": "clips/extraction-id/clip-id.mp4",
      "start_time": 45.2,
      "end_time": 112.8,
      "duration": 67.6,
      "virality_score": 87,
      "hook_text": "Nobody tells you this about...",
      "transcript_text": "Full transcript of the clip...",
      "reframed": true,
      "preview_url": "/storage/clips/extraction-id/clip-id.mp4"  // computed from storage_key, not stored
    }
  ]
}
```
- **Errors:** 404 if extraction not found
- **Auth:** Required, user-scoped (only own extractions)

#### `GET /clips`
List user's extractions with basic info (no clips array — use detail endpoint for that).
- **Query params:** `limit` (default 20, max 100), `cursor` (optional)
- **Response (200):** `{ "extractions": [...], "next_cursor": "..." }`
- **Auth:** Required

---

### New DB Models

#### ClipExtraction

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (String 36) | Primary key |
| user_id | UUID (FK) | Owner |
| status | Enum | pending / downloading / transcribing / analyzing / extracting / completed / failed |
| youtube_url | String(2048) | Original YouTube URL |
| video_title | String(500), nullable | YouTube video title from yt-dlp metadata |
| video_duration | Float, nullable | Total video duration in seconds |
| source_video_key | String(500), nullable | Storage key of downloaded full video |
| error_message | Text, nullable | Failure details |
| credits_charged | Integer, default 1 | Credits deducted |
| created_at | DateTime(tz) | When submitted |
| completed_at | DateTime(tz), nullable | When finished |

Relationships: `user` (back_populates="clip_extractions"), `clips` (one-to-many)

**Note:** The `User` model must be updated to add a `clip_extractions` relationship (back_populates="user").

#### Clip

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (String 36) | Primary key |
| extraction_id | UUID (FK) | Parent extraction |
| storage_key | String(500) | Path to clip video file |
| start_time | Float | Start timestamp in source video (seconds) |
| end_time | Float | End timestamp in source video (seconds) |
| duration | Float | Clip length in seconds |
| virality_score | Integer | 1-100 score from OpenAI |
| hook_text | Text | Opening line / hook identified by OpenAI |
| transcript_text | Text | Full transcript of the clip segment |
| reframed | Boolean, default False | Whether face-tracking reframe was applied |
| created_at | DateTime(tz) | When created |

Relationship: `extraction` (back_populates="clips")

---

### Processing Pipeline (Celery Task)

Runs as `extract_clips_task(extraction_id)` with Celery task name `"extract_clips"` — same patterns as existing `process_video_task`.

**Known failure modes:** yt-dlp may fail due to YouTube rate limiting, geo-restrictions, or CAPTCHA challenges. These are treated as transient errors and retried. After 3 retries, the extraction fails with a descriptive error message.

**Alembic migration required** for `clip_extractions` and `clips` tables.

#### Stage 1: Download
- Set status to `downloading`
- Use **yt-dlp** to download video + metadata
- Extract: title, duration, resolution, aspect ratio
- **Enforce 60-minute max duration** — if video exceeds limit, fail immediately with "Video too long (max 60 minutes)"
- yt-dlp writes directly to `{storage_dir}/downloads/{extraction_id}/source.mp4` (bypasses storage abstraction — files are too large for in-memory bytes)
- Update extraction: `video_title`, `video_duration`, `source_video_key`

#### Stage 2: Transcribe
- Set status to `transcribing`
- Use existing **Deepgram** transcription service (`app/services/transcription.py`)
- Get word-level timestamps: `[{"word": "hello", "start": 0.5, "end": 0.8}, ...]`
- If transcription fails or returns empty: fail the extraction ("No speech detected")
- Unlike video processing jobs, transcription is required here — can't clip without it

#### Stage 3: Analyze with OpenAI
- Set status to `analyzing`
- Format transcript with timestamps into a readable text block
- **Long transcript handling:** If transcript exceeds ~12,000 words (~60 min video), split into 30-minute chunks with 2-minute overlap. Analyze each chunk separately, merge results, deduplicate overlapping clips.
- Send to **GPT-4o** with system prompt requesting clip identification
- Request JSON response with: start_time, end_time, virality_score (1-100), hook_text, reasoning
- Target: 30-90 second clips, strong opening hooks, complete thoughts
- Parse response, validate timestamps are within video bounds

**System prompt:**
> You are a viral content analyst specializing in short-form video for TikTok, Instagram Reels, and YouTube Shorts. Given a transcript with word-level timestamps from a video, identify the best clips between 30-90 seconds long.
>
> For each clip:
> - It must have a strong hook in the first 3 seconds that makes viewers stop scrolling
> - It must contain a complete thought or story arc — no mid-sentence cuts
> - It should end cleanly, ideally on a punchline, key insight, or emotional peak
> - Score it 1-100 on virality potential based on: hook strength, emotional engagement, shareability, and completeness
>
> Return JSON: { "clips": [{ "start_time": float, "end_time": float, "virality_score": int, "hook_text": "first sentence of the clip", "reasoning": "why this clip works" }] }
>
> Order clips by virality_score descending. Aim for 5-15 clips depending on video length.

**OpenAI config:**
- Model: `gpt-4o`
- `response_format: { "type": "json_object" }`
- Temperature: 0.3 (more deterministic scoring)
- Max tokens: 4096

#### Stage 4: Extract & Reframe
For each clip identified by OpenAI:

1. **FFmpeg extract** — cut segment from source video at start_time/end_time
2. **Detect aspect ratio** — FFprobe the source
3. **If landscape (width > height):**
   - Run **MediaPipe Face Detection** on sampled frames (every 0.5s)
   - Compute smoothed crop window (1080x1920) centered on primary face
   - Moving average on face positions to prevent jitter
   - If face lost: hold last known position
   - If no face at all: center crop
   - Apply crop via FFmpeg `crop` filter
4. **If vertical/square:** scale to 1080x1920, no face tracking needed
5. **Save** to storage: `clips/{extraction_id}/{clip_id}.mp4`
6. **Create Clip record** in database

- Output codec: H.264 (libx264, preset=medium, crf=23), AAC audio (128k) — same as existing video processor
- Set status to `extracting` at the start of this stage
- If reframing fails for an individual clip, mark `reframed=False` and fall back to center crop — do not fail the entire extraction
- Clips are saved directly to disk at `{storage_dir}/clips/{extraction_id}/{clip_id}.mp4` (bypasses storage abstraction for consistency with download stage)

#### Stage 5: Complete
- Set status to `completed`, set `completed_at`
- Clean up temp files (keep source video in storage for potential re-extraction)

#### Failure Handling
- Same retry pattern as existing worker: max 3 retries, 30-second delay
- On final failure: set status to `failed`, store error message, refund credit
- Each stage updates status so the user can see progress

#### Fallback (No Redis)
Same pattern as existing jobs — synchronous inline processing if Celery is unavailable.

---

### New Services

#### YouTube Downloader (`app/services/youtube.py`)
- `download_video(url: str, output_dir: str) -> dict` — downloads video, returns metadata (title, duration, filepath, width, height)
- Uses yt-dlp Python API
- Validates URL is a valid YouTube URL before downloading
- Downloads best quality up to 1080p (no 4K — unnecessary for shorts)
- Returns: `{ "title": str, "duration": float, "filepath": str, "width": int, "height": int }`

#### OpenAI Clip Analyzer (`app/services/clip_analyzer.py`)
- `analyze_transcript(words: list[dict], video_duration: float) -> list[dict]` — sends transcript to GPT-4o, returns clip suggestions
- Formats word-level timestamps into readable transcript text
- Calls OpenAI chat completions API
- Parses and validates JSON response
- Returns: list of `{ "start_time", "end_time", "virality_score", "hook_text", "reasoning" }`

#### Face Reframer (`app/services/face_reframer.py`)
- `reframe_to_vertical(input_path: str, output_path: str) -> bool` — reframes landscape video to 9:16 with face tracking
- Returns `True` if reframing was applied, `False` if input was already vertical
- Uses MediaPipe for face detection, FFmpeg for the actual crop
- Smoothing: moving average window on face center positions
- Fallback: center crop if no face detected

---

### Configuration

New env vars:
```
OPENAI_API_KEY           # Required for clip analysis
OPENAI_MODEL             # Default: gpt-4o
```

`DEEPGRAM_API_KEY` already exists. No new config for yt-dlp or MediaPipe (no API keys needed).

### New Dependencies
- `openai` — OpenAI Python SDK
- `yt-dlp` — YouTube video downloader
- `mediapipe` — Google's face detection (runs on CPU)

---

## Storage Layout

```
storage/
  downloads/{extraction_id}/source.mp4    # Full downloaded video
  clips/{extraction_id}/{clip_id}.mp4     # Individual extracted clips
```

Clips are stored permanently. Downloaded source videos can be cleaned up periodically (not automated — manual for now).

---

## Integration with Existing Splitscreen Pipeline

No changes needed to existing code. The integration is data-level:

1. Extract clips → each clip gets a `storage_key` like `clips/abc123/def456.mp4`
2. User reviews clips via `GET /clips/{extraction_id}`
3. User picks favorites, uses their `storage_key` as `source_video_key` in `POST /jobs/batch`
4. Existing splitscreen pipeline takes over: gameplay compositing + captions

---

## Out of Scope (for now)

- Automatic splitscreen job creation (user manually triggers after review)
- Re-extraction with different parameters
- Clip editing / trimming after extraction
- Multiple YouTube URLs in one request
- Downloading from non-YouTube sources
- GPU-accelerated face detection
- Virality score calibration / learning from feedback
- Deletion of extractions and associated clips/storage
- Duplicate URL detection (same URL submitted twice)
