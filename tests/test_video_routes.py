# tests/test_video_routes.py
import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import User
from app.services.auth import create_access_token
from app.database import get_db


def test_upload_video(client, db):
    user = User(email="test@example.com", password_hash="hashed", credits_remaining=10)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(subject=str(user.id))
    client.headers["Authorization"] = f"Bearer {token}"
    file = io.BytesIO(b"fake video data")
    resp = client.post("/videos/upload", files={"file": ("test.mp4", file, "video/mp4")})
    assert resp.status_code == 200
    assert "key" in resp.json()
    assert resp.json()["key"].startswith("uploads/")


def test_upload_invalid_type(client, db):
    user = User(email="test2@example.com", password_hash="hashed", credits_remaining=10)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(subject=str(user.id))
    client.headers["Authorization"] = f"Bearer {token}"
    file = io.BytesIO(b"not a video")
    resp = client.post("/videos/upload", files={"file": ("test.txt", file, "text/plain")})
    assert resp.status_code == 400
