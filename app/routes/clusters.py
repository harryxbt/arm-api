from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.cluster import Cluster, ClusterAccount, AccountPost, Platform
from app.models.clip_extraction import ClipExtraction
from app.models.user import User
from app.schemas.cluster import (
    CreateClusterRequest,
    UpdateClusterRequest,
    AddAccountRequest,
    UpdateAccountRequest,
    AccountCredentials,
    CreatePostRequest,
    UpdatePostRequest,
    StatsResponse,
    PostResponse,
    AccountResponse,
    ClusterSummaryResponse,
    ClusterListResponse,
    ClusterDetailResponse,
    ExtractionSummaryInCluster,
)

router = APIRouter(prefix="/clusters", tags=["clusters"])


def _aggregate_stats(posts: list[AccountPost]) -> StatsResponse:
    return StatsResponse(
        views=sum(p.views for p in posts),
        likes=sum(p.likes for p in posts),
        comments=sum(p.comments for p in posts),
        shares=sum(p.shares for p in posts),
    )


def _post_to_response(post: AccountPost) -> PostResponse:
    return PostResponse(
        id=post.id,
        clip_id=post.clip_id,
        platform_post_id=post.platform_post_id,
        views=post.views,
        likes=post.likes,
        comments=post.comments,
        shares=post.shares,
        posted_at=post.posted_at.isoformat() if post.posted_at else None,
        created_at=post.created_at.isoformat(),
    )


def _account_to_response(account: ClusterAccount) -> AccountResponse:
    creds = None
    if account.credentials:
        creds = AccountCredentials(**account.credentials)
    return AccountResponse(
        id=account.id,
        platform=account.platform.value,
        handle=account.handle,
        credentials=creds,
        stats=_aggregate_stats(account.posts),
        posts=[_post_to_response(p) for p in account.posts],
        created_at=account.created_at.isoformat(),
    )


def _get_cluster_or_404(db: Session, cluster_id: str) -> Cluster:
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


def _get_account_or_404(db: Session, cluster_id: str, account_id: str) -> ClusterAccount:
    account = db.query(ClusterAccount).filter(
        ClusterAccount.id == account_id,
        ClusterAccount.cluster_id == cluster_id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


# --- Cluster CRUD ---

@router.post("", response_model=ClusterDetailResponse, status_code=status.HTTP_201_CREATED)
def create_cluster(
    body: CreateClusterRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cluster = Cluster(name=body.name)
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return ClusterDetailResponse(
        id=cluster.id,
        name=cluster.name,
        created_at=cluster.created_at.isoformat(),
        accounts=[],
        extractions=[],
        stats=StatsResponse(),
    )


@router.get("", response_model=ClusterListResponse)
def list_clusters(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clusters = db.query(Cluster).order_by(Cluster.created_at.desc()).all()
    summaries = []
    for cluster in clusters:
        all_posts = [p for acc in cluster.accounts for p in acc.posts]
        summaries.append(ClusterSummaryResponse(
            id=cluster.id,
            name=cluster.name,
            account_count=len(cluster.accounts),
            stats=_aggregate_stats(all_posts),
            created_at=cluster.created_at.isoformat(),
        ))
    return ClusterListResponse(clusters=summaries)


@router.get("/{cluster_id}", response_model=ClusterDetailResponse)
def get_cluster(
    cluster_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cluster = _get_cluster_or_404(db, cluster_id)
    all_posts = [p for acc in cluster.accounts for p in acc.posts]
    return ClusterDetailResponse(
        id=cluster.id,
        name=cluster.name,
        created_at=cluster.created_at.isoformat(),
        accounts=[_account_to_response(a) for a in cluster.accounts],
        extractions=[
            ExtractionSummaryInCluster(
                id=e.id,
                status=e.status.value,
                youtube_url=e.youtube_url,
                video_title=e.video_title,
                created_at=e.created_at.isoformat(),
            )
            for e in cluster.extractions
        ],
        stats=_aggregate_stats(all_posts),
    )


@router.put("/{cluster_id}", response_model=ClusterDetailResponse)
def update_cluster(
    cluster_id: str,
    body: UpdateClusterRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cluster = _get_cluster_or_404(db, cluster_id)
    cluster.name = body.name
    db.commit()
    db.refresh(cluster)
    all_posts = [p for acc in cluster.accounts for p in acc.posts]
    return ClusterDetailResponse(
        id=cluster.id,
        name=cluster.name,
        created_at=cluster.created_at.isoformat(),
        accounts=[_account_to_response(a) for a in cluster.accounts],
        extractions=[
            ExtractionSummaryInCluster(
                id=e.id,
                status=e.status.value,
                youtube_url=e.youtube_url,
                video_title=e.video_title,
                created_at=e.created_at.isoformat(),
            )
            for e in cluster.extractions
        ],
        stats=_aggregate_stats(all_posts),
    )


@router.delete("/{cluster_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cluster(
    cluster_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cluster = _get_cluster_or_404(db, cluster_id)
    db.query(ClipExtraction).filter(ClipExtraction.cluster_id == cluster_id).update(
        {"cluster_id": None}
    )
    db.delete(cluster)
    db.commit()


# --- Account Management ---

@router.post("/{cluster_id}/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def add_account(
    cluster_id: str,
    body: AddAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_cluster_or_404(db, cluster_id)
    platform = Platform(body.platform)

    existing = db.query(ClusterAccount).filter(
        ClusterAccount.cluster_id == cluster_id,
        ClusterAccount.platform == platform,
        ClusterAccount.handle == body.handle,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Account already exists in this cluster")

    creds = body.credentials.model_dump(exclude_none=True) if body.credentials else None
    account = ClusterAccount(cluster_id=cluster_id, platform=platform, handle=body.handle, credentials=creds)
    db.add(account)
    db.commit()
    db.refresh(account)
    return AccountResponse(
        id=account.id,
        platform=account.platform.value,
        handle=account.handle,
        stats=StatsResponse(),
        posts=[],
        created_at=account.created_at.isoformat(),
    )


@router.put("/{cluster_id}/accounts/{account_id}", response_model=AccountResponse)
def update_account(
    cluster_id: str,
    account_id: str,
    body: UpdateAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _get_account_or_404(db, cluster_id, account_id)
    if body.handle is not None:
        account.handle = body.handle
    if body.credentials is not None:
        account.credentials = body.credentials.model_dump(exclude_none=True)
    db.commit()
    db.refresh(account)
    return _account_to_response(account)


@router.delete("/{cluster_id}/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_account(
    cluster_id: str,
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _get_account_or_404(db, cluster_id, account_id)
    db.delete(account)
    db.commit()


# --- Post Tracking ---

@router.post("/{cluster_id}/accounts/{account_id}/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
def create_post(
    cluster_id: str,
    account_id: str,
    body: CreatePostRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_account_or_404(db, cluster_id, account_id)
    posted_at = None
    if body.posted_at:
        posted_at = datetime.fromisoformat(body.posted_at)

    post = AccountPost(
        account_id=account_id,
        clip_id=body.clip_id,
        platform_post_id=body.platform_post_id,
        views=body.views,
        likes=body.likes,
        comments=body.comments,
        shares=body.shares,
        posted_at=posted_at,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return _post_to_response(post)


@router.put("/{cluster_id}/accounts/{account_id}/posts/{post_id}", response_model=PostResponse)
def update_post(
    cluster_id: str,
    account_id: str,
    post_id: str,
    body: UpdatePostRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_account_or_404(db, cluster_id, account_id)
    post = db.query(AccountPost).filter(
        AccountPost.id == post_id,
        AccountPost.account_id == account_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if body.views is not None:
        post.views = body.views
    if body.likes is not None:
        post.likes = body.likes
    if body.comments is not None:
        post.comments = body.comments
    if body.shares is not None:
        post.shares = body.shares

    db.commit()
    db.refresh(post)
    return _post_to_response(post)


@router.delete("/{cluster_id}/accounts/{account_id}/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    cluster_id: str,
    account_id: str,
    post_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_account_or_404(db, cluster_id, account_id)
    post = db.query(AccountPost).filter(
        AccountPost.id == post_id,
        AccountPost.account_id == account_id,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    db.delete(post)
    db.commit()
