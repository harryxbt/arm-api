import os
from app.storage.base import BaseStorage


class LocalStorage(BaseStorage):
    def __init__(self, base_dir: str):
        self.base_dir = os.path.realpath(base_dir)

    def _safe_path(self, *parts: str) -> str:
        """Resolve path and verify it stays within base_dir."""
        resolved = os.path.realpath(os.path.join(self.base_dir, *parts))
        if not resolved.startswith(self.base_dir + os.sep) and resolved != self.base_dir:
            raise ValueError(f"Path traversal detected: {parts}")
        return resolved

    def save_file(self, prefix: str, filename: str, data: bytes) -> str:
        file_path = self._safe_path(prefix, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)
        return f"{prefix}/{filename}"

    def get_file(self, key: str) -> str:
        return self._safe_path(key)

    def get_download_url(self, key: str) -> str:
        return f"/storage/{key}"

    def get_upload_url(self, prefix: str, filename: str) -> str:
        return f"/storage/{prefix}/{filename}"
