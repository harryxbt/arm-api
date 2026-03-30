# tests/test_gameplay_routes.py
import pytest
from app.main import app
from app.models import User, GameplayClip
from app.services.auth import create_access_token
from app.database import get_db


def test_list_gameplay(client, db):
    user = User(email="test@example.com", password_hash="hashed")
    db.add(user)
    clip = GameplayClip(name="Subway Surfers", storage_key="gameplay/subway.mp4", duration_seconds=120.0)
    inactive = GameplayClip(name="Old", storage_key="gameplay/old.mp4", duration_seconds=60.0, active=False)
    db.add_all([clip, inactive])
    db.commit()
    token = create_access_token(subject=str(user.id))
    client.headers["Authorization"] = f"Bearer {token}"
    resp = client.get("/gameplay")
    assert resp.status_code == 200
    clips = resp.json()
    assert len(clips) == 1
    assert clips[0]["name"] == "Subway Surfers"
