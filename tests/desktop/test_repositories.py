from datetime import UTC, datetime, timedelta

import pytest

from app.database.sqlite import SQLiteDatabase
from app.models import ImageAsset, ImportedImage, Order, OrderItem, Product
from app.repositories.sqlite import (
    SQLiteImagesRepository,
    SQLiteImportsRepository,
    SQLiteOrdersRepository,
    SQLiteProductsRepository,
)
from app.utils.objectid import new_id


def asset(fid="a" * 64):
    return ImageAsset(
        fid,
        f"images/{fid[:2]}/{fid[2:4]}/{fid}.png",
        f"/local-media/{fid}",
        None,
        "h",
        "image/png",
        1,
        1,
        10,
    )


@pytest.mark.asyncio
async def test_imported_image_insert_update_persistence(tmp_path):
    db = await SQLiteDatabase(tmp_path / "db.sqlite").open()
    imports, images = SQLiteImportsRepository(db), SQLiteImagesRepository(db)
    batch = await imports.create("x.xlsx")
    img = await images.create(
        ImportedImage(
            "", batch.id, 1, "image1.png", hash="hash", status="unnamed", image_asset=asset()
        )
    )
    assert (await images.get(img.id)).image_asset.file_id == "a" * 64
    await images.update_status(img.id, "ignored")
    assert (await images.get(img.id)).status == "ignored"
    await db.close()
    db2 = await SQLiteDatabase(tmp_path / "db.sqlite").open()
    assert (await SQLiteImagesRepository(db2).get(img.id)).status == "ignored"
    await db2.close()


@pytest.mark.asyncio
async def test_missing_records_return_none(tmp_path):
    db = await SQLiteDatabase(tmp_path / "db.sqlite").open()
    images = SQLiteImagesRepository(db)
    imports = SQLiteImportsRepository(db)
    assert await images.update_status(new_id(), "ignored") is None
    assert await images.link_product(new_id(), new_id()) is None
    assert await imports.update(new_id(), status="failed") is None
    await db.close()


@pytest.mark.asyncio
async def test_order_update_is_transactional_on_item_failure(tmp_path):
    db = await SQLiteDatabase(tmp_path / "db.sqlite").open()
    products = SQLiteProductsRepository(db)
    pid = new_id()
    await products.create(Product(pid, "p", "p", asset()))
    repo = SQLiteOrdersRepository(db)
    oid = new_id()
    old = Order(
        oid, "old", [OrderItem(pid, "p", 1, 1)], expires_at=datetime.now(UTC) + timedelta(days=1)
    )
    await repo.create(old)
    broken = Order(
        oid,
        "new",
        [OrderItem(pid, "p", 2, 1), OrderItem(pid, "p", 3, 1)],
        expires_at=old.expires_at,
    )
    with pytest.raises(__import__("sqlite3").IntegrityError):
        await repo.update(broken)
    current = await repo.get(oid)
    assert current.title == "old"
    assert [(i.quantity, i.position) for i in current.items] == [(1, 1)]
    await db.close()
