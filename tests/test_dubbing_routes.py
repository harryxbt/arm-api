# tests/test_dubbing_routes.py
from unittest.mock import patch
from app.models.dubbing import DubbingJob, DubbingOutput, DubbingJobStatus, DubbingOutputStatus
from app.models.user import User
from app.services.auth import create_access_token


def _create_user(db, credits=10):
    user = User(email="dub@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


class TestCreateDubbing:
    @patch("app.routes.dubbing._dispatch_dubbing")
    def test_create_dubbing_job(self, mock_dispatch, client, db):
        user = _create_user(db)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "languages": ["fr", "es"],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert set(data["languages"]) == {"fr", "es"}
        assert data["credits_charged"] == 2
        assert len(data["outputs"]) == 2
        mock_dispatch.assert_called_once()

    @patch("app.routes.dubbing._dispatch_dubbing")
    def test_insufficient_credits(self, mock_dispatch, client, db):
        user = _create_user(db, credits=1)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "languages": ["fr", "es"],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 402
        mock_dispatch.assert_not_called()

    def test_invalid_language(self, client, db):
        user = _create_user(db)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "languages": ["de"],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 422

    def test_empty_languages(self, client, db):
        user = _create_user(db)
        resp = client.post("/dubbing", json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "languages": [],
        }, headers=_auth_header(user.id))
        assert resp.status_code == 422


class TestGetDubbing:
    def test_get_job_with_outputs(self, client, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            source_url="https://youtube.com/watch?v=abc",
            languages=["fr"],
            credits_charged=1,
            status=DubbingJobStatus.completed,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        output = DubbingOutput(
            dubbing_job_id=job.id,
            language="fr",
            status=DubbingOutputStatus.completed,
            output_video_key="dubbing/test/fr/output.mp4",
        )
        db.add(output)
        db.commit()

        resp = client.get(f"/dubbing/{job.id}", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert len(data["outputs"]) == 1
        assert data["outputs"][0]["language"] == "fr"

    def test_get_nonexistent(self, client, db):
        user = _create_user(db)
        resp = client.get("/dubbing/nonexistent-id", headers=_auth_header(user.id))
        assert resp.status_code == 404

    def test_cannot_see_other_users_job(self, client, db):
        user1 = _create_user(db)
        user2 = User(email="other@example.com", password_hash="hashed", credits_remaining=10)
        db.add(user2)
        db.commit()
        db.refresh(user2)
        job = DubbingJob(
            user_id=user2.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr"],
            credits_charged=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        resp = client.get(f"/dubbing/{job.id}", headers=_auth_header(user1.id))
        assert resp.status_code == 404


class TestListDubbing:
    def test_list_empty(self, client, db):
        user = _create_user(db)
        resp = client.get("/dubbing", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    def test_list_with_items(self, client, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr", "es"],
            credits_charged=2,
        )
        db.add(job)
        db.commit()
        resp = client.get("/dubbing", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 1
