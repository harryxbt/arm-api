# Clusters Feature Design

## Overview

Clusters are groups of social media accounts that content is distributed to. A cluster like "Charlie Morgan Minecraft Splitscreen" contains a YouTube account, TikTok account, Instagram account, etc. All clips extracted for a cluster are stored together, and each account tracks its own performance metrics.

Clusters are global (no user scoping) since this is an internal tool.

## Data Model

### New Tables

#### `clusters`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID string (36) | PK |
| `name` | String(255) | e.g. "Charlie Morgan Minecraft Splitscreen" |
| `created_at` | DateTime (tz) | Auto-set |
| `updated_at` | DateTime (tz) | Auto-set, auto-update |

Relationships: has many `cluster_accounts`, has many `clip_extractions`.

#### `cluster_accounts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID string (36) | PK |
| `cluster_id` | FK -> clusters.id | `ondelete="CASCADE"` |
| `platform` | Enum: youtube, tiktok, instagram | Python enum + SQLAlchemy Enum |
| `handle` | String(255) | e.g. "@charlieminecraft" |
| `created_at` | DateTime (tz) | Auto-set |

Unique constraint: `(cluster_id, platform, handle)` — same account can't be added twice.

Relationships: belongs to `cluster`, has many `account_posts`.

#### `account_posts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID string (36) | PK |
| `account_id` | FK -> cluster_accounts.id | `ondelete="CASCADE"` |
| `clip_id` | FK -> clips.id | Nullable, `ondelete="SET NULL"` |
| `platform_post_id` | String(500) | Nullable, for future API sync |
| `views` | Integer | Default 0 |
| `likes` | Integer | Default 0 |
| `comments` | Integer | Default 0 |
| `shares` | Integer | Default 0 |
| `posted_at` | DateTime (tz) | Nullable |
| `created_at` | DateTime (tz) | Auto-set |

Relationships: belongs to `cluster_account`, optionally belongs to `clip`.

### Modified Tables

#### `clip_extractions`

Add column:
- `cluster_id`: FK -> clusters.id, **nullable**, `ondelete="SET NULL"`. Existing extractions remain unlinked.
- Add index on `cluster_id` for efficient cluster detail queries.
- Add `cluster` relationship with `back_populates` on both `ClipExtraction` and `Cluster` models.

Note: `ClipExtraction.user_id` remains required — the extraction is still triggered by a user, the cluster just organizes it.

## API Routes

New router mounted at `/clusters`. All routes require authentication via `get_current_user` (consistent with existing routes) even though clusters are global.

### Cluster CRUD

| Method | Path | Description |
|--------|------|-------------|
| `POST /clusters` | Create a cluster. Body: `{ name }` |
| `GET /clusters` | List all clusters with account counts and aggregate stats |
| `GET /clusters/{id}` | Cluster detail: accounts with per-account stats, extractions, cluster-level aggregates |
| `PUT /clusters/{id}` | Update cluster name. Body: `{ name }` |
| `DELETE /clusters/{id}` | Delete cluster. Cascades to accounts. Unlinks extractions (sets `cluster_id` to null) |

### Account Management

| Method | Path | Description |
|--------|------|-------------|
| `POST /clusters/{id}/accounts` | Add account. Body: `{ platform, handle }` |
| `DELETE /clusters/{id}/accounts/{account_id}` | Remove account (cascades posts) |

### Post Tracking

| Method | Path | Description |
|--------|------|-------------|
| `POST /clusters/{id}/accounts/{account_id}/posts` | Log a post. Body: `{ clip_id?, views?, likes?, comments?, shares?, posted_at? }` |
| `PUT /clusters/{id}/accounts/{account_id}/posts/{post_id}` | Update post stats. Body: `{ views?, likes?, comments?, shares? }` |
| `DELETE /clusters/{id}/accounts/{account_id}/posts/{post_id}` | Delete a post |

### Existing Route Change

`POST /clips/extract` — add optional `cluster_id` field to `ExtractClipsRequest`. When provided, the extraction is linked to that cluster.

### Cluster Detail Response Shape

```json
{
  "id": "uuid",
  "name": "Charlie Morgan Minecraft Splitscreen",
  "created_at": "iso8601",
  "accounts": [
    {
      "id": "uuid",
      "platform": "tiktok",
      "handle": "@charlieminecraft",
      "stats": { "views": 15000, "likes": 800, "comments": 45, "shares": 120 },
      "posts": [
        {
          "id": "uuid",
          "clip_id": "uuid|null",
          "platform_post_id": "string|null",
          "views": 5000,
          "likes": 300,
          "comments": 15,
          "shares": 40,
          "posted_at": "iso8601|null",
          "created_at": "iso8601"
        }
      ]
    }
  ],
  "extractions": [
    {
      "id": "uuid",
      "status": "completed",
      "youtube_url": "...",
      "video_title": "...",
      "created_at": "iso8601"
    }
  ],
  "stats": { "views": 45000, "likes": 2400, "comments": 135, "shares": 360 }
}
```

## UI Integration

All within the existing single-page `index.html`:

### Cluster List View
- Cards showing each cluster with name, account count, and aggregate stats (total views, likes, etc.)
- "Create Cluster" button opens a modal

### Cluster Detail View
- Accessed by clicking a cluster card
- Shows accounts with per-account stat breakdowns
- Shows extractions/clips belonging to this cluster
- Add/remove account controls

### Extraction Flow Change
- When submitting a YouTube URL for clip extraction, an optional dropdown lets the user assign it to a cluster

### Create Cluster Modal
- Name input
- Add accounts: platform dropdown (YouTube/TikTok/Instagram) + handle text input
- Can add multiple accounts before saving

## Implementation Notes

- New Alembic migration for the three tables + `clip_extractions.cluster_id` column
- New SQLAlchemy models: `Cluster`, `ClusterAccount`, `AccountPost`
- New Pydantic schemas in `app/schemas/cluster.py`
- New route file `app/routes/clusters.py`
- Register router in `app/main.py`
- Platform enum shared between model and schema
- CASCADE delete on cluster -> accounts -> posts
- Extractions are unlinked (not deleted) when a cluster is deleted via `ondelete="SET NULL"`
- Adding new platforms requires an Alembic migration (DB-level enum)
