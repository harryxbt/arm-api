import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.job import Job, JobStatus
from app.models.gameplay import GameplayClip
from app.schemas.job import CreateJobRequest, CreateBatchJobRequest, JobResponse, BatchJobResponse, JobListResponse
from app.services.credits import deduct_credit
from app.storage import storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


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


def _process_inline(job_id: str) -> None:
    """Process a video job synchronously (dev mode, no Celery)."""
    from app.config import settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.transcription import transcribe_audio
    from app.services.video_processor import generate_ass_subtitles, composite_splitscreen
    from app.services.credits import refund_credit

    engine = create_engine(settings.database_url)
    LocalSession = sessionmaker(bind=engine)
    db = LocalSession()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        import time as _time

        job.status = JobStatus.processing
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("[job %s] Starting splitscreen: src=%s gameplay=%s",
                     job_id[:8], job.source_video_key, job.gameplay_key)

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = storage.get_file(job.source_video_key)
            gameplay_path = storage.get_file(job.gameplay_key)
            logger.info("[job %s] Source: %s, Gameplay: %s", job_id[:8], source_path, gameplay_path)

            logger.info("[job %s] Transcribing for captions...", job_id[:8])
            t0 = _time.time()
            try:
                words = transcribe_audio(source_path)
                logger.info("[job %s] Transcription done: %d words in %.1fs", job_id[:8], len(words), _time.time() - t0)
            except Exception as te:
                logger.warning("[job %s] Transcription failed (%s), proceeding without captions", job_id[:8], te)
                words = []

            caption_style = None
            if job.caption_data and isinstance(job.caption_data, dict):
                caption_style = job.caption_data.get("style")
            job.caption_data = {"words": words, "style": caption_style}

            ass_path = None
            if words:
                ass_path = os.path.join(tmpdir, "captions.ass")
                generate_ass_subtitles(words, ass_path, style=caption_style)
                logger.info("[job %s] Captions generated: %s", job_id[:8], ass_path)

            output_filename = f"{uuid.uuid4()}.mp4"
            output_path = os.path.join(tmpdir, output_filename)
            logger.info("[job %s] Compositing splitscreen (this may take a while)...", job_id[:8])
            t0 = _time.time()
            composite_splitscreen(source_path, gameplay_path, ass_path, output_path)
            logger.info("[job %s] Compositing done in %.1fs", job_id[:8], _time.time() - t0)

            with open(output_path, "rb") as f:
                output_data = f.read()
            output_key = storage.save_file("outputs", output_filename, output_data)
            logger.info("[job %s] Output saved: %s (%.1f MB)", job_id[:8], output_key, len(output_data) / (1024*1024))

            job.output_video_key = output_key
            job.status = JobStatus.completed
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("[job %s] Complete!", job_id[:8])

    except Exception as e:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.failed
            job.error_message = str(e)[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.flush()
            refund_credit(db, job.user_id, job.id, commit=False)
            db.commit()
        logger.exception("Inline processing failed for job %s", job_id)
    finally:
        db.close()


def _dispatch_job(job_id: str) -> None:
    """Dispatch job to Celery if available, otherwise process in background thread."""
    if _is_celery_available():
        from app.worker import process_video_task
        process_video_task.delay(job_id)
    else:
        import threading
        logger.info("Celery unavailable, processing job %s in background thread", job_id)
        t = threading.Thread(target=_process_inline, args=(job_id,), daemon=True)
        t.start()


def _job_to_response(job: Job) -> JobResponse:
    output_url = storage.get_download_url(job.output_video_key) if job.output_video_key else None
    return JobResponse(
        id=str(job.id),
        status=job.status.value,
        source_video_key=job.source_video_key,
        gameplay_key=job.gameplay_key,
        output_url=output_url,
        error_message=job.error_message,
        created_at=job.created_at.isoformat(),
    )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(body: CreateJobRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Resolve gameplay key
    if body.gameplay_id:
        clip = db.query(GameplayClip).filter(GameplayClip.id == body.gameplay_id, GameplayClip.active == True).first()
        if not clip:
            raise HTTPException(status_code=404, detail="Gameplay clip not found")
        gameplay_key = clip.storage_key
    elif body.gameplay_key:
        gameplay_key = body.gameplay_key
    else:
        raise HTTPException(status_code=400, detail="Provide gameplay_id or gameplay_key")

    # Store caption style in caption_data if provided
    caption_data = None
    if body.caption_style:
        caption_data = {"style": body.caption_style.model_dump(exclude_none=True)}

    # Create job + deduct credit in a single transaction
    job = Job(
        user_id=user.id,
        source_video_key=body.source_video_key,
        gameplay_key=gameplay_key,
        caption_data=caption_data,
    )
    db.add(job)
    db.flush()  # get job.id before credit deduction

    if not deduct_credit(db, user.id, job.id, commit=False):
        db.rollback()
        raise HTTPException(status_code=402, detail="Insufficient credits")

    db.commit()
    db.refresh(job)

    _dispatch_job(str(job.id))

    return _job_to_response(job)


@router.post("/batch", response_model=BatchJobResponse, status_code=status.HTTP_201_CREATED)
def create_batch_jobs(body: CreateBatchJobRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Resolve all gameplay clips upfront
    clips = db.query(GameplayClip).filter(
        GameplayClip.id.in_(body.gameplay_ids),
        GameplayClip.active == True,
    ).all()
    found_ids = {clip.id for clip in clips}
    missing = [gid for gid in body.gameplay_ids if gid not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Gameplay clips not found: {', '.join(missing)}")

    # Store caption style if provided
    caption_data = None
    if body.caption_style:
        caption_data = {"style": body.caption_style.model_dump(exclude_none=True)}

    # Create all jobs and deduct credits in a single transaction
    jobs = []
    for clip in clips:
        job = Job(
            user_id=user.id,
            source_video_key=body.source_video_key,
            gameplay_key=clip.storage_key,
            caption_data=caption_data,
        )
        db.add(job)
        db.flush()

        if not deduct_credit(db, user.id, job.id, commit=False):
            db.rollback()
            raise HTTPException(status_code=402, detail=f"Insufficient credits (needed {len(body.gameplay_ids)}, failed at #{len(jobs) + 1})")

        jobs.append(job)

    db.commit()
    for job in jobs:
        db.refresh(job)

    # Dispatch all jobs
    for job in jobs:
        _dispatch_job(str(job.id))

    return BatchJobResponse(
        jobs=[_job_to_response(j) for j in jobs],
        credits_deducted=len(jobs),
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.get("", response_model=JobListResponse)
def list_jobs(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Job).filter(Job.user_id == user.id).order_by(Job.created_at.desc())
    if cursor:
        cursor_job = db.query(Job).filter(Job.id == cursor).first()
        if cursor_job:
            query = query.filter(Job.created_at < cursor_job.created_at)
    jobs = query.limit(limit + 1).all()
    next_cursor = str(jobs[-1].id) if len(jobs) > limit else None
    return JobListResponse(
        jobs=[_job_to_response(j) for j in jobs[:limit]],
        next_cursor=next_cursor,
    )
