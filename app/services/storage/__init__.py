from app.services.storage.base import StorageDeleteError, StorageError, StoredAsset
from app.services.storage.local import LocalImageStorage


def __getattr__(name):
    if name == "ImageKitStorage":
        from app.services.storage.imagekit import ImageKitStorage

        return ImageKitStorage
    raise AttributeError(name)


__all__ = [
    "ImageKitStorage",
    "LocalImageStorage",
    "StorageDeleteError",
    "StorageError",
    "StoredAsset",
]
