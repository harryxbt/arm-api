# tests/test_tiktok_scraper.py
import pytest
from unittest.mock import patch, MagicMock
from app.services.tiktok_scraper import TikTokScraper


class TestTikTokScraper:
    def test_build_url(self):
        scraper = TikTokScraper()
        assert scraper._build_url("@joefazer") == "https://www.tiktok.com/@joefazer"
        assert scraper._build_url("joefazer") == "https://www.tiktok.com/@joefazer"

    @patch("app.services.tiktok_scraper.yt_dlp.YoutubeDL")
    def test_scrape_success(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {
            "channel_follower_count": 125000,
            "channel_following_count": 340,
            "like_count": 8500000,
            "description": "Fitness content creator",
            "thumbnails": [{"url": "https://p16.tiktok.com/avatar.jpg"}],
            "entries": [
                {
                    "url": "https://www.tiktok.com/@joefazer/video/123",
                    "view_count": 150000,
                    "like_count": 12000,
                    "comment_count": 340,
                    "repost_count": 890,
                    "title": "Morning routine",
                    "upload_date": "20260320",
                },
                {
                    "url": "https://www.tiktok.com/@joefazer/video/456",
                    "view_count": 80000,
                    "like_count": 6000,
                    "comment_count": 120,
                    "repost_count": 200,
                    "title": "Workout tips",
                    "upload_date": "20260319",
                },
            ],
        }

        scraper = TikTokScraper()
        result = scraper.scrape("@joefazer")

        assert result["followers"] == 125000
        assert result["following"] == 340
        assert result["total_likes"] == 8500000
        assert result["total_videos"] == 2
        assert result["bio"] == "Fitness content creator"
        assert len(result["recent_videos"]) == 2
        assert result["recent_videos"][0]["views"] == 150000
        assert result["recent_videos"][0]["caption"] == "Morning routine"

    @patch("app.services.tiktok_scraper.yt_dlp.YoutubeDL")
    def test_scrape_failure(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("Network error")

        scraper = TikTokScraper()
        with pytest.raises(Exception, match="Network error"):
            scraper.scrape("@joefazer")

    @patch("app.services.tiktok_scraper.yt_dlp.YoutubeDL")
    def test_scrape_empty_profile(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {
            "channel_follower_count": 0,
            "entries": [],
        }

        scraper = TikTokScraper()
        result = scraper.scrape("@newaccount")
        assert result["followers"] == 0
        assert result["total_videos"] == 0
        assert result["recent_videos"] == []
