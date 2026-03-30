# Analytics Suite — Design Spec

## Overview

Automated TikTok profile analytics for cluster accounts. Add a TikTok account to a cluster, and the system scrapes profile-level stats every 6 hours — followers, likes, video counts, recent video performance. All snapshots stored forever for growth tracking.

## Motivation

Armageddon manages content clusters for clients. To measure impact, we need to track how each account is performing over time — follower growth, engagement trends, content performance. Starting with TikTok only; YouTube/Instagram can be added later.

## Architecture

### Approach: Celery Beat Poller + yt-dlp Scraper

yt-dlp (already installed) scrapes public TikTok profile pages for structured metadata. Celery Beat dispatches scrape tasks every 6 hours, one per TikTok account. Results stored as `ProfileSnapshot` rows — one per scrape, per account, kept forever.

### Data Flow

```
Celery Beat fires every 6 hours
        |
        v
poll_account_analytics queries all TikTok ClusterAccounts
        |
        v
Dispatches scrape_tiktok_profile task per account
        |
        v
TikTokScraper calls yt-dlp on public profile URL
        |
        v
ProfileSnapshot row created with stats
        |
        v
API routes serve current stats, history, growth, cluster overview
```

## Data Model

### ProfileSnapshot

One row per scrape, per account. All snapshots kept forever.

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) PK | UUID |
| account_id | FK -> cluster_accounts.id, ondelete CASCADE | |
| followers | Integer | |
| following | Integer | |
| total_likes | BigInteger | Can be in the millions |
| total_videos | Integer | |
| bio | Text, nullable | |
| avatar_url | String(500), nullable | |
| recent_videos | JSON, nullable | Array of recent video objects (see below) |
| scraped_at | DateTime(tz) | When this snapshot was taken |

**Index:** composite index on `(account_id, scraped_at DESC)` — every query filters by account + time ordering, and this table grows indefinitely.

**recent_videos JSON structure:**

Each entry in the array:
```json
{
    "url": "https://www.tiktok.com/@user/video/123",
    "views": 150000,
    "likes": 12000,
    "comments": 340,
    "shares": 890,
    "caption": "Video caption text",
    "posted_at": "2026-03-20T14:30:00Z"
}
```

This captures whatever's visible on the profile page (typically ~30 recent videos).

### Existing Models Used

- `ClusterAccount` — already has `platform` (Platform enum) and `handle` (e.g. "@joefazer"). No changes needed.
- `Cluster` — groups accounts by client. No changes needed.

### Growth Tracking

Growth is computed at query time by comparing snapshots across time ranges. "Follower growth this week" = latest snapshot followers minus the snapshot closest to 7 days ago. No pre-computed rollup tables needed.

## TikTok Scraper Service

Located in `app/services/tiktok_scraper.py`.

**Input:** handle string (e.g. "@joefazer")

**Output:** dict with all ProfileSnapshot fields (except id, account_id)

**How it works:**
- Builds URL: `https://www.tiktok.com/@joefazer`
- Calls yt-dlp with `--dump-json --flat-playlist` to extract channel metadata and recent video entries
- Parses yt-dlp output into a clean dict matching ProfileSnapshot columns
- Raises an exception on failure (rate limit, page changed, etc.) — caller handles retries

**Single responsibility:** scrapes and returns data. Does not touch the database.

## Worker & Scheduling

Located in `app/analytics_worker.py`.

### Beat Periodic Task

`poll_account_analytics` — runs every 6 hours (21600 seconds):
- Queries all `ClusterAccount` rows where `platform = tiktok`
- For each account, dispatches a `scrape_tiktok_profile` task

### Scrape Task

`scrape_tiktok_profile(account_id)`:
- Loads the ClusterAccount, gets the handle
- Calls `TikTokScraper.scrape(handle)`
- Creates a `ProfileSnapshot` row with the results
- On failure: retries up to 3 times with 60s delay, then logs error (no snapshot created, skip this cycle)

One task per account — independent execution, one failing doesn't block others.

### Beat Config

Added to `worker.py`:
```python
"poll-account-analytics": {
    "task": "poll_account_analytics",
    "schedule": 21600.0,  # 6 hours
}
```

Task discovery: `worker.py` must import `app.analytics_worker`.

## API Routes

New router: `app/routes/analytics.py`, prefix `/analytics`.

| Method | Path | Description |
|--------|------|-------------|
| GET | /analytics/accounts/{id}/current | Latest snapshot for an account |
| GET | /analytics/accounts/{id}/history | Historical snapshots, filterable by date range (?from=&to=), defaults to last 30 days, max 500 rows |
| GET | /analytics/accounts/{id}/growth | Computed growth: follower delta, likes delta, avg views over period (?days=7) |
| GET | /analytics/clusters/{id}/overview | Aggregated stats across all accounts in cluster: total followers, total likes, account count |
| POST | /analytics/accounts/{id}/scrape | Manual trigger — scrape right now instead of waiting for next cycle |

### Growth Endpoint Logic

`GET /analytics/accounts/{id}/growth?days=7`:
- Fetches latest snapshot (current state)
- Fetches snapshot closest to `days` ago
- Returns deltas: follower_change, likes_change, videos_change
- Also returns avg views/likes/comments from recent_videos in the latest snapshot

### Cluster Overview Logic

`GET /analytics/clusters/{id}/overview`:
- For each TikTok account in the cluster, get the latest snapshot
- Aggregate: total followers, total likes, total videos, account count
- Return per-account summaries alongside the totals

## Error Handling

- **Account not found on TikTok:** scraper raises error, worker logs and skips. No snapshot. Next cycle retries.
- **Rate limiting:** yt-dlp handles some internally. Retry logic (3 attempts, 60s delay) covers transient blocks. Persistent blocks appear as gaps in history.
- **New account added:** first snapshot at next 6-hour cycle, or immediately via manual POST /scrape endpoint.
- **Account removed from cluster:** cascade delete removes all snapshots.
- **No credits involved:** analytics is free.

## File Summary

| File | Purpose |
|------|---------|
| `app/models/profile_snapshot.py` | ProfileSnapshot model |
| `app/models/__init__.py` | Re-export ProfileSnapshot |
| `migrations/versions/xxx_add_profile_snapshots.py` | Alembic migration |
| `app/services/tiktok_scraper.py` | yt-dlp based TikTok profile scraper |
| `app/schemas/analytics.py` | Pydantic schemas for API |
| `app/routes/analytics.py` | Analytics API routes |
| `app/analytics_worker.py` | Beat task + scrape task |
| `app/worker.py` | Add Beat schedule + import analytics_worker |
| `app/main.py` | Register analytics router |

## Out of Scope

- YouTube / Instagram scrapers (TikTok only for now — add later as additional scraper classes)
- Dashboard UI (API only — the other agent is handling UI)
- Data rollups / pruning (keep everything forever, optimize later if needed)
- Alerting / notifications
- Official TikTok API integration (scraping public profiles via yt-dlp)
