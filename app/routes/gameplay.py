from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.gameplay import GameplayClip
from app.models.user import User
from app.schemas.gameplay import GameplayClipResponse
from app.storage import storage

router = APIRouter(prefix="/gameplay", tags=["gameplay"])

SEED_GAMEPLAY = [
    ("5ce0d9ee-a1b7-4312-b010-43275dfb0eef", "Subway Surfers", "gameplay/subway_surfers.mp4", 30.0),
    ("636c903c-3f10-423f-b269-cd606b573b9d", "Minecraft Parkour", "gameplay/minecraft_parkour.mp4", 30.0),
    ("6181f715-b934-4eaf-82d0-613014b55976", "Minecraft Parkour 4K", "gameplay/gameplay_1.mp4", 648.0),
    ("637ee636-4547-4a9f-96bc-fd20f6eccf02", "GTA 5 Mega Ramp", "gameplay/gameplay_2.mp4", 756.0),
    ("19ce0df3-6969-4722-b02a-5d9e9d17adc5", "Fortnite Solo Squads", "gameplay/gameplay_3.mp4", 876.0),
]


@router.post("/seed")
def seed_gameplay(db: Session = Depends(get_db)):
    added = 0
    for gid, name, key, dur in SEED_GAMEPLAY:
        if not db.query(GameplayClip).filter(GameplayClip.id == gid).first():
            db.add(GameplayClip(id=gid, name=name, storage_key=key, duration_seconds=dur))
            added += 1
    db.commit()
    return {"added": added}


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
