import logging
import os
import subprocess
import tempfile

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _extract_audio(video_path: str) -> str:
    """Extract audio from video as mp3 to reduce file size."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    logger.info("Extracting audio from %s", os.path.basename(video_path))
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "64k", tmp.name],
        capture_output=True, timeout=120,
    )
    if result.returncode != 0:
        logger.error("FFmpeg audio extraction failed: %s", result.stderr.decode()[-500:])
    audio_size_mb = os.path.getsize(tmp.name) / (1024 * 1024)
    logger.info("Audio extracted: %.1f MB", audio_size_mb)
    return tmp.name


def _deepgram_transcribe(audio_path: str) -> dict:
    """Send audio to Deepgram and return the raw response."""
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    params = {
        "model": "nova-3",
        "smart_format": "true",
        "utterances": "true",
        "punctuate": "true",
        "paragraphs": "true",
    }

    size_mb = len(audio_data) / (1024 * 1024)
    logger.info("Sending audio to Deepgram (nova-3, %.1f MB)...", size_mb)

    last_exc = None
    for attempt in range(1, 4):
        try:
            response = httpx.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers={
                    "Authorization": f"Token {settings.deepgram_api_key}",
                    "Content-Type": "audio/mpeg",
                },
                content=audio_data,
                timeout=httpx.Timeout(600.0, connect=30.0),
            )
            response.raise_for_status()
            logger.info("Deepgram response received")
            return response.json()
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            last_exc = e
            logger.warning("Deepgram attempt %d/3 failed: %s", attempt, e)
    raise last_exc


def _parse_words(data: dict) -> list[dict]:
    words = []
    for channel in data.get("results", {}).get("channels", []):
        for alt in channel.get("alternatives", []):
            for w in alt.get("words", []):
                words.append({
                    "word": w["punctuated_word"],
                    "start": w["start"],
                    "end": w["end"],
                })
            break
        break
    return words


def _parse_segments(data: dict) -> list[dict]:
    segments = []
    for channel in data.get("results", {}).get("channels", []):
        for alt in channel.get("alternatives", []):
            for paragraph in alt.get("paragraphs", {}).get("paragraphs", []):
                for sentence in paragraph.get("sentences", []):
                    text = sentence.get("text", "").strip()
                    if text:
                        segments.append({
                            "text": text,
                            "start": sentence["start"],
                            "end": sentence["end"],
                        })
            break
        break
    return segments


def transcribe_full(audio_path: str) -> tuple[list[dict], list[dict]]:
    """Single Deepgram call returning both words and segments.
    Returns (words, segments) where:
        words: list of {"word": str, "start": float, "end": float}
        segments: list of {"text": str, "start": float, "end": float}
    """
    audio_file = _extract_audio(audio_path)
    try:
        data = _deepgram_transcribe(audio_file)
    finally:
        os.unlink(audio_file)

    words = _parse_words(data)
    segments = _parse_segments(data)
    logger.info("Parsed %d words, %d segments from Deepgram", len(words), len(segments))
    return words, segments


def transcribe_audio(audio_path: str) -> list[dict]:
    """Return word-level timestamps. Convenience wrapper."""
    words, _ = transcribe_full(audio_path)
    return words


def transcribe_segments(audio_path: str) -> list[dict]:
    """Return sentence-level segments. Convenience wrapper."""
    _, segments = transcribe_full(audio_path)
    return segments
