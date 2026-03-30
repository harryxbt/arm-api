# tests/test_dubbing_models.py
from app.models.dubbing import DubbingJob, DubbingOutput, DubbingJobStatus, DubbingOutputStatus
from app.models.user import User


def _create_user(db, credits=10):
    user = User(email="dub@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestDubbingModels:
    def test_create_dubbing_job(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr", "es"],
            credits_charged=2,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.id is not None
        assert job.status == DubbingJobStatus.pending
        assert job.languages == ["fr", "es"]
        assert job.credits_charged == 2

    def test_create_dubbing_output(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr"],
            credits_charged=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        output = DubbingOutput(
            dubbing_job_id=job.id,
            language="fr",
        )
        db.add(output)
        db.commit()
        db.refresh(output)
        assert output.id is not None
        assert output.status == DubbingOutputStatus.pending
        assert output.dubbing_job_id == job.id

    def test_job_outputs_relationship(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["fr", "es"],
            credits_charged=2,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        for lang in ["fr", "es"]:
            db.add(DubbingOutput(dubbing_job_id=job.id, language=lang))
        db.commit()
        db.refresh(job)
        assert len(job.outputs) == 2

    def test_user_dubbing_jobs_relationship(self, db):
        user = _create_user(db)
        job = DubbingJob(
            user_id=user.id,
            source_video_key="dubbing/test/source.mp4",
            languages=["he"],
            credits_charged=1,
        )
        db.add(job)
        db.commit()
        db.refresh(user)
        assert len(user.dubbing_jobs) == 1
