# app/clip_worker.py
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction, ExtractionStatus
from app.services.credits import refund_credit
from app.services.youtube import download_video
from app.services.transcription import transcribe_full
from app.services.clip_analyzer import analyze_segments
from app.services.face_reframer import reframe_to_vertical
from app.worker import celery_app

engine = create_engine(settings.database_url)
ClipWorkerSession = sessionmaker(bind=engine)


def _extract_clip_segment(source_path: str, start: float, end: float, output_path: str) -> None:
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-i", source_path, "-t", str(end - start),
         "-c", "copy", "-avoid_negative_ts", "make_zero", output_path],
        capture_output=True, timeout=60,
    )
    if not os.path.exists(output_path):
        raise RuntimeError(f"FFmpeg clip extraction failed: {output_path}")


def _get_transcript_for_range(words: list[dict], start: float, end: float) -> str:
    return " ".join(w["word"] for w in words if w["start"] >= start and w["end"] <= end)


@celery_app.task(name="extract_clips", bind=True, max_retries=3)
def extract_clips_task(self, extraction_id: str):
    db = ClipWorkerSession()
    try:
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if not extraction:
            return

        # Stage 1: Download
        extraction.status = ExtractionStatus.downloading
        db.commit()
        download_dir = os.path.join(settings.storage_dir, "downloads", extraction_id)
        os.makedirs(download_dir, exist_ok=True)
        meta = download_video(extraction.youtube_url, download_dir)
        extraction.video_title = meta["title"]
        extraction.video_duration = meta["duration"]
        extraction.source_video_key = f"downloads/{extraction_id}/{os.path.basename(meta['filepath'])}"
        db.commit()
        source_path = meta["filepath"]

        # Stage 2: Transcribe (segments for sentence boundaries, words for clip text)
        extraction.status = ExtractionStatus.transcribing
        db.commit()
        words, segments = transcribe_full(source_path)
        if not segments:
            raise ValueError("No speech detected in video — cannot extract clips")

        # Stage 3: Analyze
        extraction.status = ExtractionStatus.analyzing
        db.commit()
        clip_suggestions = analyze_segments(segments, video_duration=meta["duration"], words=words)
        if not clip_suggestions:
            raise ValueError("OpenAI returned no valid clips for this video")

        # Stage 4: Extract & Reframe
        extraction.status = ExtractionStatus.extracting
        db.commit()
        clips_dir = os.path.join(settings.storage_dir, "clips", extraction_id)
        os.makedirs(clips_dir, exist_ok=True)

        for suggestion in clip_suggestions:
            clip_id = str(uuid.uuid4())
            raw_path = os.path.join(clips_dir, f"{clip_id}_raw.mp4")
            final_path = os.path.join(clips_dir, f"{clip_id}.mp4")

            _extract_clip_segment(source_path, suggestion["start_time"], suggestion["end_time"], raw_path)

            try:
                reframed = reframe_to_vertical(raw_path, final_path)
            except Exception:
                os.rename(raw_path, final_path)
                reframed = False

            if os.path.exists(raw_path) and raw_path != final_path:
                os.remove(raw_path)

            clip = Clip(
                id=clip_id,
                extraction_id=extraction_id,
                storage_key=f"clips/{extraction_id}/{clip_id}.mp4",
                start_time=suggestion["start_time"],
                end_time=suggestion["end_time"],
                duration=suggestion["end_time"] - suggestion["start_time"],
                virality_score=suggestion.get("virality_score", 0),
                hook_text=suggestion.get("hook_text", ""),
                transcript_text=_get_transcript_for_range(words, suggestion["start_time"], suggestion["end_time"]),
                reframed=reframed,
            )
            db.add(clip)

        # Stage 5: Complete
        extraction.status = ExtractionStatus.completed
        extraction.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        db.rollback()
        extraction = db.query(ClipExtraction).filter(ClipExtraction.id == extraction_id).first()
        if not extraction:
            raise
        if self.request.retries < self.max_retries:
            extraction.status = ExtractionStatus.pending
            extraction.error_message = f"Retry {self.request.retries + 1}: {str(e)[:500]}"
            db.commit()
            raise self.retry(exc=e)
        else:
            extraction.status = ExtractionStatus.failed
            extraction.error_message = str(e)[:1000]
            extraction.completed_at = datetime.now(timezone.utc)
            db.flush()
            refund_credit(db, extraction.user_id, job_id=None, commit=False)
            db.commit()
    finally:
        db.close()
