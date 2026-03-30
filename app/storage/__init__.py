from app.config import settings
from app.storage.base import BaseStorage
from app.storage.local import LocalStorage


def _create_storage() -> BaseStorage:
    if settings.storage_backend == "bunny":
        from app.storage.bunny import BunnyStorage
        return BunnyStorage(
            api_key=settings.bunny_api_key,
            storage_zone=settings.bunny_storage_zone,
            cdn_hostname=settings.bunny_cdn_hostname,
            storage_hostname=settings.bunny_storage_hostname,
        )
    return LocalStorage(base_dir=settings.storage_dir)


storage = _create_storage()
