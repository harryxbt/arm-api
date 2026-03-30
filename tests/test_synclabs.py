# tests/test_synclabs.py
from unittest.mock import patch, MagicMock, mock_open
import httpx
import pytest

from app.services.synclabs import create_lipsync, poll_lipsync, get_lipsync_url, download_lipsync


class TestCreateLipsync:
    @patch("app.services.synclabs.httpx.post")
    @patch("builtins.open", mock_open(read_data=b"fake-data"))
    def test_create_returns_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "sync_456"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = create_lipsync("/tmp/video.mp4", "/tmp/audio.mp3")
        assert result == "sync_456"

    @patch("app.services.synclabs.httpx.post")
    @patch("builtins.open", mock_open(read_data=b"fake-data"))
    def test_create_raises_on_error(self, mock_post):
        mock_post.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        with pytest.raises(httpx.HTTPStatusError):
            create_lipsync("/tmp/video.mp4", "/tmp/audio.mp3")


class TestPollLipsync:
    @patch("app.services.synclabs.httpx.get")
    def test_poll_returns_status(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "completed", "url": "https://sync.so/output.mp4"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = poll_lipsync("sync_456")
        assert result == "completed"


class TestGetLipsyncUrl:
    @patch("app.services.synclabs.httpx.get")
    def test_returns_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "completed", "url": "https://sync.so/output.mp4"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        url = get_lipsync_url("sync_456")
        assert url == "https://sync.so/output.mp4"


class TestDownloadLipsync:
    @patch("app.services.synclabs.httpx.get")
    def test_download_saves_file(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.content = b"fake-video-data"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        output_path = str(tmp_path / "output.mp4")
        download_lipsync("https://sync.so/output.mp4", output_path)
        with open(output_path, "rb") as f:
            assert f.read() == b"fake-video-data"
