import os
import tempfile
import uuid
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.job import Job, JobStatus
from app.services.credits import refund_credit
from app.services.transcription import transcribe_audio
from app.services.video_processor import generate_ass_subtitles, composite_splitscreen
from app.storage import storage

celery_app = Celery("armageddon", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=30,
    task_max_retries=3,
    beat_schedule={
        "poll-account-analytics": {
            "task": "poll_account_analytics",
            "schedule": 21600.0,
        },
    },
)

engine = create_engine(settings.database_url)
WorkerSession = sessionmaker(bind=engine)


@celery_app.task(name="process_video", bind=True, max_retries=3)
def process_video_task(self, job_id: str):
    db = WorkerSession()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        job.status = JobStatus.processing
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: Download files
            source_path = storage.get_file(job.source_video_key)
            gameplay_path = storage.get_file(job.gameplay_key)

            # Step 2: Transcribe
            try:
                words = transcribe_audio(source_path)
            except Exception:
                words = []  # proceed without captions if transcription fails

            # Extract caption style from job config, store words
            caption_style = None
            if job.caption_data and isinstance(job.caption_data, dict):
                caption_style = job.caption_data.get("style")
            job.caption_data = {"words": words, "style": caption_style}

            # Step 3: Generate captions
            ass_path = None
            if words:
                ass_path = os.path.join(tmpdir, "captions.ass")
                generate_ass_subtitles(words, ass_path, style=caption_style)

            # Step 4: FFmpeg composite
            output_filename = "output.mp4"
            output_path = os.path.join(tmpdir, output_filename)
            composite_splitscreen(source_path, gameplay_path, ass_path, output_path)

            # Step 5: Upload output
            with open(output_path, "rb") as f:
                output_data = f.read()
            output_key = storage.save_file(f"jobs/{job_id}", output_filename, output_data)

            job.output_video_key = output_key
            job.status = JobStatus.completed
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    except Exception as e:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise

        if self.request.retries < self.max_retries:
            # Retry: reset status to pending, don't refund yet
            job.status = JobStatus.pending
            job.error_message = f"Retry {self.request.retries + 1}: {str(e)[:500]}"
            db.commit()
            raise self.retry(exc=e)
        else:
            # Final failure: mark failed and refund
            job.status = JobStatus.failed
            job.error_message = str(e)[:1000]
            job.completed_at = datetime.now(timezone.utc)
            db.flush()
            refund_credit(db, job.user_id, job.id, commit=False)
            db.commit()
    finally:
        db.close()

import app.analytics_worker  # noqa: F401, E402 — register analytics tasks with Beat
import app.dubbing_worker  # noqa: F401, E402 — register dubbing tasks
