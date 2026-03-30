# tests/test_video_processor.py
import os
import tempfile
import pytest
from app.services.video_processor import generate_ass_subtitles, _seconds_to_ass_time


def test_seconds_to_ass_time():
    assert _seconds_to_ass_time(0.0) == "0:00:00.00"
    assert _seconds_to_ass_time(65.5) == "0:01:05.50"
    assert _seconds_to_ass_time(3661.25) == "1:01:01.25"


def test_generate_ass_subtitles():
    words = [
        {"word": "Hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.5, "end": 1.0},
        {"word": "this", "start": 1.2, "end": 1.5},
        {"word": "is", "start": 1.5, "end": 1.7},
        {"word": "a", "start": 1.8, "end": 1.9},
        {"word": "test", "start": 2.0, "end": 2.5},
    ]
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w") as f:
        output_path = f.name
    try:
        generate_ass_subtitles(words, output_path)
        with open(output_path) as f:
            content = f.read()
        assert "[Script Info]" in content
        assert "Hello world this is" in content
        assert "a test" in content
    finally:
        os.unlink(output_path)


def test_generate_ass_empty_words():
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w") as f:
        output_path = f.name
    try:
        generate_ass_subtitles([], output_path)
        with open(output_path) as f:
            content = f.read()
        assert "[Script Info]" in content
        assert "Dialogue" not in content
    finally:
        os.unlink(output_path)
