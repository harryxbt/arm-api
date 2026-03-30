# tests/test_job_routes.py
import pytest
from unittest.mock import patch
from app.models import User, GameplayClip
from app.services.auth import create_access_token
from app.database import get_db


@patch("app.routes.jobs.process_video_task")
def test_create_job(mock_task, client, db):
    user = User(email="test@example.com", password_hash="hashed", credits_remaining=5)
    clip = GameplayClip(name="Subway Surfers", storage_key="gameplay/subway.mp4", duration_seconds=120.0)
    db.add_all([user, clip])
    db.commit()
    db.refresh(user)
    db.refresh(clip)
    token = create_access_token(subject=str(user.id))
    client.headers["Authorization"] = f"Bearer {token}"
    resp = client.post("/jobs", json={"source_video_key": "uploads/test.mp4", "gameplay_id": str(clip.id)})
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    mock_task.delay.assert_called_once()


@patch("app.routes.jobs.process_video_task")
def test_create_job_insufficient_credits(mock_task, client, db):
    user = User(email="broke@example.com", password_hash="hashed", credits_remaining=0)
    clip = GameplayClip(name="Game", storage_key="gameplay/game.mp4", duration_seconds=60.0)
    db.add_all([user, clip])
    db.commit()
    db.refresh(user)
    db.refresh(clip)
    token = create_access_token(subject=str(user.id))
    client.headers["Authorization"] = f"Bearer {token}"
    resp = client.post("/jobs", json={"source_video_key": "uploads/test.mp4", "gameplay_id": str(clip.id)})
    assert resp.status_code == 402
