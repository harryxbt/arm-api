from pydantic import BaseModel


class GameplayClipResponse(BaseModel):
    id: str
    name: str
    thumbnail_url: str
    duration: float

    model_config = {"from_attributes": True}
