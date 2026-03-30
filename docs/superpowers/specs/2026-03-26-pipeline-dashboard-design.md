# Pipeline Dashboard Design

**Date:** 2026-03-26
**Status:** Approved

## Overview

Replace the current linear clip extraction wizard with a modular pipeline where dubbing and splitscreen are independently togglable stages. Users pick clips, then choose which processing stages to apply: dub, splitscreen, or both.

## Current State

The CLIPS tab is a 4-step wizard:
1. Paste URL → extract clips
2. Pick clips
3. Pick gameplay + caption style
4. Generate splitscreen videos → results

Dubbing exists as a backend feature (`POST /dubbing`, worker pipeline) but has no frontend UI. The Library tab lets users revisit extractions and re-generate splitscreens.

## Proposed Flow

### Step 1: Input (unchanged)
- Paste YouTube/Instagram URL or upload file
- Optional cluster assignment
- Extracts clips via existing `/clips/extract` or `/clips/import` endpoints

### Step 2: Pick Clips (unchanged)
- Grid of extracted clips with virality scores, hooks, durations
- Click to select/deselect
- Preview button for each clip

### Step 3: Pipeline Options (new — replaces old steps 3+4)

For the selected clips, present two pipeline stage cards:

#### DUB stage (toggle on/off)
- Language picker: checkboxes for available languages (fr, es, he)
- Shows credit cost: "1 credit per language per clip"
- When enabled, **one `POST /dubbing` call per selected clip**, each with the chosen languages
- `source_url` for dubbing = the clip's `preview_url` from the extraction response (this is a direct download URL served by the API at `/storage/...`)

#### SPLITSCREEN stage (toggle on/off)
- Gameplay picker (existing grid)
- Caption style settings (existing: font, size, position, colors)
- Phone preview with caption animation (existing)

#### When both stages are enabled
- Show a single global toggle: **"Use dubbed audio for splitscreen?"**
- Default: yes (dubbed clip becomes the splitscreen source)
- If no: splitscreen uses original clip audio, dubbing outputs are separate downloads
- This toggle is hidden when only one stage is enabled

#### Validation
- At least one stage must be enabled
- DUB requires at least one language selected
- SPLITSCREEN requires at least one gameplay selected
- **Upfront credit check**: calculate total cost (dub credits + splitscreen credits) and compare against `user.credits_remaining` before enabling the GENERATE button. Show "Insufficient credits" warning if short.

### Step 4: Results (reworked)

Show outputs grouped by clip:

```
Clip: "The secret to scaling..."  (42s)
├── DUB
│   ├── Spanish ● completed  [WATCH] [DL]
│   ├── French  ◐ lip_syncing...
│   └── Hebrew  ○ pending
└── SPLITSCREEN
    ├── minecraft_parkour + Spanish audio ● completed [WATCH] [DL]
    ├── minecraft_parkour + French audio  ◐ processing...
    └── subway_surfers + Original audio   ● completed [WATCH] [DL]
```

- Poll both `/dubbing/{job_id}` and `/jobs/{job_id}` for status updates
- Status dots use existing color scheme (yellow=pending, blue=processing, green=completed, red=failed)
- Download and watch buttons on completed outputs

#### Polling strategy
- Stagger polls: dubbing jobs poll every 5 seconds, splitscreen jobs poll every 3 seconds
- Only poll jobs that are not in a terminal state (completed/failed)
- Cap at 20 concurrent active polls; if more, increase interval to 10 seconds

## Pipeline Execution Order

### Generate button pseudocode

```
totalCost = (dubEnabled ? selectedClips.length * selectedLanguages.length : 0)
          + (splitscreenEnabled ? selectedClips.length * selectedGameplay.length : 0)

if totalCost > user.credits_remaining:
  show "Insufficient credits" error
  return

// Track all jobs in client-side state
pipelineState = { clips: {} }

for each selectedClip:
  pipelineState.clips[clip.id] = { dubbingJobId: null, splitscreenJobIds: [] }

  if dubEnabled:
    resp = POST /dubbing { source_url: clip.preview_url, languages: selectedLanguages }
    pipelineState.clips[clip.id].dubbingJobId = resp.id

  if splitscreenEnabled AND NOT useDubbedAudio:
    resp = POST /jobs/batch { source_video_key: clip.storage_key, gameplay_ids, caption_style }
    pipelineState.clips[clip.id].splitscreenJobIds = resp.jobs.map(j => j.id)

// Navigate to step 4, start polling

// If useDubbedAudio AND splitscreenEnabled:
//   Poll dubbing jobs. As each dubbing output completes:
//     POST /jobs/batch { source_video_key: output.output_video_key, gameplay_ids, caption_style }
//     Add returned job IDs to pipelineState
```

### When both stages enabled with "use dubbed audio" = yes:

1. Submit dubbing jobs first via `POST /dubbing` (one per clip)
2. Poll until dubbing outputs complete per-language
3. As each language output completes, submit splitscreen job via `POST /jobs/batch` using `output.output_video_key` as `source_video_key`
4. Poll splitscreen jobs
5. Splitscreen jobs trickle in as dubbing outputs finish — no need to wait for all dubbing to complete

### When "use dubbed audio" = no, or only one stage enabled:
- Submit all jobs immediately in parallel
- Each stage is independent

## Failure Handling

| Scenario | Behavior |
|----------|----------|
| Dubbing partially fails (some languages succeed) | Splitscreen proceeds for successful languages only. Failed languages show error in results with no splitscreen row beneath them. |
| Dubbing fully fails, splitscreen enabled with dubbed audio | Show dubbing errors. No splitscreen jobs created. User can click "Retry with original audio" to submit splitscreen with original clip. |
| Dubbing fails, splitscreen enabled WITHOUT dubbed audio | Splitscreen is independent — proceeds normally. Dubbing errors shown separately. |
| Splitscreen fails for one gameplay | Other gameplay outputs unaffected. Failed job shows error. |
| User closes browser during processing | Jobs continue server-side. User can see results by navigating to Library tab and opening the extraction. |

## Library Tab Changes

When viewing an extraction detail in Library:
- Show existing splitscreen jobs (unchanged)
- Add a "DUBBING" section showing dubbing jobs
- **Association**: since the dubbing API has no extraction_id link, the frontend stores a `source_url → extraction_id` mapping in `localStorage` when creating dubbing jobs. Library tab reads this to show relevant dubbing jobs. Alternatively, `GET /dubbing` lists all user jobs — filter client-side by matching `source_url` against clip `preview_url`s in the extraction.
- Allow re-running the pipeline from Library (same stage toggles as step 3)

## Clusters Tab

No changes.

## API Usage

All existing endpoints — no new backend work needed:

| Action | Endpoint | Key fields |
|--------|----------|-----------|
| Extract clips | `POST /clips/extract` or `POST /clips/import` | |
| Get extraction | `GET /clips/{extraction_id}` | Returns clips with `preview_url` and `storage_key` |
| Create dubbing | `POST /dubbing` | `source_url` = clip's `preview_url`, `languages` = selected list |
| Poll dubbing | `GET /dubbing/{job_id}` | Returns `outputs[]` with `status`, `output_video_key`, `download_url` |
| Create splitscreen | `POST /jobs/batch` | `source_video_key` = clip's `storage_key` OR dubbing output's `output_video_key` |
| Poll splitscreen | `GET /jobs/{job_id}` | Returns `status`, `output_url` |
| List gameplay | `GET /gameplay` | Returns gameplay options with `id`, `name`, `duration` |

## UI Components

### Stage Card
Collapsible card with toggle header. When toggled on, expands to show stage-specific options. Consistent styling with existing `.caption-settings` panel.

### Language Picker
Row of language buttons (toggle on/off). Selected = red border + filled. Labels: ES (Spanish), FR (French), HE (Hebrew).

### Credit Summary
Bottom of step 3, always visible:
```
DUB:         3 clips x 2 languages = 6 credits
SPLITSCREEN: 3 clips x 1 gameplay  = 3 credits
TOTAL:       9 credits  (you have 12)
```
GENERATE button disabled if total > available.

### Pipeline Progress
Nested list grouped by clip → stage → output. Each row has status dot, label, and action buttons.

## Scope

### In scope
- New step 3 pipeline options UI
- Reworked step 4 results UI
- Dubbing API integration from frontend
- Library tab: show dubbing outputs alongside splitscreen jobs
- Sequential execution when dubbed audio feeds into splitscreen
- Upfront credit validation
- Failure handling with fallback options

### Out of scope
- New backend endpoints
- Additional languages beyond fr/es/he
- Batch dubbing across multiple extractions
