"""RunPod serverless handler for Armageddon video processing."""

import os
import tempfile
import time
import logging

import runpod
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BUNNY_API_KEY = os.environ.get("BUNNY_API_KEY", "")
BUNNY_STORAGE_ZONE = os.environ.get("BUNNY_STORAGE_ZONE", "")
BUNNY_STORAGE_HOST = os.environ.get("BUNNY_STORAGE_HOST", "storage.bunnycdn.com")
BUNNY_CDN_HOST = os.environ.get("BUNNY_CDN_HOST", "")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
BUNNY_BASE = f"https://{BUNNY_STORAGE_HOST}/{BUNNY_STORAGE_ZONE}"


def bunny_download(key: str, local_path: str):
    """Download a file from Bunny storage."""
    url = f"{BUNNY_BASE}/{key}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with httpx.stream("GET", url, headers={"AccessKey": BUNNY_API_KEY}, timeout=300.0) as resp:
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=8192):
                f.write(chunk)
    logger.info("Downloaded %s (%.1f MB)", key, os.path.getsize(local_path) / (1024 * 1024))


def bunny_upload(key: str, local_path: str, retries: int = 3):
    """Upload a file to Bunny storage with retries."""
    url = f"{BUNNY_BASE}/{key}"
    with open(local_path, "rb") as f:
        data = f.read()
    for attempt in range(1, retries + 1):
        resp = httpx.put(url, content=data, headers={"AccessKey": BUNNY_API_KEY}, timeout=300.0)
        if resp.status_code in (200, 201):
            logger.info("Uploaded %s (%.1f MB)", key, len(data) / (1024 * 1024))
            return key
        if attempt < retries:
            logger.warning("Upload attempt %d/%d failed (%s), retrying...", attempt, retries, resp.status_code)
            time.sleep(2 * attempt)
        else:
            resp.raise_for_status()
    return key


def transcribe(audio_path: str) -> list[dict]:
    """Transcribe audio via Deepgram."""
    if not DEEPGRAM_API_KEY:
        return []
    import subprocess
    tmp_audio = audio_path + ".wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", tmp_audio],
        capture_output=True, timeout=120,
    )
    if not os.path.exists(tmp_audio):
        return []
    with open(tmp_audio, "rb") as f:
        audio_data = f.read()
    os.remove(tmp_audio)
    resp = httpx.post(
        "https://api.deepgram.com/v1/listen",
        params={"model": "nova-3", "smart_format": "true", "punctuate": "true"},
        headers={"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": "audio/wav"},
        content=audio_data,
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    words = []
    for w in data.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("words", []):
        words.append({"word": w["word"], "start": w["start"], "end": w["end"]})
    logger.info("Transcribed %d words", len(words))
    return words


def handler(job):
    job_input = job["input"]
    job_id = job_input["job_id"]
    source_key = job_input["source_video_key"]
    gameplay_key = job_input["gameplay_key"]
    caption_style = job_input.get("caption_style")

    logger.info("[%s] Starting: src=%s gameplay=%s", job_id[:8], source_key, gameplay_key)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download source and gameplay
        source_path = os.path.join(tmpdir, "source.mp4")
        gameplay_path = os.path.join(tmpdir, "gameplay.mp4")
        bunny_download(source_key, source_path)
        bunny_download(gameplay_key, gameplay_path)

        # Transcribe for captions
        logger.info("[%s] Transcribing...", job_id[:8])
        t0 = time.time()
        words = transcribe(source_path)
        logger.info("[%s] Transcription: %d words in %.1fs", job_id[:8], len(words), time.time() - t0)

        # Generate ASS subtitles
        from app.services.video_processor import generate_ass_subtitles, composite_splitscreen

        ass_path = None
        if words:
            ass_path = os.path.join(tmpdir, "captions.ass")
            generate_ass_subtitles(words, ass_path, style=caption_style)

        # Composite splitscreen
        output_path = os.path.join(tmpdir, "output.mp4")
        logger.info("[%s] Compositing...", job_id[:8])
        t0 = time.time()
        composite_splitscreen(source_path, gameplay_path, ass_path, output_path)
        logger.info("[%s] Compositing done in %.1fs", job_id[:8], time.time() - t0)

        # Upload output
        output_key = f"jobs/{job_id}/output.mp4"
        bunny_upload(output_key, output_path)

    logger.info("[%s] Complete", job_id[:8])
    return {
        "job_id": job_id,
        "output_key": output_key,
        "status": "completed",
    }


runpod.serverless.start({"handler": handler})
