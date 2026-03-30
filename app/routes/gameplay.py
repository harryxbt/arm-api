from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.gameplay import GameplayClip
from app.models.user import User
from app.schemas.gameplay import GameplayClipResponse
from app.storage import storage

router = APIRouter(prefix="/gameplay", tags=["gameplay"])


@router.get("", response_model=list[GameplayClipResponse])
def list_gameplay(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    clips = db.query(GameplayClip).filter(GameplayClip.active == True).all()
    return [
        GameplayClipResponse(
            id=str(clip.id),
            name=clip.name,
            thumbnail_url=storage.get_download_url(clip.thumbnail_key) if clip.thumbnail_key else "",
            duration=clip.duration_seconds,
        )
        for clip in clips
    ]
