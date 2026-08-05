import argparse
import asyncio
import json
import logging
import os
import platform
import secrets
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from http.cookiejar import CookieJar
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from filelock import FileLock, Timeout

from app.config import Settings
from app.desktop_config import DISPLAY_NAME, VERSION
from app.desktop_paths import DesktopPaths


def reserved_loopback_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    return sock


def _write_smoke_report(path, report):
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _base_smoke_report():
    return {
        "success": False,
        "stage": "starting",
        "sys_executable": sys.executable,
        "cwd": os.getcwd(),
        "sys_meipass": getattr(sys, "_MEIPASS", None),
        "application_version": VERSION,
        "python_version": platform.python_version(),
        "data_directory": None,
        "database_path": None,
        "exception_type": None,
        "exception_message": None,
        "traceback": None,
        "stages": [],
    }


def configure_file_logging(log_path):
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    for name in ("app", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.propagate = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return handler


def _run_smoke_test(report_path=None):
    os.environ["TALABIYTAK_DESKTOP_LAUNCH"] = "1"
    report = _base_smoke_report()

    def stage(name, **details):
        report["stage"] = name
        entry = {"stage": name, "success": True}
        entry.update(details)
        report["stages"].append(entry)

    async def smoke():
        from app.main import create_app

        tmp_ctx = None
        sock = None
        server = None
        thread = None
        try:
            stage("create-temp-directory")
            tmp_ctx = tempfile.TemporaryDirectory(prefix="talabiytak-smoke-")
            tmp = Path(tmp_ctx.name)
            stage("create-desktop-paths")
            root = DesktopPaths.create(tmp)
            report["data_directory"] = str(root.root.parent)
            report["database_path"] = str(root.database)
            stage("create-settings")
            settings = Settings(
                _env_file=None,
                desktop_mode=True,
                data_dir=str(root.root.parent),
                secret_key=secrets.token_urlsafe(48),
                app_name=DISPLAY_NAME,
                app_env="desktop",
                trusted_hosts="127.0.0.1,localhost",
            )
            stage("create-app")
            app = create_app(settings)
            stage("enter-lifespan")
            async with app.router.lifespan_context(app):
                db = app.state.database
                report["database_path"] = str(getattr(db, "path", report["database_path"]))
                if not await db.ping():
                    raise RuntimeError("SQLite ping returned false")
                stage("database-ping", actual=True)
                expected = {"status": "ready", "database": "sqlite", "storage": "local"}
                report["stage"] = "catalog-readiness"
                actual = await app.state.catalog.readiness()
                if actual != expected:
                    raise RuntimeError(
                        f"Unexpected readiness response: expected={expected!r}, actual={actual!r}"
                    )
                stage("catalog-readiness", expected=expected, actual=actual)
                sock = reserved_loopback_socket()
                port = sock.getsockname()[1]
                config = uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    log_config=None,
                    access_log=False,
                    lifespan="off",
                )
                server = uvicorn.Server(config)
                thread = threading.Thread(
                    target=lambda: server.run(sockets=[sock]),
                    name="smoke-fastapi",
                    daemon=True,
                )
                thread.start()
                deadline = time.monotonic() + 15
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not server.started:
                    raise RuntimeError("local server did not start")
                stage("server-started", port=port)
                for endpoint in ("/health", "/ready"):
                    url = f"http://127.0.0.1:{port}{endpoint}"
                    with urllib.request.urlopen(url, timeout=10) as response:
                        body = response.read().decode("utf-8")
                        if response.status != 200:
                            raise RuntimeError(
                                f"{endpoint} returned HTTP {response.status}: {body}"
                            )
                        payload = json.loads(body)
                    if endpoint == "/ready" and (
                        payload.get("database"),
                        payload.get("storage"),
                    ) != ("sqlite", "local"):
                        raise RuntimeError(f"Unexpected /ready payload: {payload!r}")
                    stage(f"http-{endpoint.lstrip('/')}", status=200, actual=payload)
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError("local server thread did not stop")
                stage("server-stopped")
                sock.close()
                sock = None
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.settimeout(1)
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        raise RuntimeError(f"local server port {port} is still open")
                stage("server-port-closed", port=port)
            stage("leave-lifespan")
            stage("close-database")
            tmp_ctx.cleanup()
            tmp_ctx = None
            stage("cleanup-temp-directory")
            report["success"] = True
            stage("completed")
            return 0
        finally:
            if server is not None:
                server.should_exit = True
            if thread is not None and thread.is_alive():
                thread.join(timeout=5)
            if sock is not None:
                sock.close()
            if tmp_ctx is not None:
                tmp_ctx.cleanup()

    try:
        code = asyncio.run(smoke())
    except Exception as exc:
        report["success"] = False
        report["exception_type"] = type(exc).__name__
        report["exception_message"] = str(exc)
        report["traceback"] = traceback.format_exc()
        try:
            print(report["traceback"], file=sys.stderr)
        except Exception:
            pass
        code = 1
    _write_smoke_report(report_path, report)
    return code


def _run_real_desktop_http_smoke_test(report_path=None):
    os.environ["TALABIYTAK_DESKTOP_LAUNCH"] = "1"
    report = _base_smoke_report()

    def stage(name, **details):
        report["stage"] = name
        entry = {"stage": name, "success": True}
        entry.update(details)
        report["stages"].append(entry)

    try:
        from app.main import create_app

        with tempfile.TemporaryDirectory(prefix="talabiytak-real-smoke-") as tmp_name:
            tmp = Path(tmp_name)
            paths = DesktopPaths.create(tmp)
            report["data_directory"] = str(paths.root.parent)
            report["database_path"] = str(paths.database)
            handler = configure_file_logging(paths.logs / "talabiytak.log")
            settings = Settings(
                _env_file=None,
                desktop_mode=True,
                data_dir=str(paths.root.parent),
                secret_key=secrets.token_urlsafe(48),
                app_name=DISPLAY_NAME,
                app_env="desktop",
                trusted_hosts="127.0.0.1,localhost",
            )
            app = create_app(settings)
            token = secrets.token_urlsafe(48)
            app.state.bootstrap_token = token
            app.state.bootstrap_token_expires_at = time.time() + 60
            sock = reserved_loopback_socket()
            port = sock.getsockname()[1]
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                lifespan="on",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=lambda: server.run(sockets=[sock]),
                name="real-smoke-fastapi",
                daemon=True,
            )
            try:
                thread.start()
                deadline = time.monotonic() + 15
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not server.started:
                    raise RuntimeError("local server did not complete startup")
                stage("server-started", port=port)
                opener = urllib.request.build_opener(
                    urllib.request.HTTPCookieProcessor(CookieJar())
                )
                bootstrap = urllib.request.Request(
                    f"http://127.0.0.1:{port}/desktop-bootstrap?token={token}",
                    headers={"Host": "127.0.0.1"},
                )
                with opener.open(bootstrap, timeout=10) as response:
                    html = response.read().decode("utf-8")
                    if response.status != 200:
                        raise RuntimeError(f"dashboard returned HTTP {response.status}")
                if "الرئيسية" not in html:
                    raise RuntimeError("dashboard title was not present in HTML")
                stage("http-dashboard", status=200)
                for endpoint in ("/products", "/imports", "/orders", "/pricing"):
                    with opener.open(f"http://127.0.0.1:{port}{endpoint}", timeout=10) as response:
                        response.read()
                        if response.status >= 500:
                            raise RuntimeError(f"{endpoint} returned HTTP {response.status}")
                    stage(f"http-{endpoint.strip('/')}", status=response.status)
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError("local server thread did not stop")
                sock.close()
                handler.flush()
                logging.shutdown()
            if getattr(app.state.database, "connection", None) is not None:
                raise RuntimeError("SQLite database was not closed")
            stage("sqlite-closed")
            report["success"] = True
            stage("completed")
            return_code = 0
    except Exception as exc:
        report["success"] = False
        report["exception_type"] = type(exc).__name__
        report["exception_message"] = str(exc)
        report["traceback"] = traceback.format_exc()
        return_code = 1
    _write_smoke_report(report_path, report)
    return return_code


def main():
    if "--smoke-test" in sys.argv:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--smoke-test", action="store_true")
        parser.add_argument("--smoke-report")
        args, _ = parser.parse_known_args()
        return _run_smoke_test(args.smoke_report)
    if "--real-desktop-smoke-test" in sys.argv:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--real-desktop-smoke-test", action="store_true")
        parser.add_argument("--smoke-report")
        args, _ = parser.parse_known_args()
        return _run_real_desktop_http_smoke_test(args.smoke_report)
    os.environ["TALABIYTAK_DESKTOP_LAUNCH"] = "1"
    from app.main import create_app

    paths = DesktopPaths.create()
    handler = configure_file_logging(paths.logs / "talabiytak.log")
    logging.info("Talabiytak %s starting", VERSION)
    lock = FileLock(paths.root / "application.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        import webview

        webview.create_window(
            DISPLAY_NAME, html="<h2 dir='rtl'>البرنامج يعمل بالفعل.</h2>", width=420, height=180
        )
        webview.start()
        return 2
    try:
        secret = (
            paths.secret.read_text(encoding="ascii")
            if paths.secret.exists()
            else secrets.token_urlsafe(48)
        )
        if not paths.secret.exists():
            paths.secret.write_text(secret, encoding="ascii")
        settings = Settings(
            _env_file=None,
            desktop_mode=True,
            data_dir=str(paths.root.parent),
            secret_key=secret,
            app_name=DISPLAY_NAME,
            app_env="desktop",
            trusted_hosts="127.0.0.1,localhost",
        )
        app = create_app(settings)
        app.state.bootstrap_token = secrets.token_urlsafe(48)
        app.state.bootstrap_token_expires_at = time.time() + 60
        sock = reserved_loopback_socket()
        port = sock.getsockname()[1]
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
            lifespan="on",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=lambda: server.run(sockets=[sock]),
            name="local-fastapi",
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            sock.close()
            raise RuntimeError("local server did not start")
        import webview

        from app.services.desktop_exports import DesktopFileDialogBridge

        bridge = DesktopFileDialogBridge(app.state.desktop_exports)
        webview.create_window(
            DISPLAY_NAME,
            f"http://127.0.0.1:{port}/desktop-bootstrap?token={app.state.bootstrap_token}",
            js_api=bridge,
            width=1280,
            height=800,
            min_size=(900, 600),
        )
        webview.start(debug=False)
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            logging.warning("local server did not stop within timeout")
        logging.info("Talabiytak %s stopped", VERSION)
    except Exception:
        logging.exception("desktop startup failed")
        try:
            import webview

            webview.create_window(
                DISPLAY_NAME,
                html="<h2 dir='rtl'>تعذر تشغيل البرنامج. راجع مجلد السجلات.</h2>",
                width=520,
                height=200,
            )
            webview.start()
        except Exception:
            pass
        return 1
    finally:
        lock.release()
        logging.info("Talabiytak %s shutdown complete", VERSION)
        handler.flush()
        logging.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
