# app/services/elevenlabs.py
import logging
import os
import subprocess
import tempfile

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elevenlabs.io/v1"


def _headers() -> dict:
    return {"xi-api-key": settings.elevenlabs_api_key}


def create_dubbing(video_path: str, target_lang: str, source_url: str | None = None) -> str:
    """Create an ElevenLabs dubbing job. Uses source_url if provided, otherwise uploads the file."""
    logger.info("Creating ElevenLabs dubbing for %s -> %s", source_url or os.path.basename(video_path), target_lang)
    data = {
        "target_lang": target_lang,
        "mode": "automatic",
        "watermark": "true",
    }
    if source_url:
        # Let ElevenLabs download directly — faster and avoids large upload
        data["source_url"] = source_url
        response = httpx.post(
            f"{BASE_URL}/dubbing",
            headers=_headers(),
            data=data,
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
    else:
        with open(video_path, "rb") as f:
            response = httpx.post(
                f"{BASE_URL}/dubbing",
                headers=_headers(),
                files={"file": (os.path.basename(video_path), f, "video/mp4")},
                data=data,
                timeout=httpx.Timeout(300.0, connect=30.0),
            )
    response.raise_for_status()
    dubbing_id = response.json()["dubbing_id"]
    logger.info("ElevenLabs dubbing created: %s", dubbing_id)
    return dubbing_id


def poll_dubbing(dubbing_id: str) -> str:
    """Check dubbing status. Returns status string: 'dubbing', 'dubbed', 'failed', etc."""
    response = httpx.get(
        f"{BASE_URL}/dubbing/{dubbing_id}",
        headers=_headers(),
        timeout=30.0,
    )
    response.raise_for_status()
    status = response.json()["status"]
    logger.info("ElevenLabs dubbing %s status: %s", dubbing_id, status)
    return status


def get_dubbed_audio_url(dubbing_id: str, target_lang: str) -> str:
    """Get the direct download URL for dubbed audio from ElevenLabs."""
    return f"{BASE_URL}/dubbing/{dubbing_id}/audio/{target_lang}"


def download_dubbed_audio(dubbing_id: str, target_lang: str, output_path: str) -> None:
    """Download the dubbed video from ElevenLabs, extract audio track via ffmpeg."""
    logger.info("Downloading dubbed content for %s (lang=%s)", dubbing_id, target_lang)
    response = httpx.get(
        f"{BASE_URL}/dubbing/{dubbing_id}/audio/{target_lang}",
        headers=_headers(),
        timeout=httpx.Timeout(300.0, connect=30.0),
    )
    response.raise_for_status()

    # ElevenLabs returns dubbed video — extract audio via ffmpeg
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-vn", "-ac", "1", "-ar", "44100",
             "-b:a", "192k", output_path],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr.decode()[-500:]}")
        logger.info("Dubbed audio saved to %s", output_path)
    finally:
        os.unlink(tmp_path)
