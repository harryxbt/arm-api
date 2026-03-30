# app/dubbing_worker.py
import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.dubbing import DubbingJob, DubbingJobStatus, DubbingOutput, DubbingOutputStatus
from app.services.credits import refund_credit
from app.services.elevenlabs import create_dubbing, poll_dubbing, download_dubbed_audio
from app.services.musetalk import run_lipsync
from app.services.youtube import download_video
from app.storage import storage
from app.worker import celery_app

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url)
DubbingWorkerSession = sessionmaker(bind=engine)

POLL_BACKOFF = [5, 10, 20, 40, 60]  # seconds, capped at 60
POLL_TIMEOUT = 1800  # 30 minutes
MAX_DUBBING_DURATION = 1800  # 30 minutes


def _poll_with_backoff(poll_fn, job_id: str, success_status: str, fail_statuses: set[str] | None = None) -> str:
    """Poll an async API with exponential backoff. Returns status string on success."""
    if fail_statuses is None:
        fail_statuses = {"failed"}
    start = time.time()
    attempt = 0
    while time.time() - start < POLL_TIMEOUT:
        status = poll_fn(job_id)
        if status == success_status:
            return status
        if status in fail_statuses:
            raise RuntimeError(f"External API job {job_id} failed (status={status})")
        delay = POLL_BACKOFF[min(attempt, len(POLL_BACKOFF) - 1)]
        time.sleep(delay)
        attempt += 1
    raise TimeoutError(f"Polling timed out after {POLL_TIMEOUT}s for job {job_id}")


def _check_parent_completion(db, dubbing_job_id: str) -> None:
    """If all outputs are terminal, finalize the parent job."""
    outputs = db.query(DubbingOutput).filter(
        DubbingOutput.dubbing_job_id == dubbing_job_id
    ).all()

    terminal = {DubbingOutputStatus.completed, DubbingOutputStatus.failed}
    if not all(o.status in terminal for o in outputs):
        return

    job = db.query(DubbingJob).filter(DubbingJob.id == dubbing_job_id).first()
    if not job or job.status in {DubbingJobStatus.completed, DubbingJobStatus.failed}:
        return

    any_success = any(o.status == DubbingOutputStatus.completed for o in outputs)
    job.status = DubbingJobStatus.completed if any_success else DubbingJobStatus.failed
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Dubbing job %s finalized as %s", dubbing_job_id, job.status.value)


@celery_app.task(name="process_dubbing", bind=True, max_retries=0)
def process_dubbing_task(self, job_id: str):
    """Main dubbing task: download source, then fan out per language."""
    db = DubbingWorkerSession()
    try:
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            return

        job.status = DubbingJobStatus.downloading
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Step 1: Acquire source video
        download_dir = os.path.join(settings.storage_dir, "dubbing", job_id)
        os.makedirs(download_dir, exist_ok=True)
        meta = download_video(job.source_url, download_dir)
        source_key = f"dubbing/{job_id}/{os.path.basename(meta['filepath'])}"
        job.source_video_key = source_key
        db.commit()

        # Validate duration (30 min max for dubbing)
        if meta["duration"] > MAX_DUBBING_DURATION:
            raise ValueError(
                f"Video too long ({meta['duration']:.0f}s, max {MAX_DUBBING_DURATION}s / 30 minutes)"
            )

        # Step 2: Fan out per language
        job.status = DubbingJobStatus.processing
        db.commit()

        outputs = db.query(DubbingOutput).filter(
            DubbingOutput.dubbing_job_id == job_id
        ).all()

        for output in outputs:
            process_dubbing_language_task.delay(job_id, str(output.id))

    except Exception as e:
        db.rollback()
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if job:
            job.status = DubbingJobStatus.failed
            job.error_message = str(e)[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.flush()
            # Refund all credits since no language processing started
            for _ in range(job.credits_charged):
                refund_credit(db, job.user_id, job_id=None, commit=False)
            db.commit()
        logger.exception("Dubbing job %s failed during setup", job_id)
    finally:
        db.close()


@celery_app.task(name="process_dubbing_language", bind=True, max_retries=3)
def process_dubbing_language_task(self, job_id: str, output_id: str):
    """Process dubbing for a single language: ElevenLabs dub -> Sync Labs lipsync."""
    db = DubbingWorkerSession()
    try:
        output = db.query(DubbingOutput).filter(DubbingOutput.id == output_id).first()
        if not output:
            return

        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            return

        source_path = os.path.join(settings.storage_dir, job.source_video_key)
        lang = output.language
        output_dir = os.path.join(settings.storage_dir, "dubbing", job_id, lang)
        os.makedirs(output_dir, exist_ok=True)

        # Step 2a: ElevenLabs dubbing
        output.status = DubbingOutputStatus.dubbing
        output.started_at = datetime.now(timezone.utc)
        db.commit()

        dubbing_id = create_dubbing(source_path, lang, source_url=job.source_url)
        output.elevenlabs_dubbing_id = dubbing_id
        db.commit()

        _poll_with_backoff(poll_dubbing, dubbing_id, success_status="dubbed")

        audio_path = os.path.join(output_dir, "dubbed_audio.mp3")
        download_dubbed_audio(dubbing_id, lang, audio_path)
        output.dubbed_audio_key = f"dubbing/{job_id}/{lang}/dubbed_audio.mp3"
        db.commit()

        # Step 2b: Local MuseTalk lip-sync
        output.status = DubbingOutputStatus.lip_syncing
        db.commit()

        video_path = os.path.join(output_dir, "output.mp4")
        run_lipsync(source_path, audio_path, video_path)
        output.output_video_key = f"dubbing/{job_id}/{lang}/output.mp4"
        output.status = DubbingOutputStatus.completed
        output.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("Dubbing output %s (%s) completed", output_id, lang)

    except Exception as e:
        db.rollback()
        output = db.query(DubbingOutput).filter(DubbingOutput.id == output_id).first()
        if not output:
            raise

        if self.request.retries < self.max_retries:
            output.status = DubbingOutputStatus.pending
            output.error_message = f"Retry {self.request.retries + 1}: {str(e)[:500]}"
            db.commit()
            raise self.retry(exc=e)
        else:
            output.status = DubbingOutputStatus.failed
            output.error_message = str(e)[:1000]
            output.completed_at = datetime.now(timezone.utc)
            db.flush()
            # Refund 1 credit for this failed output (atomic with status update)
            job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
            if job:
                refund_credit(db, job.user_id, job_id=None, commit=False)
            db.commit()
            logger.exception("Dubbing output %s (%s) failed permanently", output_id, output.language)
    finally:
        # Check if parent should be finalized
        try:
            _check_parent_completion(db, job_id)
        except Exception:
            logger.exception("Error checking parent completion for job %s", job_id)
        db.close()


def _process_dubbing_inline(job_id: str) -> None:
    """Process dubbing synchronously (dev mode, no Celery). No retries."""
    db = DubbingWorkerSession()
    try:
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            return

        job.status = DubbingJobStatus.downloading
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Step 1: Download
        download_dir = os.path.join(settings.storage_dir, "dubbing", job_id)
        os.makedirs(download_dir, exist_ok=True)
        meta = download_video(job.source_url, download_dir)
        job.source_video_key = f"dubbing/{job_id}/{os.path.basename(meta['filepath'])}"
        db.commit()

        if meta["duration"] > MAX_DUBBING_DURATION:
            raise ValueError(
                f"Video too long ({meta['duration']:.0f}s, max {MAX_DUBBING_DURATION}s / 30 minutes)"
            )

        source_path = os.path.join(settings.storage_dir, job.source_video_key)
        job.status = DubbingJobStatus.processing
        db.commit()

        outputs = db.query(DubbingOutput).filter(
            DubbingOutput.dubbing_job_id == job_id
        ).all()

        # Process each language sequentially in dev mode
        for output in outputs:
            try:
                lang = output.language
                output_dir = os.path.join(settings.storage_dir, "dubbing", job_id, lang)
                os.makedirs(output_dir, exist_ok=True)

                output.status = DubbingOutputStatus.dubbing
                output.started_at = datetime.now(timezone.utc)
                db.commit()

                dubbing_id = create_dubbing(source_path, lang, source_url=job.source_url)
                output.elevenlabs_dubbing_id = dubbing_id
                db.commit()

                _poll_with_backoff(poll_dubbing, dubbing_id, success_status="dubbed")

                audio_path = os.path.join(output_dir, "dubbed_audio.mp3")
                download_dubbed_audio(dubbing_id, lang, audio_path)
                output.dubbed_audio_key = f"dubbing/{job_id}/{lang}/dubbed_audio.mp3"
                db.commit()

                output.status = DubbingOutputStatus.lip_syncing
                db.commit()

                video_path = os.path.join(output_dir, "output.mp4")
                run_lipsync(source_path, audio_path, video_path)
                output.output_video_key = f"dubbing/{job_id}/{lang}/output.mp4"
                output.status = DubbingOutputStatus.completed
                output.completed_at = datetime.now(timezone.utc)
                db.commit()
                logger.info("Dubbing output %s (%s) completed inline", output.id, lang)

            except Exception as e:
                db.rollback()
                output = db.query(DubbingOutput).filter(DubbingOutput.id == output.id).first()
                if output:
                    output.status = DubbingOutputStatus.failed
                    output.error_message = str(e)[:1000]
                    output.completed_at = datetime.now(timezone.utc)
                    db.flush()
                    refund_credit(db, job.user_id, job_id=None, commit=False)
                    db.commit()
                logger.exception("Inline dubbing failed for output %s", output.id if output else "unknown")

        _check_parent_completion(db, job_id)

    except Exception as e:
        db.rollback()
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if job:
            job.status = DubbingJobStatus.failed
            job.error_message = str(e)[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.flush()
            for _ in range(job.credits_charged):
                refund_credit(db, job.user_id, job_id=None, commit=False)
            db.commit()
        logger.exception("Inline dubbing job %s failed", job_id)
    finally:
        db.close()
