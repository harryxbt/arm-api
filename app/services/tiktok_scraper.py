# app/services/tiktok_scraper.py
import logging
from datetime import datetime, timezone

import yt_dlp

logger = logging.getLogger(__name__)


class TikTokScraper:
    def _build_url(self, handle: str) -> str:
        clean = handle.lstrip("@")
        return f"https://www.tiktok.com/@{clean}"

    def _parse_upload_date(self, date_str: str | None) -> str | None:
        if not date_str or len(date_str) != 8:
            return None
        try:
            dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return None

    def scrape(self, handle: str) -> dict:
        url = self._build_url(handle)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "dump_single_json": True,
            "playlistend": 30,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries") or []
        recent_videos = []
        for entry in entries:
            recent_videos.append({
                "url": entry.get("url") or entry.get("webpage_url", ""),
                "views": entry.get("view_count", 0) or 0,
                "likes": entry.get("like_count", 0) or 0,
                "comments": entry.get("comment_count", 0) or 0,
                "shares": entry.get("repost_count", 0) or 0,
                "caption": entry.get("title") or entry.get("description", ""),
                "posted_at": self._parse_upload_date(entry.get("upload_date")),
            })

        avatar_url = None
        thumbnails = info.get("thumbnails") or []
        if thumbnails:
            avatar_url = thumbnails[-1].get("url")

        return {
            "followers": info.get("channel_follower_count", 0) or 0,
            "following": info.get("channel_following_count", 0) or 0,
            "total_likes": info.get("like_count", 0) or 0,
            "total_videos": len(entries),
            "bio": info.get("description") or None,
            "avatar_url": avatar_url,
            "recent_videos": recent_videos,
            "scraped_at": datetime.now(timezone.utc),
        }
