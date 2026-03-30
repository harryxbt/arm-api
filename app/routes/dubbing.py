# app/routes/dubbing.py
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.dubbing import DubbingJob, DubbingJobStatus, DubbingOutput, DubbingOutputStatus
from app.models.user import User
from app.schemas.dubbing import (
    CreateDubbingRequest,
    DubbingJobListResponse,
    DubbingJobResponse,
    DubbingJobSummaryResponse,
    DubbingOutputResponse,
)
from app.services.credits import deduct_credit
from app.storage import storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dubbing", tags=["dubbing"])


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


def _dispatch_dubbing(job_id: str) -> None:
    """Dispatch dubbing to Celery if available, otherwise process in background thread."""
    if _is_celery_available():
        from app.dubbing_worker import process_dubbing_task
        process_dubbing_task.delay(job_id)
    else:
        import threading
        from app.dubbing_worker import _process_dubbing_inline
        logger.info("Celery unavailable, processing dubbing %s in background thread", job_id)
        t = threading.Thread(target=_process_dubbing_inline, args=(job_id,), daemon=True)
        t.start()


def _output_to_response(output: DubbingOutput) -> DubbingOutputResponse:
    download_url = None
    if output.output_video_key:
        download_url = storage.get_download_url(output.output_video_key)
    return DubbingOutputResponse(
        id=str(output.id),
        language=output.language,
        status=output.status.value,
        output_video_key=output.output_video_key,
        download_url=download_url,
        error_message=output.error_message,
        started_at=output.started_at.isoformat() if output.started_at else None,
        completed_at=output.completed_at.isoformat() if output.completed_at else None,
    )


def _job_to_response(job: DubbingJob) -> DubbingJobResponse:
    return DubbingJobResponse(
        id=str(job.id),
        status=job.status.value,
        source_url=job.source_url,
        languages=job.languages,
        credits_charged=job.credits_charged,
        error_message=job.error_message,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        outputs=[_output_to_response(o) for o in job.outputs],
    )


@router.post("", response_model=DubbingJobResponse, status_code=status.HTTP_201_CREATED)
def create_dubbing(
    body: CreateDubbingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    num_languages = len(body.languages)

    # Check credits upfront
    if user.credits_remaining < num_languages:
        raise HTTPException(status_code=402, detail="Insufficient credits")

    job = DubbingJob(
        user_id=user.id,
        source_video_key="",  # set by worker after download
        source_url=body.source_url,
        languages=body.languages,
        credits_charged=num_languages,
    )
    db.add(job)
    db.flush()

    # Create one output per language
    for lang in body.languages:
        db.add(DubbingOutput(dubbing_job_id=job.id, language=lang))

    # Deduct credits in loop with commit=False
    for _ in range(num_languages):
        if not deduct_credit(db, user.id, commit=False):
            db.rollback()
            raise HTTPException(status_code=402, detail="Insufficient credits")

    db.commit()
    db.refresh(job)

    _dispatch_dubbing(str(job.id))

    return _job_to_response(job)


@router.get("/{job_id}", response_model=DubbingJobResponse)
def get_dubbing(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(DubbingJob).options(
        selectinload(DubbingJob.outputs)
    ).filter(
        DubbingJob.id == job_id,
        DubbingJob.user_id == user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Dubbing job not found")
    return _job_to_response(job)


@router.get("", response_model=DubbingJobListResponse)
def list_dubbing(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(DubbingJob).filter(
        DubbingJob.user_id == user.id,
    ).order_by(DubbingJob.created_at.desc())

    if cursor:
        cursor_job = db.query(DubbingJob).filter(DubbingJob.id == cursor).first()
        if cursor_job:
            query = query.filter(DubbingJob.created_at < cursor_job.created_at)

    jobs = query.limit(limit + 1).all()
    next_cursor = str(jobs[-1].id) if len(jobs) > limit else None

    return DubbingJobListResponse(
        jobs=[
            DubbingJobSummaryResponse(
                id=str(j.id),
                status=j.status.value,
                source_url=j.source_url,
                languages=j.languages,
                credits_charged=j.credits_charged,
                created_at=j.created_at.isoformat(),
            )
            for j in jobs[:limit]
        ],
        next_cursor=next_cursor,
    )
