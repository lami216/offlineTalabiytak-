import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from app.database.sqlite import SQLiteDatabase
from app.desktop_paths import DesktopPaths
from app.models import ImageAsset, Order, OrderItem, Product
from app.repositories.sqlite import SQLiteOrdersRepository, SQLiteProductsRepository
from app.services.backups import (
    BackupService,
    InvalidBackupError,
    apply_pending_restore,
    inspect_backup,
)
from app.services.desktop_exports import DesktopExportManager
from app.utils.objectid import new_id


def asset(file_id: str, size=5):
    return ImageAsset(
        file_id,
        f"images/{file_id[:2]}/{file_id[2:4]}/{file_id}.png",
        f"/local-media/{file_id}",
        None,
        file_id,
        "image/png",
        1,
        1,
        size,
    )


async def seed(paths: DesktopPaths):
    db = await SQLiteDatabase(paths.database).open()
    products = SQLiteProductsRepository(db)
    orders = SQLiteOrdersRepository(db)
    f1, f2 = "a" * 64, "b" * 64
    for fid in (f1, f2):
        path = paths.images / fid[:2] / fid[2:4] / f"{fid}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fid[:5].encode())
    p1 = await products.create(Product(new_id(), "قديم", "قديم", asset(f1)))
    p2 = await products.create(Product(new_id(), "مشترك", "مشترك", asset(f1)))
    old = datetime.now(UTC) - timedelta(days=45)
    await orders.create(
        Order(
            new_id(),
            "طلبية قديمة",
            [OrderItem(p1.id, p1.name, 3, 1), OrderItem(p2.id, p2.name, 7, 2)],
            old,
            old,
            old - timedelta(days=1),
        )
    )
    await orders.create(
        Order(new_id(), "طلبية جديدة", [OrderItem(p2.id, p2.name, 2, 1)], expires_at=old)
    )
    await db.connection.execute(
        "INSERT INTO imports ("
        "id, filename, status, counters, errors, processing_state, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), "source.xlsx", "completed", "{}", "[]", "{}", old.isoformat(), old.isoformat()),
    )
    await db.commit()
    return db


@pytest.mark.asyncio
async def test_old_orders_are_permanent_and_cleanup_noop(tmp_path):
    paths = DesktopPaths.create(tmp_path)
    db = await seed(paths)
    repo = SQLiteOrdersRepository(db)
    assert await repo.count_active() == 2
    assert [o.title for o in await repo.list_active()] == ["طلبية جديدة", "طلبية قديمة"]
    old = (await repo.list_active())[1]
    assert await repo.get_active(old.id)
    old.title = "معدلة"
    await repo.update(old)
    assert (await repo.get_active(old.id)).title == "معدلة"
    assert await repo.cleanup_expired() == 0
    await db.close()
    db2 = await SQLiteDatabase(paths.database).open()
    assert await SQLiteOrdersRepository(db2).count_active() == 2
    await SQLiteOrdersRepository(db2).delete(old.id)
    assert await SQLiteOrdersRepository(db2).count_active() == 1
    await db2.close()


@pytest.mark.asyncio
async def test_create_backup_manifest_exclusions_and_restore_clean_paths(tmp_path):
    paths = DesktopPaths.create(tmp_path / "src")
    paths.secret.write_text("do-not-copy", encoding="ascii")
    (paths.logs / "talabiytak.log").write_text("log", encoding="utf-8")
    (paths.temp / "price.xlsx").write_bytes(b"xlsx")
    db = await seed(paths)
    manager = DesktopExportManager(paths.temp / "exports")
    result = await BackupService(paths, db, manager).create_backup()
    backup = result["path"]
    assert zipfile.is_zipfile(backup)
    inspection = inspect_backup(backup, verify_images=True)
    manifest = inspection.manifest
    assert manifest["format"] == "talabiytak-backup"
    names = zipfile.ZipFile(backup).namelist()
    assert "manifest.json" in names and "database/talabiytak.db" in names
    assert not any(n.endswith(".xlsx") for n in names)
    assert not any(
        "settings.key" in n or "logs/" in n or "temp/" in n or n.startswith("/") or ".." in n
        for n in names
    )
    listed = {f["path"]: f for f in manifest["files"]}
    with zipfile.ZipFile(backup) as z:
        for name, info in listed.items():
            assert len(z.read(name)) == info["size"]
        snap = tmp_path / "snap.db"
        snap.write_bytes(z.read("database/talabiytak.db"))
    con = sqlite3.connect(snap)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT count(*) FROM orders").fetchone()[0] == 2
    con.close()
    await db.close()

    clean = DesktopPaths.create(tmp_path / "clean")
    clean.secret.write_text("new-secret", encoding="ascii")
    BackupService(clean, None).stage_restore(backup)
    assert apply_pending_restore(clean) is True
    assert clean.secret.read_text(encoding="ascii") == "new-secret"
    db2 = await SQLiteDatabase(clean.database).open()
    assert await SQLiteOrdersRepository(db2).count_active() == 2
    await db2.close()


@pytest.mark.asyncio
async def test_restore_over_existing_creates_recovery_and_rejects_malicious(tmp_path):
    a = DesktopPaths.create(tmp_path / "a")
    dba = await seed(a)
    backup = (
        await BackupService(a, dba, DesktopExportManager(a.temp / "exports")).create_backup()
    )["path"]
    await dba.close()
    b = DesktopPaths.create(tmp_path / "b")
    dbb = await SQLiteDatabase(b.database).open()
    await SQLiteProductsRepository(dbb).create(
        Product(new_id(), "A-only", "a-only", asset("c" * 64))
    )
    await dbb.close()
    BackupService(b, None).stage_restore(backup)
    assert apply_pending_restore(b) is True
    assert any((b.root / "recovery").glob("pre-restore-*"))

    bad = tmp_path / "bad.talbackup"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil", "x")
        z.writestr(
            "manifest.json", json.dumps({"format": "talabiytak-backup", "format_version": 1})
        )
    with pytest.raises(InvalidBackupError):
        inspect_backup(bad)
