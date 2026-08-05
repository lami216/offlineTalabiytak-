from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.database.sqlite import SQLiteDatabase
from app.desktop_paths import DesktopPaths
from app.models import ImportedImage, Product
from app.services.arabic import ArabicNormalizationService
from app.services.desktop_exports import MIME_XLSX, DesktopExportManager, DesktopFileDialogBridge
from tests.desktop.test_routes import png


async def logged_client(app):
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"host": "127.0.0.1"},
    )
    app.state.bootstrap_token = "b" * 40
    app.state.bootstrap_token_expires_at = 9999999999
    await client.get(f"/desktop-bootstrap?token={'b' * 40}", follow_redirects=False)
    return client


@pytest.mark.asyncio
async def test_product_search_uses_local_media_bytes(tmp_path):
    paths = DesktopPaths.create(tmp_path)
    settings = Settings(
        _env_file=None,
        desktop_mode=True,
        data_dir=str(tmp_path),
        secret_key="x" * 40,
        trusted_hosts="*",
    )
    db = await SQLiteDatabase(paths.database).open()
    from app.main import create_app

    app = create_app(settings, database=db)
    app.state.paths = paths
    async with app.router.lifespan_context(app):
        data = png()
        stored = await app.state.storage.upload(data, "png", "image/png", 1, 1)
        await app.state.repositories.products.create(
            Product(
                "1" * 24,
                "اختبار صورة",
                ArabicNormalizationService().normalize("اختبار صورة"),
                stored,
            )
        )
        client = await logged_client(app)
        try:
            response = await client.get("/orders/product-search?q=اختبار")
            item = response.json()["items"][0]
            assert item["image_url"].startswith("/local-media/")
            assert "imagekit" not in item["image_url"].lower()
            assert "http" not in item["image_url"].lower()
            assert "file://" not in item["image_url"].lower()
            media = await client.get(item["image_url"])
            assert media.status_code == 200
            assert media.headers["content-type"].startswith("image/png")
            assert media.content == data
        finally:
            await client.aclose()
    await db.close()


@pytest.mark.asyncio
async def test_delete_duplicate_keeps_shared_product_asset(tmp_path):
    paths = DesktopPaths.create(tmp_path)
    settings = Settings(
        _env_file=None,
        desktop_mode=True,
        data_dir=str(tmp_path),
        secret_key="x" * 40,
        trusted_hosts="*",
    )
    db = await SQLiteDatabase(paths.database).open()
    from app.main import create_app

    app = create_app(settings, database=db)
    app.state.paths = paths
    async with app.router.lifespan_context(app):
        data = png()
        stored = await app.state.storage.upload(data, "png", "image/png", 1, 1)
        product_id = "2" * 24
        await app.state.repositories.products.create(
            Product(product_id, "منتج", ArabicNormalizationService().normalize("منتج"), stored)
        )
        batch = await app.state.repositories.imports.create("x.xlsx")
        image = await app.state.repositories.images.create(
            ImportedImage(
                "",
                batch.id,
                1,
                "x.png",
                hash=stored.file_id,
                status="duplicate",
                duplicate_of={"type": "product", "id": product_id},
                image_asset=stored,
            )
        )
        client = await logged_client(app)
        try:
            csrf = app.state.security.load(client.cookies.get(settings.session_cookie_name))["csrf"]
            r = await client.post(
                f"/imports/images/{image.id}/delete",
                data={"csrf_token": csrf, "return_status": "duplicate", "return_page": "1"},
                follow_redirects=False,
            )
            assert r.status_code == 303
            assert (await app.state.repositories.images.get(image.id)).status == "deleted"
            media = await client.get(f"/local-media/{stored.file_id}")
            assert media.status_code == 200
            assert media.content == data
        finally:
            await client.aclose()
    await db.close()


def test_desktop_export_bridge_cancel_retry_and_success(tmp_path):
    manager = DesktopExportManager(tmp_path / "exports", ttl_seconds=1800)
    export = manager.register(b"xlsx", "x.xlsx", MIME_XLSX)
    choices = iter([None, str(tmp_path / "chosen")])
    bridge = DesktopFileDialogBridge(manager, lambda _suggested: next(choices))
    assert bridge.save_generated_file(export.token) == {"ok": False, "cancelled": True}
    assert manager.get(export.token) is not None
    result = bridge.save_generated_file(export.token)
    assert result["ok"] is True
    assert Path(result["path"]).read_bytes() == b"xlsx"
    assert Path(result["path"]).suffix == ".xlsx"
    assert manager.get(export.token) is None
    assert bridge.save_generated_file("bad-token")["ok"] is False
