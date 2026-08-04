import logging
import os
import secrets
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import uvicorn
from filelock import FileLock, Timeout

from app.config import Settings
from app.desktop_config import DISPLAY_NAME, VERSION
from app.desktop_paths import DesktopPaths


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    os.environ["TALABIYTAK_DESKTOP_LAUNCH"] = "1"
    from app.main import create_app

    paths = DesktopPaths.create()
    handler = RotatingFileHandler(
        paths.logs / "talabiytak.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
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
        port = free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None)
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name="local-fastapi", daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("local server did not start")
        import webview

        webview.create_window(
            DISPLAY_NAME,
            f"http://127.0.0.1:{port}/desktop-bootstrap?token={app.state.bootstrap_token}",
            width=1280,
            height=800,
            min_size=(900, 600),
        )
        webview.start(debug=False)
        server.should_exit = True
        thread.join(timeout=10)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
