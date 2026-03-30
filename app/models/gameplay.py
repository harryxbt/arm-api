import uuid

from sqlalchemy import String, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class GameplayClip(Base):
    __tablename__ = "gameplay_library"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500))
    duration_seconds: Mapped[float] = mapped_column(Float)
    thumbnail_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
