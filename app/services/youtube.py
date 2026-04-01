import logging
import os
import re
import subprocess
import tempfile

import httpx
import yt_dlp

log = logging.getLogger(__name__)

MAX_DURATION_SECONDS = 3600  # 60 minutes

COBALT_API_URL = os.environ.get("COBALT_API_URL", "https://api.cobalt.tools")


def validate_youtube_url(url: str) -> bool:
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
    )
    return bool(pattern.match(url))


def _is_instagram_url(url: str) -> bool:
    return bool(re.match(r"^(https?://)?(www\.)?instagram\.com/", url))


def _find_output(output_dir: str) -> str | None:
    for f in os.listdir(output_dir):
        if f.startswith("source."):
            return os.path.join(output_dir, f)
    return None


def _clean_partials(output_dir: str):
    for f in os.listdir(output_dir):
        if f.startswith("source."):
            os.remove(os.path.join(output_dir, f))


def _probe_duration(filepath: str) -> float:
    """Get duration via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", filepath],
            capture_output=True, text=True, timeout=15,
        )
        import json
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0


# --- Method 1: yt-dlp ---

def _try_ytdlp(url: str, output_dir: str) -> dict:
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "source.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    cookies_file = os.environ.get("YTDLP_COOKIES_FILE")
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts["cookiefile"] = cookies_file
    else:
        chrome_paths = [
            os.path.expanduser("~/.config/google-chrome"),
            os.path.expanduser("~/Library/Application Support/Google/Chrome"),
        ]
        if any(os.path.exists(p) for p in chrome_paths):
            ydl_opts["cookiesfrombrowser"] = ("chrome",)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0)
        if duration > MAX_DURATION_SECONDS:
            raise ValueError(
                f"Video too long ({duration:.0f}s, max {MAX_DURATION_SECONDS}s / 60 minutes)"
            )
        info = ydl.extract_info(url, download=True)

        filepath = None
        if "requested_downloads" in info and info["requested_downloads"]:
            filepath = info["requested_downloads"][0].get("filepath")
        if not filepath:
            filepath = _find_output(output_dir)
        if not filepath or not os.path.exists(filepath):
            raise RuntimeError("yt-dlp: output file not found")

        return {
            "title": info.get("title", "Unknown"),
            "duration": float(info.get("duration", 0)),
            "filepath": filepath,
            "width": int(info.get("width", 0)),
            "height": int(info.get("height", 0)),
        }


# --- Method 2: Cobalt API ---

def _try_cobalt(url: str, output_dir: str) -> dict:
    resp = httpx.post(
        f"{COBALT_API_URL}/api/json",
        json={"url": url, "vQuality": "1080", "filenamePattern": "basic"},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    download_url = data.get("url")
    if not download_url:
        raise RuntimeError(f"Cobalt returned no URL: {data}")

    filepath = os.path.join(output_dir, "source.mp4")
    with httpx.stream("GET", download_url, timeout=120, follow_redirects=True) as stream:
        stream.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in stream.iter_bytes(chunk_size=65536):
                f.write(chunk)

    if not os.path.exists(filepath) or os.path.getsize(filepath) < 1024:
        raise RuntimeError("Cobalt: downloaded file too small or missing")

    duration = _probe_duration(filepath)
    if duration > MAX_DURATION_SECONDS:
        os.remove(filepath)
        raise ValueError(
            f"Video too long ({duration:.0f}s, max {MAX_DURATION_SECONDS}s / 60 minutes)"
        )

    return {
        "title": "Unknown",
        "duration": duration,
        "filepath": filepath,
        "width": 0,
        "height": 0,
    }


# --- Method 3: yt-dlp with no auth (plain) ---

def _try_ytdlp_plain(url: str, output_dir: str) -> dict:
    ydl_opts = {
        "format": "best[height<=1080][ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "source.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0)
        if duration > MAX_DURATION_SECONDS:
            raise ValueError(
                f"Video too long ({duration:.0f}s, max {MAX_DURATION_SECONDS}s / 60 minutes)"
            )
        info = ydl.extract_info(url, download=True)

        filepath = None
        if "requested_downloads" in info and info["requested_downloads"]:
            filepath = info["requested_downloads"][0].get("filepath")
        if not filepath:
            filepath = _find_output(output_dir)
        if not filepath or not os.path.exists(filepath):
            raise RuntimeError("yt-dlp plain: output file not found")

        return {
            "title": info.get("title", "Unknown"),
            "duration": float(info.get("duration", 0)),
            "filepath": filepath,
            "width": int(info.get("width", 0)),
            "height": int(info.get("height", 0)),
        }


# --- Main entry point ---

METHODS = [
    ("yt-dlp", _try_ytdlp),
    ("cobalt", _try_cobalt),
    ("yt-dlp-plain", _try_ytdlp_plain),
]


def download_video(url: str, output_dir: str) -> dict:
    errors = []

    for name, method in METHODS:
        _clean_partials(output_dir)
        try:
            log.info(f"Trying download method: {name}")
            result = method(url, output_dir)
            log.info(f"Download succeeded with: {name}")
            return result
        except ValueError:
            raise  # duration limit — don't retry
        except Exception as e:
            log.warning(f"{name} failed: {e}")
            errors.append(f"{name}: {e}")
            continue

    raise RuntimeError(
        f"All download methods failed:\n" + "\n".join(errors)
    )
