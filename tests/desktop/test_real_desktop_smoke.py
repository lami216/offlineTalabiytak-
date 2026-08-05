import json
import logging
import secrets
import time

import pytest
from httpx import ASGITransport, AsyncClient

import desktop_launcher
from app.config import Settings
from app.desktop_config import DISPLAY_NAME
from app.desktop_paths import DesktopPaths
from app.main import create_app


def test_real_desktop_http_smoke_exercises_dashboard_with_lifespan_on(tmp_path):
    report = tmp_path / "real-smoke.json"

    assert desktop_launcher._run_real_desktop_http_smoke_test(str(report)) == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["success"] is True
    stages = {entry["stage"] for entry in payload["stages"]}
    assert "http-dashboard" in stages
    assert {"http-app-icon-32", "http-app-icon-192"} <= stages
    assert {"http-products", "http-imports", "http-orders", "http-pricing"} <= stages
    assert "sqlite-closed" in stages


@pytest.mark.asyncio
async def test_desktop_500_writes_traceback_without_secrets(tmp_path):
    paths = DesktopPaths.create(tmp_path)
    log_path = paths.logs / "talabiytak.log"
    handler = desktop_launcher.configure_file_logging(log_path)
    settings = Settings(
        _env_file=None,
        desktop_mode=True,
        data_dir=str(paths.root.parent),
        secret_key=secrets.token_urlsafe(48),
        app_name=DISPLAY_NAME,
        app_env="desktop",
        trusted_hosts="*",
    )
    app = create_app(settings)
    token = "bootstrap-token-secret"
    cookie_secret = None

    @app.get("/__test_error")
    async def test_error():
        raise ValueError("forced desktop smoke failure")

    async with app.router.lifespan_context(app):
        app.state.bootstrap_token = token
        app.state.bootstrap_token_expires_at = time.time() + 60
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://127.0.0.1",
            headers={"host": "127.0.0.1"},
        ) as client:
            bootstrap = await client.get(
                f"/desktop-bootstrap?token={token}", follow_redirects=False
            )
            cookie_secret = bootstrap.headers.get("set-cookie", "")
            response = await client.get(
                "/__test_error", headers={"x-request-id": "rid-desktop-test"}
            )

    handler.flush()
    logging.shutdown()
    text = log_path.read_text(encoding="utf-8")
    assert response.status_code == 500
    assert text
    assert "rid-desktop-test" in text
    assert "ValueError" in text
    assert "Traceback" in text
    assert token not in text
    assert cookie_secret not in text
