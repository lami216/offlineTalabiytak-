import json

import pytest

import desktop_launcher


@pytest.mark.parametrize("secret", ["secret_key", "session", "bootstrap_token"])
def test_smoke_success_report_excludes_secret_names(tmp_path, secret):
    report = tmp_path / "smoke.json"
    assert desktop_launcher._run_smoke_test(str(report)) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["stage"] == "completed"
    stages = [entry["stage"] for entry in payload["stages"]]
    for expected in (
        "create-temp-directory",
        "create-desktop-paths",
        "create-settings",
        "create-app",
        "enter-lifespan",
        "database-ping",
        "catalog-readiness",
        "leave-lifespan",
        "close-database",
        "cleanup-temp-directory",
        "completed",
    ):
        assert expected in stages
    assert secret not in report.read_text(encoding="utf-8")


def test_smoke_failure_report_contains_traceback(monkeypatch, tmp_path):
    class BadCatalog:
        async def readiness(self):
            return {"status": "not-ready"}

    original = desktop_launcher._run_smoke_test.__globals__["_base_smoke_report"]

    from app import main as app_main

    original_configure = app_main.configure_services

    def bad_configure(app, database, storage, *, backend):
        original_configure(app, database, storage, backend=backend)
        app.state.catalog = BadCatalog()

    monkeypatch.setattr(app_main, "configure_services", bad_configure)
    report = tmp_path / "failed-smoke.json"
    assert desktop_launcher._run_smoke_test(str(report)) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["success"] is False
    assert payload["stage"] == "catalog-readiness"
    assert payload["exception_type"] == "RuntimeError"
    assert "Unexpected readiness response" in payload["exception_message"]
    assert "Traceback" in payload["traceback"]
    text = report.read_text(encoding="utf-8")
    assert "secret_key" not in text
    assert "bootstrap_token" not in text
    assert original
