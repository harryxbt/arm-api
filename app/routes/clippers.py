# app/routes/clippers.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.clipper import Clipper, ClipperAccount, ClipAssignment, AssignmentStatus
from app.models.cluster import ClusterAccount, Cluster
from app.models.user import User
from app.schemas.clipper import (
    AssignmentListResponse,
    AssignmentResponse,
    ClipperDetailResponse,
    ClipperAccountResponse,
    ClipperListResponse,
    ClipperSummaryResponse,
    CreateAssignmentRequest,
    CreateClipperRequest,
    LinkAccountRequest,
    ResetClipperPasswordRequest,
)
from app.services.auth import hash_password
from app.storage import storage

router = APIRouter(prefix="/clippers", tags=["clippers"])


def _assignment_to_response(a: ClipAssignment) -> AssignmentResponse:
    download_url = storage.get_download_url(a.video_key) if a.video_key else None
    return AssignmentResponse(
        id=a.id,
        account_id=a.account_id,
        platform=a.account.platform.value if a.account else "",
        handle=a.account.handle if a.account else "",
        video_key=a.video_key,
        download_url=download_url,
        caption=a.caption,
        hashtags=a.hashtags,
        status=a.status.value,
        post_url=a.post_url,
        posted_at=a.posted_at.isoformat() if a.posted_at else None,
        created_at=a.created_at.isoformat(),
    )


# --- Clipper CRUD ---

@router.post("", response_model=ClipperDetailResponse, status_code=status.HTTP_201_CREATED)
def create_clipper(
    body: CreateClipperRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Clipper).filter(Clipper.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Clipper with this email already exists")
    clipper = Clipper(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
    )
    db.add(clipper)
    db.commit()
    db.refresh(clipper)
    return ClipperDetailResponse(
        id=clipper.id, email=clipper.email, name=clipper.name,
        is_active=clipper.is_active, accounts=[], created_at=clipper.created_at.isoformat(),
    )


@router.get("", response_model=ClipperListResponse)
def list_clippers(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clippers = db.query(Clipper).order_by(Clipper.created_at.desc()).all()
    return ClipperListResponse(clippers=[
        ClipperSummaryResponse(
            id=c.id, email=c.email, name=c.name, is_active=c.is_active,
            account_count=len(c.accounts), created_at=c.created_at.isoformat(),
        ) for c in clippers
    ])


@router.get("/{clipper_id}", response_model=ClipperDetailResponse)
def get_clipper(
    clipper_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clipper = db.query(Clipper).filter(Clipper.id == clipper_id).first()
    if not clipper:
        raise HTTPException(status_code=404, detail="Clipper not found")
    accounts = []
    for ca in clipper.accounts:
        acct = ca.account
        cluster = db.query(Cluster).filter(Cluster.id == acct.cluster_id).first() if acct else None
        accounts.append(ClipperAccountResponse(
            id=acct.id, platform=acct.platform.value, handle=acct.handle,
            cluster_name=cluster.name if cluster else "",
        ))
    return ClipperDetailResponse(
        id=clipper.id, email=clipper.email, name=clipper.name,
        is_active=clipper.is_active, accounts=accounts,
        created_at=clipper.created_at.isoformat(),
    )


@router.put("/{clipper_id}/reset-password", status_code=status.HTTP_200_OK)
def reset_clipper_password(
    clipper_id: str,
    body: ResetClipperPasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clipper = db.query(Clipper).filter(Clipper.id == clipper_id).first()
    if not clipper:
        raise HTTPException(status_code=404, detail="Clipper not found")
    clipper.password_hash = hash_password(body.password)
    db.commit()
    return {"status": "password_reset", "clipper_id": clipper_id}


@router.delete("/{clipper_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_clipper(
    clipper_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clipper = db.query(Clipper).filter(Clipper.id == clipper_id).first()
    if not clipper:
        raise HTTPException(status_code=404, detail="Clipper not found")
    clipper.is_active = False
    db.commit()


# --- Account linking ---

@router.post("/{clipper_id}/accounts", status_code=status.HTTP_201_CREATED)
def link_account(
    clipper_id: str,
    body: LinkAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clipper = db.query(Clipper).filter(Clipper.id == clipper_id).first()
    if not clipper:
        raise HTTPException(status_code=404, detail="Clipper not found")
    account = db.query(ClusterAccount).filter(ClusterAccount.id == body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    existing = db.query(ClipperAccount).filter(
        ClipperAccount.clipper_id == clipper_id,
        ClipperAccount.account_id == body.account_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Account already linked")
    link = ClipperAccount(clipper_id=clipper_id, account_id=body.account_id)
    db.add(link)
    db.commit()
    return {"status": "linked"}


@router.delete("/{clipper_id}/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_account(
    clipper_id: str,
    account_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    link = db.query(ClipperAccount).filter(
        ClipperAccount.clipper_id == clipper_id,
        ClipperAccount.account_id == account_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()


# --- Assignments (admin) ---

assignments_router = APIRouter(prefix="/assignments", tags=["assignments"])


@assignments_router.post("", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(
    body: CreateAssignmentRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(ClusterAccount).filter(ClusterAccount.id == body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    assignment = ClipAssignment(
        account_id=body.account_id,
        video_key=body.video_key,
        caption=body.caption,
        hashtags=body.hashtags,
        created_by=user.id,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return _assignment_to_response(assignment)


@assignments_router.get("", response_model=AssignmentListResponse)
def list_assignments(
    status_filter: str | None = Query(None, alias="status"),
    account_id: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ClipAssignment).order_by(ClipAssignment.created_at.desc())
    if status_filter:
        query = query.filter(ClipAssignment.status == AssignmentStatus(status_filter))
    if account_id:
        query = query.filter(ClipAssignment.account_id == account_id)
    assignments = query.limit(100).all()
    return AssignmentListResponse(
        assignments=[_assignment_to_response(a) for a in assignments]
    )
