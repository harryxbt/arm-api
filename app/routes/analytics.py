# app/routes/analytics.py
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.cluster import Cluster, ClusterAccount, Platform
from app.models.profile_snapshot import ProfileSnapshot
from app.models.user import User
from app.schemas.analytics import (
    AccountSummary,
    ClusterOverviewResponse,
    GrowthResponse,
    SnapshotResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


def _snapshot_to_response(snapshot: ProfileSnapshot) -> SnapshotResponse:
    return SnapshotResponse(
        id=str(snapshot.id),
        account_id=str(snapshot.account_id),
        followers=snapshot.followers,
        following=snapshot.following,
        total_likes=snapshot.total_likes,
        total_videos=snapshot.total_videos,
        bio=snapshot.bio,
        avatar_url=snapshot.avatar_url,
        recent_videos=snapshot.recent_videos,
        scraped_at=snapshot.scraped_at.isoformat(),
    )


def _get_latest_snapshot(db: Session, account_id: str) -> ProfileSnapshot | None:
    return (
        db.query(ProfileSnapshot)
        .filter(ProfileSnapshot.account_id == account_id)
        .order_by(ProfileSnapshot.scraped_at.desc())
        .first()
    )


def _dispatch_scrape(account_id: str) -> None:
    try:
        from app.analytics_worker import scrape_tiktok_profile
        scrape_tiktok_profile.delay(account_id)
    except Exception:
        logger.warning("Could not dispatch scrape for account %s", account_id)


@router.get("/accounts/{account_id}/current", response_model=SnapshotResponse)
def get_current_snapshot(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    snapshot = _get_latest_snapshot(db, account_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshots found for this account")
    return _snapshot_to_response(snapshot)


@router.get("/accounts/{account_id}/history", response_model=list[SnapshotResponse])
def get_history(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=500),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    query = db.query(ProfileSnapshot).filter(ProfileSnapshot.account_id == account_id)
    if from_date:
        query = query.filter(ProfileSnapshot.scraped_at >= from_date)
    else:
        default_from = datetime.now(timezone.utc) - timedelta(days=30)
        query = query.filter(ProfileSnapshot.scraped_at >= default_from)
    if to_date:
        query = query.filter(ProfileSnapshot.scraped_at <= to_date)
    snapshots = query.order_by(ProfileSnapshot.scraped_at.desc()).limit(limit).all()
    return [_snapshot_to_response(s) for s in snapshots]


@router.get("/accounts/{account_id}/growth", response_model=GrowthResponse)
def get_growth(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=365),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    latest = _get_latest_snapshot(db, account_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No snapshots found")
    target_date = datetime.now(timezone.utc) - timedelta(days=days)
    # Find snapshot at or before the target date; fall back to oldest available
    previous = (
        db.query(ProfileSnapshot)
        .filter(ProfileSnapshot.account_id == account_id, ProfileSnapshot.scraped_at <= target_date)
        .order_by(ProfileSnapshot.scraped_at.desc())
        .first()
    )
    if previous is None:
        # Fall back to the oldest snapshot that isn't the latest
        previous = (
            db.query(ProfileSnapshot)
            .filter(
                ProfileSnapshot.account_id == account_id,
                ProfileSnapshot.id != latest.id,
            )
            .order_by(ProfileSnapshot.scraped_at.asc())
            .first()
        )
    avg_views = avg_likes = avg_comments = None
    if latest.recent_videos:
        videos = latest.recent_videos
        if videos:
            avg_views = sum(v.get("views", 0) for v in videos) / len(videos)
            avg_likes = sum(v.get("likes", 0) for v in videos) / len(videos)
            avg_comments = sum(v.get("comments", 0) for v in videos) / len(videos)
    return GrowthResponse(
        current_followers=latest.followers,
        previous_followers=previous.followers if previous else None,
        follower_change=(latest.followers - previous.followers) if previous else None,
        current_likes=latest.total_likes,
        previous_likes=previous.total_likes if previous else None,
        likes_change=(latest.total_likes - previous.total_likes) if previous else None,
        current_videos=latest.total_videos,
        previous_videos=previous.total_videos if previous else None,
        videos_change=(latest.total_videos - previous.total_videos) if previous else None,
        period_days=days,
        avg_views=avg_views,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
    )


@router.get("/clusters/{cluster_id}/overview", response_model=ClusterOverviewResponse)
def get_cluster_overview(
    cluster_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    accounts = (
        db.query(ClusterAccount)
        .filter(ClusterAccount.cluster_id == cluster_id, ClusterAccount.platform == Platform.tiktok)
        .all()
    )
    total_followers = total_likes = total_videos = 0
    account_summaries = []
    for account in accounts:
        latest = _get_latest_snapshot(db, account.id)
        summary = AccountSummary(
            account_id=str(account.id),
            handle=account.handle,
            platform=account.platform.value,
            followers=latest.followers if latest else None,
            total_likes=latest.total_likes if latest else None,
            total_videos=latest.total_videos if latest else None,
            last_scraped=latest.scraped_at.isoformat() if latest else None,
        )
        account_summaries.append(summary)
        if latest:
            total_followers += latest.followers
            total_likes += latest.total_likes
            total_videos += latest.total_videos
    return ClusterOverviewResponse(
        cluster_id=str(cluster.id),
        cluster_name=cluster.name,
        total_followers=total_followers,
        total_likes=total_likes,
        total_videos=total_videos,
        account_count=len(accounts),
        accounts=account_summaries,
    )


@router.post("/accounts/{account_id}/scrape", status_code=status.HTTP_202_ACCEPTED)
def manual_scrape(
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.platform != Platform.tiktok:
        raise HTTPException(status_code=400, detail="Analytics scraping is only supported for TikTok accounts")
    _dispatch_scrape(str(account.id))
    return {"status": "scrape dispatched", "account_id": str(account.id)}
