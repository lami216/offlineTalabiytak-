from io import BytesIO

import pytest
from PIL import Image

from app.config import Settings
from app.database.sqlite import SQLiteDatabase
from app.desktop_paths import DesktopPaths
from app.main import create_app
from app.services.storage.local import LocalImageStorage


def png():
    output = BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, "PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_first_run_and_migrations(tmp_path):
    paths = DesktopPaths.create(tmp_path)
    db = await SQLiteDatabase(paths.database).open()
    version = await (await db.connection.execute("SELECT version FROM schema_version")).fetchone()
    from app.database.sqlite import LATEST_SCHEMA

    assert version[0] == LATEST_SCHEMA
    assert paths.images.is_dir() and paths.logs.is_dir() and paths.temp.is_dir()
    await db.close()
    reopened = await SQLiteDatabase(paths.database).open()
    assert (await (await reopened.connection.execute("PRAGMA foreign_keys")).fetchone())[0] == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_local_storage_preserves_bytes_and_deduplicates(tmp_path):
    storage = LocalImageStorage(tmp_path / "images")
    raw = png()
    first = await storage.upload(raw, "png", "image/png", 3, 2)
    second = await storage.upload(raw, "png", "image/png", 3, 2)
    assert first.file_path == second.file_path
    assert await storage.read(first.file_path) == raw
    assert len(list(tmp_path.rglob("*.png"))) == 1


@pytest.mark.asyncio
async def test_local_storage_blocks_traversal(tmp_path):
    storage = LocalImageStorage(tmp_path / "images")
    with pytest.raises(ValueError):
        await storage.read("images/../../secret")
    with pytest.raises(ValueError):
        await storage.read("C:/Windows/system.ini")


def desktop_settings(tmp_path):
    return Settings(
        _env_file=None,
        desktop_mode=True,
        data_dir=str(tmp_path),
        secret_key="test-secret-key-that-is-long-enough",
        app_env="desktop",
        trusted_hosts="127.0.0.1,localhost",
    )


@pytest.mark.asyncio
async def test_lifespan_owns_database_and_closes_once(tmp_path):
    app = create_app(desktop_settings(tmp_path))
    async with app.router.lifespan_context(app):
        db = app.state.database
        assert await db.ping()
    assert db.connection is None


@pytest.mark.asyncio
async def test_lifespan_keeps_injected_database_open(tmp_path):
    paths = DesktopPaths.create(tmp_path)
    db = await SQLiteDatabase(paths.database).open()
    app = create_app(desktop_settings(tmp_path), database=db)
    app.state.paths = paths
    async with app.router.lifespan_context(app):
        assert await app.state.database.ping()
    assert db.connection is not None
    assert await db.ping()
    await db.close()
    assert db.connection is None
