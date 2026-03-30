# tests/test_storage.py
import os
import pytest
from app.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_save_and_get_file(storage, tmp_path):
    data = b"fake video content"
    key = storage.save_file("uploads", "test.mp4", data)
    assert key == "uploads/test.mp4"
    path = storage.get_file(key)
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == data


def test_get_download_url(storage, tmp_path):
    storage.save_file("outputs", "result.mp4", b"data")
    url = storage.get_download_url("outputs/result.mp4")
    assert "outputs/result.mp4" in url


def test_save_file_creates_subdirectory(storage, tmp_path):
    storage.save_file("gameplay", "clip.mp4", b"gameplay data")
    assert os.path.exists(os.path.join(str(tmp_path), "gameplay", "clip.mp4"))
