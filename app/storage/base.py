from abc import ABC, abstractmethod


class BaseStorage(ABC):
    @abstractmethod
    def save_file(self, prefix: str, filename: str, data: bytes) -> str:
        """Save file, return storage key."""
        ...

    @abstractmethod
    def get_file(self, key: str) -> str:
        """Get local file path for a storage key."""
        ...

    @abstractmethod
    def get_download_url(self, key: str) -> str:
        """Get a URL/path to download a file."""
        ...

    @abstractmethod
    def get_upload_url(self, prefix: str, filename: str) -> str:
        """Get a URL/path for uploading a file. Used for presigned URLs in S3."""
        ...
