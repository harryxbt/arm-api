# app/services/synclabs.py
import logging
import os

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sync.so/v2"


def _headers() -> dict:
    return {
        "x-api-key": settings.synclabs_api_key,
        "Content-Type": "application/json",
    }


def _upload_temp_file(file_path: str) -> str:
    """Upload a file to tmpfiles.org and return a direct download URL. Files expire after 1 hour."""
    logger.info("Uploading %s to temp hosting...", os.path.basename(file_path))
    with open(file_path, "rb") as f:
        response = httpx.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": (os.path.basename(file_path), f)},
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "success":
        raise RuntimeError(f"tmpfiles.org upload failed: {data}")
    # Convert page URL to direct download URL by inserting /dl/ and ensuring https
    page_url = data["data"]["url"]
    direct_url = page_url.replace("tmpfiles.org/", "tmpfiles.org/dl/").replace("http://", "https://")
    logger.info("Uploaded to %s", direct_url)
    return direct_url


def create_lipsync(video_path: str, audio_path: str) -> str:
    """Create a Sync Labs lip-sync job. Uploads both video and audio to temp hosting."""
    video_url = _upload_temp_file(video_path)
    audio_url = _upload_temp_file(audio_path)
    logger.info("Creating Sync Labs lipsync: video=%s audio=%s", video_url[:80], audio_url[:80])

    response = httpx.post(
        f"{BASE_URL}/generate",
        headers=_headers(),
        json={
            "model": "lipsync-2",
            "input": [
                {"type": "video", "url": video_url},
                {"type": "audio", "url": audio_url},
            ],
        },
        timeout=httpx.Timeout(60.0, connect=30.0),
    )
    response.raise_for_status()
    job_id = response.json()["id"]
    logger.info("Sync Labs lipsync created: %s", job_id)
    return job_id


def poll_lipsync(job_id: str) -> str:
    """Check lipsync status. Returns status string."""
    response = httpx.get(
        f"{BASE_URL}/generate/{job_id}",
        headers=_headers(),
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    status = data["status"]
    logger.info("Sync Labs lipsync %s status: %s", job_id, status)
    return status


def get_lipsync_url(job_id: str) -> str:
    """Get the download URL for a completed lipsync job."""
    response = httpx.get(
        f"{BASE_URL}/generate/{job_id}",
        headers=_headers(),
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    # The output URL is in the outputUrl or output field
    url = data.get("outputUrl") or data.get("output")
    if not url:
        raise RuntimeError(f"No output URL found in Sync Labs response: {list(data.keys())}")
    return url


def download_lipsync(url: str, output_path: str) -> None:
    """Download the lip-synced video from the given URL."""
    logger.info("Downloading lip-synced video to %s", output_path)
    response = httpx.get(url, timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True)
    response.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(response.content)
    logger.info("Lip-synced video saved: %.1f MB", os.path.getsize(output_path) / (1024 * 1024))
