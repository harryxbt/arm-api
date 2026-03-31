import logging
import os
import tempfile
import time

import httpx

from app.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class BunnyStorage(BaseStorage):
    def __init__(
        self,
        api_key: str,
        storage_zone: str,
        cdn_hostname: str,
        storage_hostname: str = "storage.bunnycdn.com",
        local_cache_dir: str = "/tmp/bunny_cache",
    ):
        self.api_key = api_key
        self.storage_zone = storage_zone
        self.cdn_hostname = cdn_hostname
        self.storage_hostname = storage_hostname
        self.local_cache_dir = local_cache_dir
        self.base_url = f"https://{storage_hostname}/{storage_zone}"
        os.makedirs(local_cache_dir, exist_ok=True)

    def save_file(self, prefix: str, filename: str, data: bytes, retries: int = 3) -> str:
        key = f"{prefix}/{filename}"
        url = f"{self.base_url}/{key}"
        for attempt in range(1, retries + 1):
            resp = httpx.put(
                url,
                content=data,
                headers={"AccessKey": self.api_key},
                timeout=300.0,
            )
            if resp.status_code in (200, 201):
                return key
            if attempt < retries:
                logger.warning("Bunny upload attempt %d/%d failed (%s %s), retrying...",
                               attempt, retries, resp.status_code, resp.reason_phrase)
                time.sleep(2 * attempt)
            else:
                resp.raise_for_status()
        return key

    def get_file(self, key: str) -> str:
        """Download from Bunny to local cache for processing."""
        local_path = os.path.join(self.local_cache_dir, key)
        if os.path.exists(local_path):
            return local_path
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        url = f"{self.base_url}/{key}"
        with httpx.stream("GET", url, headers={"AccessKey": self.api_key}, timeout=300.0) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    f.write(chunk)
        return local_path

    def get_download_url(self, key: str) -> str:
        return f"https://{self.cdn_hostname}/{key}"

    def get_upload_url(self, prefix: str, filename: str) -> str:
        return f"{self.base_url}/{prefix}/{filename}"
