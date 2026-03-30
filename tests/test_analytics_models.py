# tests/test_analytics_models.py
from datetime import datetime, timezone
from app.models.profile_snapshot import ProfileSnapshot
from app.models.cluster import Cluster, ClusterAccount, Platform


class TestProfileSnapshot:
    def test_create_snapshot(self, db):
        cluster = Cluster(name="Test Client")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@joefazer",
        )
        db.add(account)
        db.flush()

        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=125000,
            following=340,
            total_likes=8500000,
            total_videos=210,
            bio="Fitness content creator",
            avatar_url="https://p16.tiktok.com/avatar.jpg",
            recent_videos=[
                {
                    "url": "https://www.tiktok.com/@joefazer/video/123",
                    "views": 150000,
                    "likes": 12000,
                    "comments": 340,
                    "shares": 890,
                    "caption": "Morning routine",
                    "posted_at": "2026-03-20T14:30:00Z",
                }
            ],
            scraped_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.id is not None
        assert snapshot.followers == 125000
        assert snapshot.total_likes == 8500000
        assert snapshot.recent_videos[0]["views"] == 150000
        assert snapshot.scraped_at.year == 2026

    def test_cascade_delete(self, db):
        cluster = Cluster(name="Test Client")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@test",
        )
        db.add(account)
        db.flush()
        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=100,
            following=50,
            total_likes=1000,
            total_videos=10,
            scraped_at=datetime.now(timezone.utc),
        )
        db.add(snapshot)
        db.commit()

        db.delete(account)
        db.commit()
        remaining = db.query(ProfileSnapshot).filter(
            ProfileSnapshot.account_id == account.id
        ).all()
        assert len(remaining) == 0

    def test_nullable_fields(self, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id,
            platform=Platform.tiktok,
            handle="@min",
        )
        db.add(account)
        db.flush()
        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=0,
            following=0,
            total_likes=0,
            total_videos=0,
            scraped_at=datetime.now(timezone.utc),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        assert snapshot.bio is None
        assert snapshot.avatar_url is None
        assert snapshot.recent_videos is None
