import os
import pytest
from unittest.mock import patch, MagicMock

from app.services.youtube import download_video, validate_youtube_url, MAX_DURATION_SECONDS


class TestValidateYoutubeUrl:
    def test_valid_watch_url(self):
        assert validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_valid_short_url(self):
        assert validate_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_valid_shorts_url(self):
        assert validate_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ") is True

    def test_invalid_url(self):
        assert validate_youtube_url("https://vimeo.com/12345") is False

    def test_empty_url(self):
        assert validate_youtube_url("") is False


class TestDownloadVideo:
    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_download_success(self, mock_ydl_class, tmp_path):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Test Video",
            "duration": 300.0,
            "width": 1920,
            "height": 1080,
            "requested_downloads": [{"filepath": str(tmp_path / "video.mp4")}],
        }
        (tmp_path / "video.mp4").write_bytes(b"fake video")

        result = download_video("https://youtube.com/watch?v=abc123", str(tmp_path))
        assert result["title"] == "Test Video"
        assert result["duration"] == 300.0
        assert result["width"] == 1920
        assert result["height"] == 1080

    @patch("app.services.youtube.yt_dlp.YoutubeDL")
    def test_download_too_long(self, mock_ydl_class, tmp_path):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "title": "Long Video",
            "duration": MAX_DURATION_SECONDS + 1,
            "width": 1920,
            "height": 1080,
        }

        with pytest.raises(ValueError, match="Video too long"):
            download_video("https://youtube.com/watch?v=abc123", str(tmp_path))
