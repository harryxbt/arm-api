# app/analytics_worker.py
import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.cluster import ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from app.services.tiktok_scraper import TikTokScraper
from app.worker import celery_app

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url)
AnalyticsSession = sessionmaker(bind=engine)


def _poll_account_analytics_logic():
    db = AnalyticsSession()
    try:
        accounts = (
            db.query(ClusterAccount)
            .filter(ClusterAccount.platform == Platform.tiktok)
            .all()
        )
        for account in accounts:
            scrape_tiktok_profile.delay(str(account.id))
            logger.info("Dispatched scrape for account %s (%s)", account.id, account.handle)
    finally:
        db.close()


def _scrape_tiktok_profile_logic(account_id: str):
    db = AnalyticsSession()
    try:
        account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
        if not account:
            logger.error("ClusterAccount %s not found", account_id)
            return

        scraper = TikTokScraper()
        data = scraper.scrape(account.handle)

        snapshot = ProfileSnapshot(
            account_id=account.id,
            followers=data["followers"],
            following=data["following"],
            total_likes=data["total_likes"],
            total_videos=data["total_videos"],
            bio=data.get("bio"),
            avatar_url=data.get("avatar_url"),
            recent_videos=data.get("recent_videos"),
            scraped_at=data.get("scraped_at", datetime.now(timezone.utc)),
        )
        db.add(snapshot)
        db.commit()
        logger.info("Snapshot created for account %s: %d followers", account.handle, data["followers"])

    except Exception as e:
        db.rollback()
        logger.exception("Scrape failed for account %s: %s", account_id, e)
        raise
    finally:
        db.close()


@celery_app.task(name="poll_account_analytics")
def poll_account_analytics():
    _poll_account_analytics_logic()


@celery_app.task(name="scrape_tiktok_profile", bind=True, max_retries=3)
def scrape_tiktok_profile(self, account_id: str):
    try:
        _scrape_tiktok_profile_logic(account_id)
    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)
        logger.error("Scrape permanently failed for account %s after %d retries", account_id, self.max_retries)
