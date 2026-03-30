# tests/test_analytics_worker.py
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from app.models.cluster import Cluster, ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from tests.conftest import TestSession


def _patch_session():
    """Patch AnalyticsSession to use the test database."""
    return patch("app.analytics_worker.AnalyticsSession", TestSession)


class TestPollAccountAnalytics:
    @patch("app.analytics_worker.scrape_tiktok_profile")
    def test_dispatches_for_tiktok_accounts(self, mock_scrape_task, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        tt_account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@tt",
        )
        db.add(tt_account)
        yt_account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.youtube, handle="@yt",
        )
        db.add(yt_account)
        db.commit()
        db.refresh(tt_account)

        with _patch_session():
            from app.analytics_worker import _poll_account_analytics_logic
            _poll_account_analytics_logic()

        mock_scrape_task.delay.assert_called_once_with(str(tt_account.id))


class TestScrapeTikTokProfile:
    @patch("app.analytics_worker.TikTokScraper")
    def test_successful_scrape_creates_snapshot(self, mock_scraper_class, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@joefazer",
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        mock_scraper = MagicMock()
        mock_scraper.scrape.return_value = {
            "followers": 125000,
            "following": 340,
            "total_likes": 8500000,
            "total_videos": 210,
            "bio": "Fitness creator",
            "avatar_url": "https://example.com/avatar.jpg",
            "recent_videos": [{"url": "https://tiktok.com/v/1", "views": 50000}],
            "scraped_at": datetime.now(timezone.utc),
        }
        mock_scraper_class.return_value = mock_scraper

        with _patch_session():
            from app.analytics_worker import _scrape_tiktok_profile_logic
            _scrape_tiktok_profile_logic(str(account.id))

        snapshots = db.query(ProfileSnapshot).filter(
            ProfileSnapshot.account_id == account.id
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].followers == 125000
        assert snapshots[0].total_likes == 8500000

    @patch("app.analytics_worker.TikTokScraper")
    def test_failed_scrape_no_snapshot(self, mock_scraper_class, db):
        cluster = Cluster(name="C")
        db.add(cluster)
        db.flush()
        account = ClusterAccount(
            cluster_id=cluster.id, platform=Platform.tiktok, handle="@broken",
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        mock_scraper = MagicMock()
        mock_scraper.scrape.side_effect = RuntimeError("Rate limited")
        mock_scraper_class.return_value = mock_scraper

        with _patch_session():
            from app.analytics_worker import _scrape_tiktok_profile_logic
            try:
                _scrape_tiktok_profile_logic(str(account.id))
            except RuntimeError:
                pass

        snapshots = db.query(ProfileSnapshot).filter(
            ProfileSnapshot.account_id == account.id
        ).all()
        assert len(snapshots) == 0
