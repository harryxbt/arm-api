import os
import re

import yt_dlp

MAX_DURATION_SECONDS = 3600  # 60 minutes


def validate_youtube_url(url: str) -> bool:
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w-]+"
    )
    return bool(pattern.match(url))


def _is_instagram_url(url: str) -> bool:
    return bool(re.match(r"^(https?://)?(www\.)?instagram\.com/", url))


def download_video(url: str, output_dir: str) -> dict:
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "source.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    # Instagram requires authentication — use browser cookies
    if _is_instagram_url(url):
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
            for f in os.listdir(output_dir):
                if f.startswith("source."):
                    filepath = os.path.join(output_dir, f)
                    break

        if not filepath or not os.path.exists(filepath):
            raise RuntimeError("Download completed but output file not found")

        return {
            "title": info.get("title", "Unknown"),
            "duration": float(info.get("duration", 0)),
            "filepath": filepath,
            "width": int(info.get("width", 0)),
            "height": int(info.get("height", 0)),
        }
