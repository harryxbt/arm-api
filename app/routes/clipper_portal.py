# app/routes/clipper_portal.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_clipper
from app.models.clipper import Clipper, ClipperAccount, ClipAssignment, AssignmentStatus
from app.schemas.clipper import AssignmentListResponse, AssignmentResponse, SubmitPostRequest
from app.storage import storage

router = APIRouter(prefix="/clipper", tags=["clipper-portal"])


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


@router.get("/assignments", response_model=AssignmentListResponse)
def get_clipper_assignments(
    clipper: Clipper = Depends(get_current_clipper),
    db: Session = Depends(get_db),
):
    assignments = (
        db.query(ClipAssignment)
        .join(ClipperAccount, ClipperAccount.account_id == ClipAssignment.account_id)
        .filter(ClipperAccount.clipper_id == clipper.id)
        .order_by(ClipAssignment.created_at.desc())
        .all()
    )
    return AssignmentListResponse(
        assignments=[_assignment_to_response(a) for a in assignments]
    )


@router.put("/assignments/{assignment_id}/submit")
def submit_post_link(
    assignment_id: str,
    body: SubmitPostRequest,
    clipper: Clipper = Depends(get_current_clipper),
    db: Session = Depends(get_db),
):
    assignment = db.query(ClipAssignment).filter(ClipAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    link = db.query(ClipperAccount).filter(
        ClipperAccount.clipper_id == clipper.id,
        ClipperAccount.account_id == assignment.account_id,
    ).first()
    if not link:
        raise HTTPException(status_code=403, detail="You are not assigned to this account")

    assignment.post_url = body.post_url
    assignment.status = AssignmentStatus.posted
    assignment.posted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assignment)
    return _assignment_to_response(assignment)
