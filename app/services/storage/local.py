import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

from app.services.errors import ImageKitError, RemoteDeleteError
from app.services.storage.imagekit import FORMAT_METADATA, StoredAsset


class LocalImageStorage:
    """Content-addressed storage constrained to the user's image directory."""

    def __init__(self, image_root: Path):
        self.root = Path(image_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative: str) -> Path:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "images":
            raise ValueError("invalid local image path")
        candidate = (self.root.parent / Path(*path.parts)).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("image path escapes storage")
        return candidate

    async def upload(self, data, extension, mime_type, width, height, **_kwargs):
        if not data:
            raise ImageKitError("لا يمكن حفظ صورة فارغة")
        try:
            with Image.open(BytesIO(data)) as image:
                detected, dimensions = FORMAT_METADATA.get((image.format or "").upper()), image.size
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageKitError("الصورة غير صالحة") from exc
        if detected != (extension, mime_type) or dimensions != (width, height):
            raise ImageKitError("بيانات الصورة لا تطابق محتواها")
        digest = sha256(data).hexdigest()
        relative = f"images/{digest[:2]}/{digest[2:4]}/{digest}.{extension}"
        target = self._resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".tmp")
            await asyncio.to_thread(temporary.write_bytes, data)
            temporary.replace(target)
        return StoredAsset(
            digest, relative, f"/local-media/{digest}", None, len(data), width, height, mime_type
        )

    async def read(self, relative):
        return await asyncio.to_thread(self._resolve(relative).read_bytes)

    async def exists(self, relative):
        return self._resolve(relative).is_file()

    async def delete(self, file_id, file_path=None):
        try:
            if file_path:
                targets = [self._resolve(file_path)]
            elif len(file_id) == 64 and all(c in "0123456789abcdef" for c in file_id):
                directory = self.root / file_id[:2] / file_id[2:4]
                targets = list(directory.glob(f"{file_id}.*"))
            else:
                raise ValueError("invalid content identifier")
            for target in targets:
                target.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            raise RemoteDeleteError("تعذر حذف الصورة المحلية") from exc

    async def update_tags(self, _file_id, _tags):
        return True
