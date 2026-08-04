from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.config import Settings
from app.database.sqlite import SQLiteDatabase
from app.desktop_paths import DesktopPaths
from app.main import create_app
from app.models import ImportedImage


def png():
    output = BytesIO()
    Image.new("RGB", (1, 1), "red").save(output, "PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_health_ready_and_local_media_requires_session(tmp_path):
    paths = DesktopPaths.create(tmp_path)
    settings = Settings(
        _env_file=None,
        desktop_mode=True,
        data_dir=str(tmp_path),
        secret_key="x" * 40,
        app_env="desktop",
        trusted_hosts="*",
    )
    db = await SQLiteDatabase(paths.database).open()
    app = create_app(settings, database=db)
    app.state.paths = paths
    async with app.router.lifespan_context(app):
        batch = await app.state.repositories.imports.create("x.xlsx")
        stored = await app.state.storage.upload(png(), "png", "image/png", 1, 1)
        await app.state.repositories.images.create(
            ImportedImage(
                "",
                batch.id,
                1,
                "x.png",
                hash=stored.file_id,
                status="unnamed",
                image_asset=stored,
            )
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://127.0.0.1",
            headers={"host": "127.0.0.1"},
        ) as client:
            assert (await client.get("/health")).json() == {"status": "ok"}
            ready = (await client.get("/ready")).json()
            assert ready == {"status": "ready", "database": "sqlite", "storage": "local"}
            assert (await client.get(f"/local-media/{stored.file_id}")).status_code == 403
            app.state.bootstrap_token = "t" * 40
            r = await client.get(f"/desktop-bootstrap?token={'t' * 40}", follow_redirects=False)
            cookie = r.headers["set-cookie"]
            assert "HttpOnly" in cookie and "SameSite=strict" in cookie
            assert (await client.get(f"/local-media/{stored.file_id}")).status_code == 200
            assert (await client.get("/local-media/../../etc/passwd")).status_code == 404
    await db.close()
