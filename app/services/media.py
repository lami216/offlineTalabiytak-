from dataclasses import dataclass

from app.services.errors import ValidationError

_HEX64 = set("0123456789abcdef")


@dataclass(frozen=True)
class MediaAssetForResponse:
    path: object
    mime_type: str


class LocalMediaService:
    def __init__(self, images, products, storage):
        self.images = images
        self.products = products
        self.storage = storage

    async def resolve(self, asset_id: str) -> MediaAssetForResponse:
        if (
            not isinstance(asset_id, str)
            or len(asset_id) != 64
            or any(c not in _HEX64 for c in asset_id)
        ):
            raise ValidationError("معرّف الصورة غير صالح")
        asset = await self.images.find_asset_by_file_id(asset_id)
        if asset is None:
            asset = await self.products.find_asset_by_file_id(asset_id)
        if asset is None:
            raise FileNotFoundError(asset_id)
        path = self.storage.resolve_for_response(asset.file_path)
        return MediaAssetForResponse(
            path=path, mime_type=asset.mime_type or "application/octet-stream"
        )
