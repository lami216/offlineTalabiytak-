_HEX64 = set("0123456789abcdef")


def valid_local_asset_id(file_id: str) -> bool:
    return isinstance(file_id, str) and len(file_id) == 64 and all(c in _HEX64 for c in file_id)


def asset_delivery_url(settings, asset):
    if not asset:
        return None
    if settings.desktop_mode:
        file_id = str(asset.file_id or "").strip().lower()
        if not valid_local_asset_id(file_id):
            return None
        return f"/local-media/{file_id}"
    return settings.imagekit_delivery_url(asset.file_path)
