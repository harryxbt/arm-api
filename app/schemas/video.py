from pydantic import BaseModel


class UploadResponse(BaseModel):
    key: str
