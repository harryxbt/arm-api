import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.video import UploadResponse
from app.storage import storage

router = APIRouter(prefix="/videos", tags=["videos"])

ALLOWED_CONTENT_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
CHUNK_SIZE = 1024 * 1024  # 1MB


async def _read_upload_with_limit(file: UploadFile) -> bytes:
    """Read upload in chunks, abort early if too large."""
    chunks = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large (max 500MB)")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/upload", response_model=UploadResponse)
async def upload_video(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")
    data = await _read_upload_with_limit(file)
    filename = f"{uuid.uuid4()}_{file.filename}"
    key = storage.save_file("uploads", filename, data)
    return UploadResponse(key=key)


@router.post("/upload-gameplay", response_model=UploadResponse)
async def upload_gameplay(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")
    data = await _read_upload_with_limit(file)
    filename = f"{uuid.uuid4()}_{file.filename}"
    key = storage.save_file("gameplay", filename, data)
    return UploadResponse(key=key)
