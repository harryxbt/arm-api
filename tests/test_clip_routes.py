# tests/test_clip_routes.py
from unittest.mock import patch
from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction, ExtractionStatus
from app.models.user import User
from app.services.auth import create_access_token

def _create_user(db, credits=10):
    user = User(email="test@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}

class TestExtractClips:
    @patch("app.routes.clips._dispatch_extraction")
    def test_create_extraction(self, mock_dispatch, client, db):
        user = _create_user(db)
        resp = client.post("/clips/extract", json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, headers=_auth_header(user.id))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert "youtube.com" in data["youtube_url"]
        mock_dispatch.assert_called_once()

    def test_invalid_url(self, client, db):
        user = _create_user(db)
        resp = client.post("/clips/extract", json={"youtube_url": "https://vimeo.com/12345"}, headers=_auth_header(user.id))
        assert resp.status_code == 422

    @patch("app.routes.clips._dispatch_extraction")
    def test_insufficient_credits(self, mock_dispatch, client, db):
        user = _create_user(db, credits=0)
        resp = client.post("/clips/extract", json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, headers=_auth_header(user.id))
        assert resp.status_code == 402
        mock_dispatch.assert_not_called()

class TestGetExtraction:
    def test_get_extraction_with_clips(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(user_id=user.id, youtube_url="https://youtube.com/watch?v=abc", status=ExtractionStatus.completed)
        db.add(extraction)
        db.flush()
        clip = Clip(extraction_id=extraction.id, storage_key="clips/test/clip1.mp4", start_time=10.0, end_time=55.0,
                    duration=45.0, virality_score=85, hook_text="Amazing hook", transcript_text="Full transcript here", reframed=True)
        db.add(clip)
        db.commit()
        db.refresh(extraction)
        resp = client.get(f"/clips/{extraction.id}", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert len(data["clips"]) == 1
        assert data["clips"][0]["virality_score"] == 85

    def test_get_nonexistent(self, client, db):
        user = _create_user(db)
        resp = client.get("/clips/nonexistent-id", headers=_auth_header(user.id))
        assert resp.status_code == 404

    def test_cannot_see_other_users_extraction(self, client, db):
        user1 = _create_user(db)
        user2 = User(email="other@example.com", password_hash="hashed", credits_remaining=10)
        db.add(user2)
        db.commit()
        db.refresh(user2)
        extraction = ClipExtraction(user_id=user2.id, youtube_url="https://youtube.com/watch?v=abc")
        db.add(extraction)
        db.commit()
        db.refresh(extraction)
        resp = client.get(f"/clips/{extraction.id}", headers=_auth_header(user1.id))
        assert resp.status_code == 404

class TestListExtractions:
    def test_list_empty(self, client, db):
        user = _create_user(db)
        resp = client.get("/clips", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["extractions"] == []

    def test_list_with_items(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(user_id=user.id, youtube_url="https://youtube.com/watch?v=abc")
        db.add(extraction)
        db.commit()
        resp = client.get("/clips", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert len(resp.json()["extractions"]) == 1
