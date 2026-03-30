# tests/test_publishing_models.py
from datetime import datetime, timezone
from app.models.cluster import (
    ClusterAccount, AccountPost, PostStatus, Platform, Cluster,
)


class TestPostStatusEnum:
    def test_values(self):
        assert PostStatus.pending.value == "pending"
        assert PostStatus.uploading.value == "uploading"
        assert PostStatus.posted.value == "posted"
        assert PostStatus.failed.value == "failed"


class TestClusterAccountCredentials:
    def test_credentials_column_exists(self, db):
        cluster = Cluster(name="Test Cluster")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@test",
            credentials={"access_token": "tok123", "open_id": "oid456"},
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        assert account.credentials["access_token"] == "tok123"
        assert account.credentials["open_id"] == "oid456"

    def test_credentials_nullable(self, db):
        cluster = Cluster(name="Test Cluster")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.youtube,
            handle="@nocreds",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        assert account.credentials is None


class TestAccountPostSchedulingColumns:
    def test_scheduled_post_columns(self, db):
        cluster = Cluster(name="Test Cluster")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@test",
        )
        db.add(account)
        db.flush()
        post = AccountPost(
            account_id=account.id,
            video_storage_key="clips/abc/clip1.mp4",
            scheduled_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
            status=PostStatus.pending,
            post_metadata={"caption": "Test post", "hashtags": ["#viral"]},
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        assert post.status == PostStatus.pending
        assert post.video_storage_key == "clips/abc/clip1.mp4"
        assert post.scheduled_at.year == 2026
        assert post.post_metadata["caption"] == "Test post"
        assert post.error_message is None
        assert post.platform_url is None
        assert post.job_id is None
