# Dashboard Redesign — Full Spec

## Overview

Complete redesign of the Armageddon dashboard (`app.armageddonlabs.io`). Bloomberg terminal density meets Armageddon amber premium aesthetic. The dashboard serves as the operational hub for the team — from source video extraction through clip generation, clipper assignment, and performance tracking.

## Target Users

Team members who manage the full content pipeline. Power users who need to move fast and see everything at a glance.

## Visual System

### Colors
- Background: `#050508`
- Panel fill: `#0a0a0e`
- Panel borders: `1px solid rgba(212,152,42,0.08)` (amber tint)
- Primary accent: `#d4982a` (amber) — labels, active states, CTAs
- Positive: `#22c55e` (green) — growth, success, online
- Alert: `#ef4444` (red) — failures, attention items, inactive
- Primary text: `#e0e0e0`
- Secondary text: `#888`
- Muted text: `#555`
- Panel gaps: 1px (Bloomberg style)

### Typography
- Font: JetBrains Mono throughout
- Panel labels: 8-9px, uppercase, letter-spacing 2px, amber
- Data values: 18-28px for hero stats, 11px for list items
- All monospace — reinforces the terminal/data aesthetic

### Effects
- Subtle backdrop blur on key stat cards (`backdrop-filter: blur(8px)`)
- Amber glow on hover states and active elements
- No heavy gradients — clean, flat panels with border definition

### Layout
- Top navigation bar (fixed)
- Content area: tiled panel grid with 1px gaps
- No sidebar — horizontal tabs maximize content width

## Navigation

Top bar, left to right:
- **Logo**: ARMAGEDDON in amber, letter-spaced
- **Tabs** (center): OVERVIEW | EXTRACT | LIBRARY | CLUSTERS | CLIPPERS
- **Right**: Credits count + user menu

Active tab indicated by amber underline. Tabs are monospace, uppercase, letter-spaced.

## Page 1: Overview (Command Center)

The home page. Bloomberg-style tiled grid showing operational status at a glance.

### Top Row — 4 Stat Cards
Compact horizontal cards with label, large number, and context:

| Card | Value | Context |
|------|-------|---------|
| PIPELINE | Count of active jobs | "X processing, Y queued" |
| VIEWS (7D) | Total views this week | "↑X% vs last week" (green/red) |
| POSTED | Videos posted this week | "X this week" |
| CLIPPERS | Active/total count | "X active now" |

Data sources:
- Pipeline: `GET /jobs?limit=100` — count by status
- Views: `GET /analytics/clusters/{id}/overview` — aggregate across clusters
- Posted: `GET /assignments?status=posted` — count recent
- Clippers: `GET /clippers` — count active, infer online from recent activity

### Main Grid — 2 Columns

**Left column (wider, ~60%):**

**Panel: Live Pipeline**
- Real-time list of extractions and jobs
- Each row: truncated title | status badge (EXTRACTING / COMPOSITING / QUEUED / DONE / FAILED)
- Click row → navigates to Library detail for that extraction
- Polls every 5 seconds
- Data: `GET /clips` (extractions) + `GET /jobs` (generation jobs)

**Panel: Top Performing Clips (7D)**
- Ranked by views
- Each row: view count | hook text excerpt | trend arrow (↑/→/↓)
- Data: `GET /analytics/accounts/{id}/current` cross-referenced with post data from clusters

**Right column (~40%):**

**Panel: Performance**
- Aggregated metrics: views, likes, comments, shares
- Each with absolute number + % change vs previous period
- Data: `GET /analytics/clusters/{id}/overview`

**Panel: Clipper Activity**
- Each clipper: status dot (green=active, red=inactive) | name | "X/Y" (posted/assigned today)
- Data: `GET /clippers` + `GET /assignments`

**Panel: Needs Attention (red-tinted border)**
- Unposted clips older than 2 days
- Clippers with 0 activity and pending assignments
- Failed jobs
- Data: derived from jobs + assignments queries

All panels auto-refresh on a 10-second interval.

## Page 2: Extract

Single-page flow — no multi-step wizard.

### Input Section (top)
- Large URL input field with placeholder "Paste YouTube or Instagram URL"
- File upload drag-drop zone (secondary, below or beside URL input)
- Cluster assignment dropdown (optional)
- EXTRACT button (amber, prominent)

### Progress Section (appears after extract triggered)
- Inline progress bar showing stages: DOWNLOADING → TRANSCRIBING → ANALYZING → EXTRACTING
- Current stage highlighted in amber, completed stages in green
- Polls `GET /clips/{id}` for status updates

### Results Section (appears when done)
- Clips grid with:
  - Virality score badge (color-coded: 90+ green, 70-89 amber, 50-69 muted)
  - Hook text
  - Duration
  - Play button for preview
- Action buttons: "Generate Videos" (opens gameplay selector inline) | "Open in Library"

Data: `POST /clips/extract` or `POST /clips/import` to create, `GET /clips/{id}` to poll.

## Page 3: Library

### List View — Dense Table

**Search + Filters (top):**
- Search input (searches video titles)
- Filter pills: All | Processing | Ready | Posted
- Sortable by any column

**Table columns:**

| Column | Data | Source |
|--------|------|--------|
| Title | Video title (truncated) | extraction.video_title |
| Source | YT/IG/Upload icon | extraction.source_type |
| Clips | Clip count | extraction.clips.length |
| Generated | Count of completed jobs | `GET /jobs?source_prefix=clips/{id}/` |
| Posted | Count of posted assignments | derived from assignments |
| Views | Total views across posts | from analytics/post data |
| Date | Creation date | extraction.created_at |
| Status | Badge | extraction.status |

Click row → opens detail view.

### Detail View — Three Column Layout

**Header bar:**
- Back button (← LIBRARY)
- Video title
- Source URL (clickable link)
- Status badge
- Date

**Left Column — Clips (~35%)**
- Clip cards, sorted by virality score descending
- Each card: virality badge | hook text | duration | play button
- Click hook text to edit transcript inline (contenteditable, save on blur)
- Checkbox on each clip for selecting to generate

**Center Column — Generated Videos (~35%)**
- Top: Generate bar with gameplay multi-select + caption settings (collapsible) + GENERATE button
- Below: Job list grouped by clip
  - Each group header: clip hook text (truncated)
  - Each row: gameplay name | status badge | WATCH button | DL button
- Completed jobs show video preview on WATCH click (modal or inline player)
- Data: `GET /jobs?source_prefix=clips/{extraction_id}/&limit=100`

**Right Column — Distribution (~30%)**
- Per-video assignment status:
  - Video name → clipper name → account handle → status (assigned/posted)
  - Post URL if posted
  - View count if available
- ASSIGN button at top — modal to pick clipper + account + caption/hashtags
- Data: `GET /assignments` filtered by video keys from this extraction
- Note: need new API endpoint or query param to filter assignments by video_key

## Page 4: Clusters

### Grid View — Cluster Cards

Each card:
- Cluster name
- Account count
- Total views (aggregated from analytics)
- Total likes
- Trend indicator (up/down vs last week)

Create Cluster button (top right). Click card → opens detail.

### Cluster Detail View

**Header:** Cluster name (editable inline) | Delete button

**Accounts Table:**

| Column | Data |
|--------|------|
| Platform | Icon (TikTok/YT/IG) |
| Handle | @username |
| Followers | From analytics snapshot |
| Views (7D) | From analytics growth |
| Posts (7D) | Count from account_posts |
| Growth % | Follower change from analytics |

- Add Account button (form: platform dropdown, handle input)
- Click row → expand inline showing:
  - Credentials (hidden by default, click to reveal)
  - Recent post history with metrics
  - Analytics chart placeholder (future: sparkline of views over time)

Data:
- `GET /clusters/{id}` for accounts
- `GET /analytics/accounts/{id}/current` for follower/view data
- `GET /analytics/accounts/{id}/growth` for trends

**Bottom: Assigned Extractions**
- Table of extractions assigned to this cluster (same format as Library list)
- Data: `GET /clips?cluster_id={id}` (need to add cluster filter to clips endpoint)

## Page 5: Clippers

### List View — Clipper Table

| Column | Data |
|--------|------|
| Name | clipper.name |
| Email | clipper.email |
| Status | Active/Inactive badge |
| Accounts | Count of linked accounts |
| Posted Today | Count from today's assignments |
| Pending | Count of unposted assignments |
| Last Active | Derived from most recent posted_at |

- Create Clipper button (top right) — modal with email, password, name
- Click row → expand inline

### Clipper Detail (inline expand)

**Info section:**
- Name, email, status
- Reset Password button → calls `PUT /clippers/{id}/reset-password`
- Deactivate button → calls `DELETE /clippers/{id}`

**Linked Accounts:**
- List of accounts with platform + handle
- Link/unlink buttons
- Data: `GET /clippers/{id}`

**Assignment History:**
- Table: Video title | Account | Status | Post URL | Date
- Data: `GET /assignments?account_id={linked_account_ids}` (need to cross-reference)

**Bulk Assignment Flow (top-level button):**
1. Select clipper(s)
2. Pick videos from library (searchable dropdown)
3. Pick target accounts (filtered to clipper's linked accounts)
4. Add caption + hashtags
5. Submit → creates assignments via `POST /assignments`

## API Gaps

Endpoints that need to be added or modified:

1. **`GET /clips` — add `cluster_id` filter param** for Clusters page to show assigned extractions
2. **`GET /assignments` — add `video_key` filter param** for Library detail distribution column
3. **`GET /jobs` — `source_prefix` already added** (done in this session)
4. **`GET /clippers` — already exists** but clipper detail needs linked account assignment data cross-referenced
5. **Analytics endpoints already exist** but are unused — need to wire into Overview and Clusters pages

## Polling Strategy

- Overview page: 10-second interval for all panels
- Extract page: 3-second interval during active extraction
- Library detail: 5-second interval for jobs in progress
- Other pages: load on mount, manual refresh

## Out of Scope

- Mobile responsive (desktop-first for now)
- Real-time websockets (polling is fine for v1)
- Client-facing dashboard (future project)
- Billing/payments UI
- Dark/light theme toggle (dark only)
