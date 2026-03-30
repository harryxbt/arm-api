# Armageddon API

Video multiplication API — upload a source video, get back splitscreen variations with gameplay footage and burned-in captions.

## Quick Start (Local Dev)

```bash
# Install dependencies
pip install -r requirements.txt

# Create storage directories
mkdir -p storage/{uploads,gameplay,outputs}

# Start the server (SQLite, no Redis needed)
python3 -m uvicorn app.main:app --reload --port 8000
```

The API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

No Redis or Celery required for local dev — jobs process inline automatically.

## Prerequisites

- Python 3.11+
- FFmpeg installed (`brew install ffmpeg` on macOS)
- Deepgram API key (optional — captions are skipped if unavailable)

Create a `.env` file for optional config:

```
DEEPGRAM_API_KEY=your_key_here
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

## Create a Dev User

```bash
# Sign up
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@test.com", "password": "password123"}'

# Response includes access_token
```

Or use the existing dev user (pre-seeded with 100 credits):

```bash
# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@armageddon.com", "password": "devpass123"}'
```

Save the `access_token` from the response — you'll need it for all authenticated requests.

```bash
export TOKEN="eyJhbG..."
```

## Testing the API

### 1. Check Your Account

```bash
curl -s http://localhost:8000/auth/me \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 2. Upload a Source Video

```bash
curl -X POST http://localhost:8000/videos/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/your/video.mp4"
```

Returns `{"key": "uploads/abc123_video.mp4"}` — save this key.

### 3. Upload Custom Gameplay (Optional)

```bash
curl -X POST http://localhost:8000/videos/upload-gameplay \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/gameplay.mp4"
```

### 4. Browse Gameplay Library

```bash
curl -s http://localhost:8000/gameplay \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Returns available gameplay clips with their IDs.

### 5. Create a Single Job

Using a gameplay library clip (by ID):

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_video_key": "uploads/abc123_video.mp4",
    "gameplay_id": "GAMEPLAY_ID_HERE"
  }' | python3 -m json.tool
```

Using a custom gameplay file (by key):

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_video_key": "uploads/abc123_video.mp4",
    "gameplay_key": "gameplay/your_gameplay.mp4"
  }' | python3 -m json.tool
```

Costs 1 credit. In dev mode (no Redis), the job processes synchronously — the response returns with `status: "pending"` but processing starts immediately.

### 6. Create a Batch Job

Same source video paired with multiple gameplay clips in one call:

```bash
curl -s -X POST http://localhost:8000/jobs/batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_video_key": "uploads/abc123_video.mp4",
    "gameplay_ids": ["GAMEPLAY_ID_1", "GAMEPLAY_ID_2"]
  }' | python3 -m json.tool
```

- Costs 1 credit per gameplay clip
- All credits deducted atomically (all-or-nothing)
- Maximum 20 gameplay clips per batch
- All gameplay IDs must exist, otherwise the entire request fails

### 7. Check Job Status

```bash
curl -s http://localhost:8000/jobs/JOB_ID \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Statuses: `pending` → `processing` → `completed` / `failed`

When completed, the response includes `output_url` pointing to the generated video.

### 8. List All Jobs

```bash
curl -s "http://localhost:8000/jobs?limit=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Supports cursor-based pagination via `?cursor=LAST_JOB_ID&limit=20`.

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/auth/signup` | Create account | No |
| `POST` | `/auth/login` | Get access token | No |
| `POST` | `/auth/refresh` | Rotate refresh token | Cookie |
| `GET` | `/auth/me` | Current user info | Yes |
| `POST` | `/videos/upload` | Upload source video (max 500MB) | Yes |
| `POST` | `/videos/upload-gameplay` | Upload custom gameplay | Yes |
| `GET` | `/gameplay` | List gameplay library | Yes |
| `POST` | `/jobs` | Create single job (1 credit) | Yes |
| `POST` | `/jobs/batch` | Create batch jobs (N credits) | Yes |
| `GET` | `/jobs/{id}` | Get job status | Yes |
| `GET` | `/jobs` | List jobs (paginated) | Yes |
| `POST` | `/billing/checkout` | Start Stripe checkout | Yes |
| `GET` | `/billing/portal` | Open Stripe customer portal | Yes |
| `POST` | `/billing/webhook` | Stripe webhook receiver | No |
| `GET` | `/health` | Health check | No |

## What the Pipeline Does

1. Downloads source video and gameplay footage from storage
2. Transcribes audio using Deepgram (word-level timestamps)
3. Generates ASS subtitle file (4-word chunks)
4. FFmpeg composites a 1080x1920 (9:16) splitscreen:
   - Source video on top (crop-to-fill, no black bars)
   - Gameplay on bottom (loops if shorter than source)
   - Captions burned in
5. Uploads output to storage

## Production Setup

For production with Celery workers:

```bash
# Start Redis
docker compose up -d

# Run migrations
alembic upgrade head

# Start API
uvicorn app.main:app --port 8000

# Start worker (separate terminal)
celery -A app.worker worker --loglevel=info

# Start Stripe webhook forwarding (separate terminal)
stripe listen --forward-to localhost:8000/billing/webhook
```

Set `DATABASE_URL` to your Supabase connection string for production.

## Error Codes

| Code | Meaning |
|------|---------|
| `400` | Bad request (invalid file type, empty batch, etc.) |
| `401` | Missing or invalid auth token |
| `402` | Insufficient credits |
| `404` | Resource not found (job, gameplay clip) |
| `500` | Server error |

Failed jobs automatically refund the deducted credit.
