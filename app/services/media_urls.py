def asset_delivery_url(settings, asset):
    if not asset:
        return None
    if settings.desktop_mode:
        return asset.url
    return settings.imagekit_delivery_url(asset.file_path)
