from unittest.mock import patch, MagicMock

from app.services.face_reframer import (
    get_video_dimensions,
    is_landscape,
    smooth_positions,
)


class TestGetVideoDimensions:
    @patch("app.services.face_reframer.subprocess.run")
    def test_returns_dimensions(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"streams":[{"width":1920,"height":1080}]}',
            returncode=0,
        )
        w, h = get_video_dimensions("/fake/path.mp4")
        assert w == 1920
        assert h == 1080


class TestIsLandscape:
    def test_landscape(self):
        assert is_landscape(1920, 1080) is True

    def test_portrait(self):
        assert is_landscape(1080, 1920) is False

    def test_square(self):
        assert is_landscape(1080, 1080) is False


class TestSmoothPositions:
    def test_smooths_positions(self):
        positions = [100, 200, 100, 200, 100]
        smoothed = smooth_positions(positions, window=3)
        assert max(smoothed) - min(smoothed) < max(positions) - min(positions)

    def test_empty_list(self):
        assert smooth_positions([], window=3) == []

    def test_single_element(self):
        assert smooth_positions([100], window=3) == [100]
