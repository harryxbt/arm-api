import os
import io
from unittest.mock import patch

from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction, ExtractionStatus, SourceType
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


class TestUpdateClipTranscript:
    def test_update_transcript(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id, youtube_url="https://youtube.com/watch?v=abc",
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.flush()
        clip = Clip(
            extraction_id=extraction.id, storage_key="clips/test/c1.mp4",
            start_time=0, end_time=30, duration=30, virality_score=80,
            hook_text="Hook", transcript_text="Original text", reframed=False,
        )
        db.add(clip)
        db.commit()
        db.refresh(clip)

        resp = client.put(
            f"/clips/{extraction.id}/{clip.id}",
            json={"transcript_text": "Updated text"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        assert resp.json()["transcript_text"] == "Updated text"

    def test_update_nonexistent_clip(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id, youtube_url="https://youtube.com/watch?v=abc",
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.commit()
        resp = client.put(
            f"/clips/{extraction.id}/nonexistent",
            json={"transcript_text": "test"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 404

    def test_update_other_users_clip(self, client, db):
        user1 = _create_user(db)
        user2 = User(email="other@example.com", password_hash="h", credits_remaining=10)
        db.add(user2)
        db.commit()
        db.refresh(user2)
        extraction = ClipExtraction(
            user_id=user2.id, youtube_url="https://youtube.com/watch?v=abc",
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.flush()
        clip = Clip(
            extraction_id=extraction.id, storage_key="clips/test/c1.mp4",
            start_time=0, end_time=30, duration=30, virality_score=80,
            hook_text="Hook", transcript_text="Original", reframed=False,
        )
        db.add(clip)
        db.commit()
        db.refresh(clip)
        resp = client.put(
            f"/clips/{extraction.id}/{clip.id}",
            json={"transcript_text": "Hacked"},
            headers=_auth_header(user1.id),
        )
        assert resp.status_code == 404


class TestUpdateLastGameplay:
    def test_update_last_gameplay(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id, youtube_url="https://youtube.com/watch?v=abc",
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.commit()
        db.refresh(extraction)
        resp = client.put(
            f"/clips/{extraction.id}/last-gameplay",
            json={"gameplay_ids": ["gp1", "gp2"]},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        assert resp.json()["last_gameplay_ids"] == ["gp1", "gp2"]

    def test_empty_gameplay_ids(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id, youtube_url="https://youtube.com/watch?v=abc",
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.commit()
        resp = client.put(
            f"/clips/{extraction.id}/last-gameplay",
            json={"gameplay_ids": []},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 422


class TestListExtractions:
    def test_includes_clip_count(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id, youtube_url="https://youtube.com/watch?v=abc",
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.flush()
        clip = Clip(
            extraction_id=extraction.id, storage_key="clips/test/c1.mp4",
            start_time=0, end_time=30, duration=30, virality_score=80,
            hook_text="Hook", transcript_text="Text", reframed=False,
        )
        db.add(clip)
        db.commit()
        resp = client.get("/clips", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()["extractions"]
        assert len(data) == 1
        assert data[0]["clip_count"] == 1
        assert data[0]["source_type"] == "youtube"

    def test_includes_source_type(self, client, db):
        user = _create_user(db)
        extraction = ClipExtraction(
            user_id=user.id, youtube_url="test.mp4",
            source_type=SourceType.upload,
            status=ExtractionStatus.completed,
        )
        db.add(extraction)
        db.commit()
        resp = client.get("/clips", headers=_auth_header(user.id))
        assert resp.json()["extractions"][0]["source_type"] == "upload"


class TestImportVideo:
    @patch("app.routes.clips._dispatch_import")
    def test_import_instagram_url(self, mock_dispatch, client, db):
        user = _create_user(db)
        resp = client.post(
            "/clips/import",
            data={"url": "https://www.instagram.com/reel/DOB5HnpD7KK/"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source_type"] == "instagram"
        assert "instagram.com" in data["youtube_url"]
        mock_dispatch.assert_called_once()

    @patch("app.routes.clips._dispatch_import")
    def test_import_file_upload(self, mock_dispatch, client, db):
        user = _create_user(db)
        file_content = b"fake video data"
        resp = client.post(
            "/clips/import",
            files={"file": ("test_video.mp4", io.BytesIO(file_content), "video/mp4")},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source_type"] == "upload"
        assert data["video_title"] == "test_video.mp4"
        mock_dispatch.assert_called_once()

    def test_import_invalid_instagram_url(self, client, db):
        user = _create_user(db)
        resp = client.post(
            "/clips/import",
            data={"url": "https://www.tiktok.com/@someone/video/123"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 422

    def test_import_invalid_file_extension(self, client, db):
        user = _create_user(db)
        resp = client.post(
            "/clips/import",
            files={"file": ("document.pdf", io.BytesIO(b"data"), "application/pdf")},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 422

    @patch("app.routes.clips._dispatch_import")
    def test_import_insufficient_credits(self, mock_dispatch, client, db):
        user = _create_user(db, credits=0)
        resp = client.post(
            "/clips/import",
            data={"url": "https://www.instagram.com/p/ABC123/"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 402
        mock_dispatch.assert_not_called()
