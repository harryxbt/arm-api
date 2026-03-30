import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction, ExtractionStatus, SourceType
from app.models.user import User
from app.schemas.clip import (
    ClipResponse,
    ExtractClipsRequest,
    ExtractionListResponse,
    ExtractionResponse,
    ExtractionSummaryResponse,
    UpdateClipRequest,
    UpdateLastGameplayRequest,
)
from app.services.credits import deduct_credit
from app.storage import storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clips", tags=["clips"])


def _is_celery_available() -> bool:
    """Check if Redis/Celery is available for async processing."""
    try:
        from redis import Redis
        from app.config import settings
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


def _process_extraction_inline(extraction_id: str) -> None:
    """Process a clip extraction synchronously (dev mode, no Celery).

    Inline path does not retry (same as existing job inline fallback).
    """
    import os
    import subprocess
    import uuid as uuid_mod
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.credits import refund_credit
    from app.services.youtube import download_video
    from app.services.transcription import transcribe_audio, transcribe_segments
    from app.services.clip_analyzer import analyze_segments
    from app.services.face_reframer import reframe_to_vertical

    engine = create_engine(settings.database_url)
    LocalSession = sessionmaker(bind=engine)
    db = LocalSession()
    try:
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if not extraction:
            logger.warning("Extraction %s not found, skipping", extraction_id)
            return

        logger.info("[%s] Starting extraction for %s", extraction_id[:8], extraction.youtube_url)

        # Stage 1: Download
        extraction.status = ExtractionStatus.downloading
        db.commit()
        download_dir = os.path.join(settings.storage_dir, "downloads", extraction_id)
        os.makedirs(download_dir, exist_ok=True)
        logger.info("[%s] Downloading video...", extraction_id[:8])
        import time as _time
        t0 = _time.time()
        meta = download_video(extraction.youtube_url, download_dir)
        logger.info("[%s] Download complete: '%s' (%.1fs, %.1f min duration)",
                     extraction_id[:8], meta["title"], _time.time() - t0, meta["duration"] / 60)
        extraction.video_title = meta["title"]
        extraction.video_duration = meta["duration"]
        extraction.source_video_key = f"downloads/{extraction_id}/{os.path.basename(meta['filepath'])}"
        db.commit()
        source_path = meta["filepath"]
        file_size_mb = os.path.getsize(source_path) / (1024 * 1024)
        logger.info("[%s] Source file: %s (%.1f MB)", extraction_id[:8], source_path, file_size_mb)

        # Stage 2: Transcribe (segments for sentence-level boundaries)
        extraction.status = ExtractionStatus.transcribing
        db.commit()
        logger.info("[%s] Transcribing segments (Whisper call 1/2)...", extraction_id[:8])
        t0 = _time.time()
        segments = transcribe_segments(source_path)
        logger.info("[%s] Segments done: %d segments in %.1fs", extraction_id[:8], len(segments), _time.time() - t0)

        logger.info("[%s] Transcribing words (Whisper call 2/2)...", extraction_id[:8])
        t0 = _time.time()
        words = transcribe_audio(source_path)
        logger.info("[%s] Words done: %d words in %.1fs", extraction_id[:8], len(words), _time.time() - t0)

        if not segments:
            raise ValueError("No speech detected in video")

        # Stage 3: Analyze (using punctuated segments)
        extraction.status = ExtractionStatus.analyzing
        db.commit()
        logger.info("[%s] Analyzing segments for clips...", extraction_id[:8])
        t0 = _time.time()
        clip_suggestions = analyze_segments(segments, video_duration=meta["duration"])
        logger.info("[%s] Analysis done: %d clips suggested in %.1fs",
                     extraction_id[:8], len(clip_suggestions) if clip_suggestions else 0, _time.time() - t0)
        if not clip_suggestions:
            raise ValueError("No valid clips found for this video")

        # Stage 4: Extract & Reframe
        extraction.status = ExtractionStatus.extracting
        db.commit()
        clips_dir = os.path.join(settings.storage_dir, "clips", extraction_id)
        os.makedirs(clips_dir, exist_ok=True)
        logger.info("[%s] Extracting %d clips...", extraction_id[:8], len(clip_suggestions))

        for i, suggestion in enumerate(clip_suggestions, 1):
            clip_id = str(uuid_mod.uuid4())
            raw_path = os.path.join(clips_dir, f"{clip_id}_raw.mp4")
            final_path = os.path.join(clips_dir, f"{clip_id}.mp4")
            duration = suggestion["end_time"] - suggestion["start_time"]
            logger.info("[%s] Clip %d/%d: %.1fs-%.1fs (%.0fs)",
                         extraction_id[:8], i, len(clip_suggestions),
                         suggestion["start_time"], suggestion["end_time"], duration)

            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(suggestion["start_time"]),
                 "-i", source_path, "-t", str(duration),
                 "-c", "copy", "-avoid_negative_ts", "make_zero", raw_path],
                capture_output=True, timeout=60,
            )

            try:
                reframed = reframe_to_vertical(raw_path, final_path)
                logger.info("[%s] Clip %d reframed to vertical", extraction_id[:8], i)
            except Exception as reframe_err:
                logger.warning("[%s] Clip %d reframe failed (%s), using raw", extraction_id[:8], i, reframe_err)
                os.rename(raw_path, final_path)
                reframed = False

            if os.path.exists(raw_path) and raw_path != final_path:
                os.remove(raw_path)

            clip_words = [w["word"] for w in words
                          if w["start"] >= suggestion["start_time"]
                          and w["end"] <= suggestion["end_time"]]

            clip = Clip(
                id=clip_id,
                extraction_id=extraction_id,
                storage_key=f"clips/{extraction_id}/{clip_id}.mp4",
                start_time=suggestion["start_time"],
                end_time=suggestion["end_time"],
                duration=duration,
                virality_score=suggestion.get("virality_score", 0),
                hook_text=suggestion.get("hook_text", ""),
                transcript_text=" ".join(clip_words),
                reframed=reframed,
            )
            db.add(clip)

        # Stage 5: Complete
        extraction.status = ExtractionStatus.completed
        extraction.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("[%s] Extraction complete: %d clips created", extraction_id[:8], len(clip_suggestions))

    except Exception as e:
        db.rollback()
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if extraction:
            extraction.status = ExtractionStatus.failed
            extraction.error_message = str(e)[:1000]
            extraction.completed_at = datetime.now(timezone.utc)
            db.flush()
            refund_credit(db, extraction.user_id, job_id=None, commit=False)
            db.commit()
        logger.exception("Inline extraction failed for %s", extraction_id)
    finally:
        db.close()


def _dispatch_extraction(extraction_id: str) -> None:
    """Dispatch extraction to Celery if available, otherwise process in background thread."""
    if _is_celery_available():
        from app.clip_worker import extract_clips_task
        extract_clips_task.delay(extraction_id)
    else:
        import threading
        logger.info("Celery unavailable, processing extraction %s in background thread", extraction_id)
        t = threading.Thread(target=_process_extraction_inline, args=(extraction_id,), daemon=True)
        t.start()


def _process_import_inline(extraction_id: str) -> None:
    """Process an imported video (IG URL or uploaded file). Transcribe only, no clip analysis."""
    import os
    import time as _time
    import uuid as uuid_mod
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.transcription import transcribe_audio

    engine = create_engine(settings.database_url)
    LocalSession = sessionmaker(bind=engine)
    db = LocalSession()
    try:
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if not extraction:
            return

        source_path = None

        # Stage 1: Download (if Instagram URL)
        if extraction.source_type == SourceType.instagram:
            extraction.status = ExtractionStatus.downloading
            db.commit()
            logger.info("[%s] Downloading Instagram video...", extraction_id[:8])
            t0 = _time.time()
            from app.services.youtube import download_video
            download_dir = os.path.join(settings.storage_dir, "downloads", extraction_id)
            os.makedirs(download_dir, exist_ok=True)
            meta = download_video(extraction.youtube_url, download_dir)
            extraction.video_title = meta["title"]
            extraction.video_duration = meta["duration"]
            extraction.source_video_key = f"downloads/{extraction_id}/{os.path.basename(meta['filepath'])}"
            db.commit()
            source_path = meta["filepath"]
            logger.info("[%s] Download complete in %.1fs", extraction_id[:8], _time.time() - t0)
        elif extraction.source_type == SourceType.upload:
            # File already saved to storage during upload
            source_path = os.path.join(settings.storage_dir, extraction.source_video_key)
            # Get duration via ffprobe
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", source_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                extraction.video_duration = float(result.stdout.strip())
            db.commit()

        if not source_path or not os.path.exists(source_path):
            raise ValueError(f"Source file not found: {source_path}")

        # Stage 2: Transcribe
        extraction.status = ExtractionStatus.transcribing
        db.commit()
        logger.info("[%s] Transcribing imported video...", extraction_id[:8])
        t0 = _time.time()
        words = transcribe_audio(source_path)
        logger.info("[%s] Transcription done: %d words in %.1fs", extraction_id[:8], len(words), _time.time() - t0)

        # Stage 3: Create single clip (no analysis)
        extraction.status = ExtractionStatus.extracting
        db.commit()

        clip_id = str(uuid_mod.uuid4())
        duration = extraction.video_duration or 0.0
        transcript_text = " ".join(w["word"] for w in words)

        clip = Clip(
            id=clip_id,
            extraction_id=extraction_id,
            storage_key=extraction.source_video_key,
            start_time=0.0,
            end_time=duration,
            duration=duration,
            virality_score=0,
            hook_text="",
            transcript_text=transcript_text,
            reframed=False,
        )
        db.add(clip)

        extraction.status = ExtractionStatus.completed
        extraction.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("[%s] Import complete: single clip created", extraction_id[:8])

    except Exception as e:
        db.rollback()
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if extraction:
            extraction.status = ExtractionStatus.failed
            extraction.error_message = str(e)[:1000]
            extraction.completed_at = datetime.now(timezone.utc)
            db.flush()
            from app.services.credits import refund_credit
            refund_credit(db, extraction.user_id, job_id=None, commit=False)
            db.commit()
        logger.exception("Import failed for %s", extraction_id)
    finally:
        db.close()


def _dispatch_import(extraction_id: str) -> None:
    """Dispatch import processing in background thread."""
    import threading
    logger.info("Processing import %s in background thread", extraction_id)
    t = threading.Thread(target=_process_import_inline, args=(extraction_id,), daemon=True)
    t.start()


def _clip_to_response(clip: Clip) -> ClipResponse:
    preview_url = storage.get_download_url(clip.storage_key) if clip.storage_key else None
    return ClipResponse(
        id=str(clip.id),
        storage_key=clip.storage_key,
        start_time=clip.start_time,
        end_time=clip.end_time,
        duration=clip.duration,
        virality_score=clip.virality_score,
        hook_text=clip.hook_text,
        transcript_text=clip.transcript_text,
        reframed=clip.reframed,
        preview_url=preview_url,
        created_at=clip.created_at.isoformat(),
    )


def _extraction_to_response(extraction: ClipExtraction) -> ExtractionResponse:
    sorted_clips = sorted(extraction.clips, key=lambda c: c.virality_score, reverse=True)
    return ExtractionResponse(
        id=str(extraction.id),
        status=extraction.status.value,
        youtube_url=extraction.youtube_url,
        video_title=extraction.video_title,
        video_duration=extraction.video_duration,
        error_message=extraction.error_message,
        created_at=extraction.created_at.isoformat(),
        completed_at=extraction.completed_at.isoformat() if extraction.completed_at else None,
        clips=[_clip_to_response(c) for c in sorted_clips],
        last_gameplay_ids=extraction.last_gameplay_ids,
        source_type=extraction.source_type.value,
    )


# Route order is critical — specific paths before parameterised paths.
# POST /extract, POST /import, PUT /{id}/last-gameplay, PUT /{id}/{clip_id},
# GET /{id}, GET ""

@router.post("/extract", response_model=ExtractionResponse, status_code=status.HTTP_201_CREATED)
def create_extraction(
    body: ExtractClipsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extraction = ClipExtraction(
        user_id=user.id,
        youtube_url=body.youtube_url,
        cluster_id=body.cluster_id,
    )
    db.add(extraction)
    db.flush()

    if not deduct_credit(db, user.id, commit=False):
        db.rollback()
        raise HTTPException(status_code=402, detail="Insufficient credits")

    db.commit()
    db.refresh(extraction)

    _dispatch_extraction(str(extraction.id))

    return _extraction_to_response(extraction)


@router.post("/import", response_model=ExtractionResponse, status_code=status.HTTP_201_CREATED)
def import_video(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
    cluster_id: str | None = Form(None),
):
    import os
    import re
    import shutil
    from app.config import settings

    if not url and not file:
        raise HTTPException(status_code=422, detail="Provide either a URL or a file")
    if url and file:
        raise HTTPException(status_code=422, detail="Provide either a URL or a file, not both")

    if url:
        # Validate Instagram URL
        ig_pattern = re.compile(
            r"^(https?://)?(www\.)?instagram\.com/(p|reel|reels)/[\w-]+"
        )
        if not ig_pattern.match(url):
            raise HTTPException(status_code=422, detail="Invalid Instagram URL. Supported: instagram.com/p/, /reel/, /reels/")
        source_type = SourceType.instagram
        source_url = url
    else:
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=422, detail="File must have a filename")
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in (".mp4", ".mov", ".webm"):
            raise HTTPException(status_code=422, detail="Supported formats: .mp4, .mov, .webm")
        source_type = SourceType.upload
        source_url = file.filename

    extraction = ClipExtraction(
        user_id=user.id,
        youtube_url=source_url,
        source_type=source_type,
        cluster_id=cluster_id,
    )
    db.add(extraction)
    db.flush()

    if not deduct_credit(db, user.id, commit=False):
        db.rollback()
        raise HTTPException(status_code=402, detail="Insufficient credits")

    # Save uploaded file to storage (chunked to avoid memory issues with large files)
    if file:
        upload_dir = os.path.join(settings.storage_dir, "downloads", extraction.id)
        os.makedirs(upload_dir, exist_ok=True)
        save_path = os.path.join(upload_dir, f"source{ext}")
        with open(save_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        extraction.source_video_key = f"downloads/{extraction.id}/source{ext}"
        extraction.video_title = file.filename

    db.commit()
    db.refresh(extraction)

    _dispatch_import(str(extraction.id))

    return _extraction_to_response(extraction)


@router.put("/{extraction_id}/last-gameplay", response_model=ExtractionResponse)
def update_last_gameplay(
    extraction_id: str,
    body: UpdateLastGameplayRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extraction = db.query(ClipExtraction).filter(
        ClipExtraction.id == extraction_id,
        ClipExtraction.user_id == user.id,
    ).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")

    extraction.last_gameplay_ids = body.gameplay_ids
    db.commit()
    db.refresh(extraction)
    return _extraction_to_response(extraction)


@router.put("/{extraction_id}/{clip_id}", response_model=ClipResponse)
def update_clip(
    extraction_id: str,
    clip_id: str,
    body: UpdateClipRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extraction = db.query(ClipExtraction).filter(
        ClipExtraction.id == extraction_id,
        ClipExtraction.user_id == user.id,
    ).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")

    clip = db.query(Clip).filter(
        Clip.id == clip_id,
        Clip.extraction_id == extraction_id,
    ).first()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clip.transcript_text = body.transcript_text
    db.commit()
    db.refresh(clip)
    return _clip_to_response(clip)


@router.get("/{extraction_id}", response_model=ExtractionResponse)
def get_extraction(
    extraction_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extraction = db.query(ClipExtraction).filter(
        ClipExtraction.id == extraction_id,
        ClipExtraction.user_id == user.id,
    ).first()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return _extraction_to_response(extraction)


@router.get("", response_model=ExtractionListResponse)
def list_extractions(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ClipExtraction).options(
        selectinload(ClipExtraction.clips)
    ).filter(
        ClipExtraction.user_id == user.id,
    ).order_by(ClipExtraction.created_at.desc())

    if cursor:
        cursor_ext = db.query(ClipExtraction).filter(ClipExtraction.id == cursor).first()
        if cursor_ext:
            query = query.filter(ClipExtraction.created_at < cursor_ext.created_at)

    extractions = query.limit(limit + 1).all()
    next_cursor = str(extractions[-1].id) if len(extractions) > limit else None

    return ExtractionListResponse(
        extractions=[
            ExtractionSummaryResponse(
                id=str(e.id),
                status=e.status.value,
                youtube_url=e.youtube_url,
                video_title=e.video_title,
                created_at=e.created_at.isoformat(),
                clip_count=len(e.clips),
                source_type=e.source_type.value,
            )
            for e in extractions[:limit]
        ],
        next_cursor=next_cursor,
    )
