from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from PIL import Image

from app.config import Settings
from app.database.sqlite import SQLiteDatabase
from app.desktop_paths import DesktopPaths
from app.models import ImportedImage, Product
from app.services.arabic import ArabicNormalizationService
from app.services.storage.base import StoredAsset
from tests.desktop.test_routes import png


def colored_png(color):
    data = BytesIO()
    with Image.new("RGB", (2, 2), color) as picture:
        picture.save(data, "PNG")
    return data.getvalue()


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


async def desktop_app(tmp_path):
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
    return app, db


@pytest.mark.asyncio
async def test_create_with_existing_image_and_repository_listing(tmp_path, monkeypatch):
    app, db = await desktop_app(tmp_path)
    async with app.router.lifespan_context(app):
        stored = await app.state.storage.upload(png(), "png", "image/png", 1, 1)
        source = await app.state.repositories.products.create(
            Product("1" * 24, "قفل 50", ArabicNormalizationService().normalize("قفل 50"), stored)
        )

        async def fail_upload(*_args, **_kwargs):
            raise AssertionError("storage.upload must not be called")

        monkeypatch.setattr(app.state.storage, "upload", fail_upload)
        second = await app.state.products.create_with_existing_image(source.id, "قفل 60")
        third = await app.state.products.create_with_existing_image(source.id, "قفل 70")
        assert {source.id, second.id, third.id} == {
            p.id for p in await app.state.repositories.products.list_by_file_id(stored.file_id)
        }
        assert second.id != source.id
        assert second.name == "قفل 60"
        assert second.normalized_name == ArabicNormalizationService().normalize("قفل 60")
        assert second.primary_image is not source.primary_image
        assert second.primary_image.file_id == source.primary_image.file_id
        assert second.primary_image.file_path == source.primary_image.file_path
        assert second.primary_image.hash == source.primary_image.hash
        second.primary_image = StoredAsset(
            "other", "images/other.png", "/local-media/other", None, "h", "image/png", 1, 1
        )
        assert source.primary_image.file_id == stored.file_id
    await db.close()


@pytest.mark.asyncio
async def test_delete_and_replace_keep_shared_asset_until_last_reference(tmp_path):
    app, db = await desktop_app(tmp_path)
    deletes = []
    async with app.router.lifespan_context(app):
        old_delete = app.state.storage.delete

        async def record_delete(file_id):
            deletes.append(file_id)
            return await old_delete(file_id)

        app.state.storage.delete = record_delete
        stored = await app.state.storage.upload(colored_png("red"), "png", "image/png", 2, 2)
        first = await app.state.repositories.products.create(
            Product("2" * 24, "قفل 50", ArabicNormalizationService().normalize("قفل 50"), stored)
        )
        second = await app.state.products.create_with_existing_image(first.id, "قفل 60")
        await app.state.products.delete(first.id)
        assert await app.state.repositories.products.get(second.id)
        assert deletes == []
        new_png = colored_png("blue")
        processed = app.state.processor.process(new_png)
        replaced = await app.state.products.replace(second.id, processed)
        assert replaced.primary_image.file_id != stored.file_id
        assert deletes == [stored.file_id]

        batch = await app.state.repositories.imports.create("x.xlsx")
        third = await app.state.repositories.products.create(
            Product(
                "3" * 24,
                "قفل 63",
                ArabicNormalizationService().normalize("قفل 63"),
                replaced.primary_image,
            )
        )
        await app.state.repositories.images.create(
            ImportedImage(
                "",
                batch.id,
                1,
                "x.png",
                status="saved_as_product",
                image_asset=replaced.primary_image,
            )
        )
        await app.state.products.delete(third.id)
        await app.state.products.delete(second.id)
        assert deletes == [stored.file_id]
    await db.close()


@pytest.mark.asyncio
async def test_shared_image_route_template_order_and_excel(tmp_path):
    app, db = await desktop_app(tmp_path)
    async with app.router.lifespan_context(app):
        client = await logged_client(app)
        try:
            csrf = app.state.security.load(
                client.cookies.get(app.state.settings.session_cookie_name)
            )["csrf"]
            stored = await app.state.storage.upload(png(), "png", "image/png", 1, 1)
            first = await app.state.repositories.products.create(
                Product(
                    "4" * 24, "قفل 50", ArabicNormalizationService().normalize("قفل 50"), stored
                )
            )
            bad = await client.post(
                f"/products/{first.id}/create-with-same-image",
                data={"name": "قفل"},
                headers={"X-Requested-With": "fetch"},
            )
            assert bad.status_code == 422 or bad.status_code == 400
            empty = await client.post(
                f"/products/{first.id}/create-with-same-image",
                data={"csrf_token": csrf, "name": " "},
                headers={"X-Requested-With": "fetch"},
            )
            assert empty.status_code == 400
            r = await client.post(
                f"/products/{first.id}/create-with-same-image",
                data={"csrf_token": csrf, "name": "قفل 60"},
                headers={"X-Requested-With": "fetch"},
            )
            assert r.status_code == 200
            second = r.json()["product"]
            assert second["image_url"].startswith("/local-media/")
            normal = await client.post(
                f"/products/{first.id}/create-with-same-image",
                data={"csrf_token": csrf, "name": "قفل 63"},
                follow_redirects=False,
            )
            assert normal.status_code == 303
            html = (await client.get(f"/products/{first.id}/edit")).text
            assert 'id="shared-image-products"' in html
            assert "shared-image-product-form" in html
            assert "إضافة منتج آخر بنفس الصورة" in html
            assert "إنشاء منتج بنفس الصورة" in html
            products_html = (await client.get("/products")).text
            assert "منتج آخر بنفس الصورة" not in products_html

            items, _ = await app.state.products.search("قفل")
            assert len(items) == 3
            order = await app.state.orders.create("طلبية", [p.id for p in items], [20, 15, 30])
            assert [i.product_id for i in order.items] == [p.id for p in items]
            assert [i.quantity for i in order.items] == [20, 15, 30]
            content = await app.state.excel_export.build(order)
            workbook = load_workbook(BytesIO(content))
            sheet = workbook["الطلبية"]
            assert [sheet[f"B{row}"].value for row in (4, 5, 6)] == [p.name for p in items]
            assert [sheet[f"C{row}"].value for row in (4, 5, 6)] == [20, 15, 30]
            workbook.close()
        finally:
            await client.aclose()
    await db.close()
