# tests/test_analytics_routes.py
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from app.schemas.analytics import (
    SnapshotResponse,
    GrowthResponse,
    ClusterOverviewResponse,
    AccountSummary,
)
from app.models.user import User
from app.models.cluster import Cluster, ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from app.services.auth import create_access_token


def _create_user(db):
    user = User(email="analytics@example.com", password_hash="hashed", credits_remaining=10)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


def _create_account_with_snapshots(db, handle="@joefazer", num_snapshots=3):
    cluster = Cluster(name="Test Client")
    db.add(cluster)
    db.flush()
    account = ClusterAccount(
        cluster_id=cluster.id,
        platform=Platform.tiktok,
        handle=handle,
    )
    db.add(account)
    db.flush()

    now = datetime.now(timezone.utc)
    snapshots = []
    for i in range(num_snapshots):
        # i=0 is oldest, i=num_snapshots-1 is most recent
        # so latest snapshot has followers = 1000 + (num_snapshots-1)*100 = 1200 for 3 snapshots
        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=1000 + (i * 100),
            following=50,
            total_likes=50000 + (i * 5000),
            total_videos=30 + i,
            bio="Test bio",
            recent_videos=[
                {"url": "https://tiktok.com/v/1", "views": 10000 + (i * 1000),
                 "likes": 500, "comments": 20, "shares": 10,
                 "caption": "Video", "posted_at": "2026-03-20T12:00:00Z"},
            ],
            scraped_at=now - timedelta(days=(num_snapshots - 1 - i) * 3),
        )
        db.add(snapshot)
        snapshots.append(snapshot)
    db.commit()
    return cluster, account, snapshots


class TestGetCurrentSnapshot:
    def test_returns_latest(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/accounts/{account.id}/current",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["followers"] == 1200

    def test_no_snapshots_404(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Empty")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@empty",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.get(
            f"/analytics/accounts/{account.id}/current",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 404


class TestGetHistory:
    def test_returns_snapshots(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/accounts/{account.id}/history",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    def test_filter_by_date_range(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        from_date = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = client.get(
            f"/analytics/accounts/{account.id}/history?from={from_date}",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


class TestGetGrowth:
    def test_growth_over_7_days(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/accounts/{account.id}/growth?days=7",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 7
        assert data["current_followers"] == 1200
        assert data["follower_change"] is not None


class TestClusterOverview:
    def test_overview(self, client, db):
        user = _create_user(db)
        cluster, account, snapshots = _create_account_with_snapshots(db)
        resp = client.get(
            f"/analytics/clusters/{cluster.id}/overview",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cluster_name"] == "Test Client"
        assert data["account_count"] == 1
        assert data["total_followers"] == 1200
        assert len(data["accounts"]) == 1


class TestManualScrape:
    @patch("app.routes.analytics._dispatch_scrape")
    def test_manual_scrape(self, mock_dispatch, client, db):
        user = _create_user(db)
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@test",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.post(
            f"/analytics/accounts/{account.id}/scrape",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 202
        mock_dispatch.assert_called_once()

    def test_non_tiktok_account_400(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.youtube, handle="@ytchannel",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.post(
            f"/analytics/accounts/{account.id}/scrape",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 400


class TestAnalyticsSchemas:
    def test_snapshot_response(self):
        resp = SnapshotResponse(
            id="abc",
            account_id="acc1",
            followers=1000,
            following=50,
            total_likes=50000,
            total_videos=30,
            bio="Test bio",
            avatar_url=None,
            recent_videos=[],
            scraped_at="2026-03-22T12:00:00Z",
        )
        assert resp.followers == 1000

    def test_growth_response(self):
        resp = GrowthResponse(
            current_followers=1000,
            previous_followers=800,
            follower_change=200,
            current_likes=50000,
            previous_likes=45000,
            likes_change=5000,
            current_videos=30,
            previous_videos=25,
            videos_change=5,
            period_days=7,
            avg_views=15000,
            avg_likes=1200,
            avg_comments=80,
        )
        assert resp.follower_change == 200

    def test_cluster_overview(self):
        resp = ClusterOverviewResponse(
            cluster_id="c1",
            cluster_name="Joe Fazer",
            total_followers=250000,
            total_likes=12000000,
            total_videos=500,
            account_count=3,
            accounts=[],
        )
        assert resp.account_count == 3
