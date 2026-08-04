from dataclasses import dataclass

from app.services.errors import AppError


class StorageError(AppError):
    """A storage operation failed without exposing backend details."""


class StorageDeleteError(StorageError):
    """A storage deletion failed and can be retried."""


@dataclass(frozen=True)
class StoredAsset:
    file_id: str
    file_path: str
    url: str
    thumbnail_url: str | None
    hash: str
    mime_type: str
    width: int
    height: int
    size: int | None = None


FORMAT_METADATA = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}
