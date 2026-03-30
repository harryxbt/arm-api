# Auto-Posting to Content Platforms — Design Spec

## Overview

Add scheduled publishing to TikTok, YouTube, and Instagram Reels. Users connect platform accounts (manual token entry), schedule clips/videos for posting with per-platform metadata, and a Celery Beat worker dispatches uploads at the scheduled time.

## Motivation

Armageddon produces multiplied video content — clips extracted from YouTube, splitscreen composites with captions and gameplay. The missing piece is distribution. Users currently download outputs and manually upload to each platform. Auto-posting closes the loop: produce content, schedule it, and let the system push it out.

## Platforms

- **TikTok** — Content Posting API (chunked upload: init, upload, publish)
- **YouTube** — Data API v3 (resumable upload + optional thumbnail)
- **Instagram Reels** — Graph API (create container, upload, poll, publish)

## Architecture

### Approach: Celery Beat Scheduler

Chosen over APScheduler (jobs lost on restart) and cron (no retries, no parallelism). Celery Beat polls every 60 seconds for due posts, dispatches a Celery task per post. This extends the existing Celery infrastructure used by `process_video_task` and `extract_clips_task`.

### Data Flow

```
User schedules post(s) via API
        |
        v
AccountPost rows created (status: pending, scheduled_at set)
        |
        v
Celery Beat polls every 60s
        |
        v
Due posts dispatched as upload_to_platform tasks
        |
        v
Uploader service calls platform API
        |
        v
Status updated to posted (with platform URL) or failed (with error)
```

## Data Models

### Integration with Existing Cluster Models

The codebase already has `ClusterAccount` (`app/models/cluster.py`) for platform accounts and `AccountPost` for tracking posts. Rather than creating parallel models, we extend the existing ones:

- **Reuse `Platform` enum** from `app/models/cluster.py` (already has tiktok, youtube, instagram)
- **Extend `ClusterAccount`** with a `credentials` column for API tokens
- **Extend `AccountPost`** with scheduling and upload status fields

### ClusterAccount — New Column

| Column | Type | Notes |
|--------|------|-------|
| credentials | JSON, nullable | Platform-specific API tokens (see below) |

Added to the existing model which already has: id, cluster_id, platform, handle, created_at.

**Credentials format per platform:**

- TikTok: `{"access_token": "...", "open_id": "..."}`
- YouTube: `{"access_token": "...", "refresh_token": "...", "client_id": "...", "client_secret": "..."}`
- Instagram: `{"access_token": "...", "instagram_user_id": "..."}`

### AccountPost — New Columns

Added to the existing model which already has: id, account_id (FK -> cluster_accounts.id), clip_id, platform_post_id, views, likes, comments, shares, posted_at, created_at.

| Column | Type | Notes |
|--------|------|-------|
| job_id | FK -> jobs.id, nullable | For splitscreen pipeline outputs |
| video_storage_key | String(500), nullable | Resolved path to video file |
| scheduled_at | DateTime(tz), nullable | When to post (null = not scheduled) |
| status | Enum(pending, uploading, posted, failed), nullable | Null for manually-tracked legacy posts |
| platform_url | String(500), nullable | Link to live post |
| error_message | Text, nullable | |
| metadata | JSON, nullable | Platform-specific options (see below) |

**Metadata JSON per platform:**

- **TikTok**: caption, hashtags, privacy_level, disable_comment, disable_duet, disable_stitch
- **YouTube**: title, description, tags, category_id, privacy_status (public/unlisted/private), thumbnail_path
- **Instagram Reels**: caption, hashtags, cover_url, share_to_feed

### Video Storage Key Resolution

When scheduling a post, `video_storage_key` is resolved at creation time:

- **From clip_id**: uses `Clip.storage_key`
- **From job_id**: uses `Job.output_video_key`

Scheduling requires the video to already exist. If `Job.output_video_key` is null (job not completed), the API returns a 400 error. Users must wait for processing to finish before scheduling.

### Multi-Platform Flow

Scheduling a clip to multiple platforms creates multiple `AccountPost` rows sharing the same video source but with independent schedules, metadata, and statuses. One failing doesn't block the others.

## Platform Uploader Services

Located in `app/services/uploaders/`.

### Base Interface

```python
class BaseUploader:
    def upload(self, video_path: str, metadata: dict) -> dict:
        """Returns {"platform_post_id": "...", "platform_url": "..."}"""
        raise NotImplementedError

    def validate_credentials(self, credentials: dict) -> bool:
        """Quick check that tokens are still valid."""
        raise NotImplementedError
```

### TikTokUploader (`tiktok.py`)

- Content Posting API: init upload -> upload video chunks -> publish
- Hashtags appended to caption text (no separate field)
- Metadata: caption, privacy_level, disable_comment, disable_duet, disable_stitch

### YouTubeUploader (`youtube.py`)

- Data API v3: resumable upload -> set snippet/status -> optional thumbnail upload
- Token refresh: attempt refresh using stored refresh_token + client_id/client_secret before uploading; update stored credentials on success
- Metadata: title, description, tags, category_id, privacy_status

### InstagramReelsUploader (`instagram.py`)

- Graph API: create media container -> upload video -> poll for processing completion -> publish
- Hashtags inline in caption
- Metadata: caption, cover_url, share_to_feed

### Factory

```python
def get_uploader(platform: str) -> BaseUploader:
    uploaders = {
        "tiktok": TikTokUploader,
        "youtube": YouTubeUploader,
        "instagram": InstagramReelsUploader,
    }
    return uploaders[platform]()
```

## API Routes

New router: `app/routes/publishing.py`, prefix `/publishing`.

### Platform Accounts

| Method | Path | Description |
|--------|------|-------------|
| PATCH | /publishing/accounts/{id}/credentials | Set or update credentials on a ClusterAccount |
| GET | /publishing/accounts | List all ClusterAccounts that have credentials set |

### Scheduled Posts

| Method | Path | Description |
|--------|------|-------------|
| POST | /publishing/schedule | Schedule posts. Accepts video_source (clip_id or job_id) + array of {account_id, scheduled_at, metadata}. Creates multiple AccountPost rows. |
| GET | /publishing/schedule | List scheduled AccountPosts, filterable by status/platform |
| GET | /publishing/schedule/{id} | Get single post with status and platform URL |
| PATCH | /publishing/schedule/{id} | Update metadata or reschedule (only while pending) |
| DELETE | /publishing/schedule/{id} | Cancel a pending post |

### Quick Action

| Method | Path | Description |
|--------|------|-------------|
| POST | /publishing/post-now | Same payload as /schedule but sets scheduled_at to now and immediately dispatches upload task |

## Worker & Scheduling

Located in `app/publishing_worker.py`.

### Beat Periodic Task

`poll_scheduled_posts` — runs every 60 seconds:
- Queries `AccountPost` where `status = pending` and `scheduled_at <= now`
- For each due post: sets status to `uploading`, dispatches `upload_to_platform` task

### Upload Task

`upload_to_platform(account_post_id)`:
- Loads the AccountPost and linked ClusterAccount credentials
- Resolves video file path from `video_storage_key`
- Calls `get_uploader(platform).upload(video_path, metadata)`
- Success: status -> posted, stores platform_post_id + platform_url, sets posted_at
- Failure: retries up to 3 times with 60s delay, then marks failed with error_message

### Beat Config

Added to existing `celery_app.conf.update()` in `worker.py`:

```python
beat_schedule = {
    "poll-scheduled-posts": {
        "task": "poll_scheduled_posts",
        "schedule": 60.0,
    }
}
```

Task discovery: `worker.py` must import `app.publishing_worker` (same pattern as `clip_worker.py`) so Beat can discover the `poll_scheduled_posts` task.

Run with: `celery -A app.worker beat --loglevel=info`

## Config & Credentials

No new environment variables. Platform credentials live in `ClusterAccount.credentials` JSON, not in global config. This supports multiple accounts per platform.

### Token Refresh

- YouTube: tokens expire hourly. YouTubeUploader refreshes before each upload using stored refresh_token + client_id + client_secret, updates stored credentials on success.
- TikTok/Instagram: long-lived tokens (60+ days). Re-paste when expired.

## Error Handling

- Each AccountPost tracks its own error_message
- Failed posts don't block other posts in the same batch
- 3 retry attempts with 60-second delay (matches existing worker pattern)
- No credits involved — posting is free, only video processing costs credits

## File Summary

| File | Purpose |
|------|---------|
| `app/models/cluster.py` | Extended: add credentials to ClusterAccount, add scheduling columns to AccountPost |
| `migrations/versions/xxx_add_publishing_columns.py` | Alembic migration for new columns |
| `app/services/uploaders/__init__.py` | Base class + factory |
| `app/services/uploaders/tiktok.py` | TikTok uploader |
| `app/services/uploaders/youtube.py` | YouTube uploader |
| `app/services/uploaders/instagram.py` | Instagram Reels uploader |
| `app/schemas/publishing.py` | Pydantic schemas for API |
| `app/routes/publishing.py` | Publishing API routes |
| `app/publishing_worker.py` | Beat task + upload task |

## Out of Scope

- OAuth flow for connecting accounts (manual token entry for now)
- Analytics/insights from platforms
- Auto-generated captions/descriptions (user provides metadata)
- Additional platforms (Facebook, X, LinkedIn) — can be added later as new uploader classes
