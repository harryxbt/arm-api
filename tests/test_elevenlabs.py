# tests/test_elevenlabs.py
import json
from unittest.mock import patch, MagicMock
import httpx
import pytest

from app.services.elevenlabs import create_dubbing, poll_dubbing, download_dubbed_audio


class TestCreateDubbing:
    @patch("app.services.elevenlabs.httpx.post")
    @patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))))
    def test_create_dubbing_returns_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"dubbing_id": "dub_123"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = create_dubbing("/tmp/video.mp4", "fr")
        assert result == "dub_123"
        mock_post.assert_called_once()

    @patch("app.services.elevenlabs.httpx.post")
    @patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))))
    def test_create_dubbing_raises_on_error(self, mock_post):
        mock_post.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=MagicMock(status_code=400)
        )
        with pytest.raises(httpx.HTTPStatusError):
            create_dubbing("/tmp/video.mp4", "fr")


class TestPollDubbing:
    @patch("app.services.elevenlabs.httpx.get")
    def test_poll_returns_status(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "dubbed"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = poll_dubbing("dub_123")
        assert result == "dubbed"


class TestDownloadDubbedAudio:
    @patch("app.services.elevenlabs.subprocess.run")
    @patch("app.services.elevenlabs.httpx.get")
    def test_download_and_extract_audio(self, mock_get, mock_ffmpeg):
        mock_resp = MagicMock()
        mock_resp.content = b"fake-video-data"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        mock_ffmpeg.return_value = MagicMock(returncode=0)

        download_dubbed_audio("dub_123", "fr", "/tmp/output.mp3")
        mock_get.assert_called_once()
        mock_ffmpeg.assert_called_once()
