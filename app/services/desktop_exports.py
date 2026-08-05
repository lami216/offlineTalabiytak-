import os
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class DesktopExport:
    token: str
    temporary_path: Path
    suggested_filename: str
    mime_type: str
    created_at: float


class DesktopExportManager:
    def __init__(self, root: Path, ttl_seconds=1800, max_exports=50):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.max_exports = max_exports
        self._lock = threading.Lock()
        self._exports = {}
        self.cleanup_expired()

    def register(
        self, data: bytes, suggested_filename: str, mime_type: str = MIME_XLSX
    ) -> DesktopExport:
        self.cleanup_expired()
        token = secrets.token_urlsafe(32)
        temp = self.root / f"{token}.tmp"
        tmp = temp.with_suffix(".writing")
        tmp.write_bytes(data)
        os.replace(tmp, temp)
        exp = DesktopExport(
            token,
            temp,
            os.path.basename(suggested_filename) or "export.xlsx",
            mime_type,
            time.time(),
        )
        with self._lock:
            self._exports[token] = exp
            for old in sorted(self._exports.values(), key=lambda x: x.created_at)[
                : -self.max_exports
            ]:
                self._remove_locked(old.token)
        return exp

    def get(self, token: str) -> DesktopExport | None:
        with self._lock:
            exp = self._exports.get(token)
            if (
                not exp
                or time.time() - exp.created_at > self.ttl_seconds
                or not exp.temporary_path.is_file()
            ):
                if exp:
                    self._remove_locked(token)
                return None
            return exp

    def consume_after_success(self, token: str):
        with self._lock:
            self._remove_locked(token)

    def _remove_locked(self, token):
        exp = self._exports.pop(token, None)
        if exp:
            exp.temporary_path.unlink(missing_ok=True)

    def cleanup_expired(self):
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            for token, exp in list(self._exports.items()):
                if exp.created_at < cutoff:
                    self._remove_locked(token)
        for path in self.root.glob("*.tmp"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                pass


class DesktopFileDialogBridge:
    def __init__(self, manager, window_provider=None):
        self.manager = manager
        self.window_provider = window_provider
        self._last_folder = None

    def save_generated_file(self, export_token):
        exp = self.manager.get(export_token)
        if exp is None:
            return {"ok": False, "message": "انتهت صلاحية الملف المؤقت."}
        path = self._choose_path(exp.suggested_filename)
        if not path:
            return {"ok": False, "cancelled": True}
        target = Path(path)
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        try:
            shutil.copyfile(exp.temporary_path, tmp)
            os.replace(tmp, target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        self.manager.consume_after_success(export_token)
        self._last_folder = str(target.parent)
        return {"ok": True, "path": str(target), "filename": target.name}

    def open_saved_folder(self, path):
        return {"ok": True}

    def _choose_path(self, suggested):
        if self.window_provider:
            return self.window_provider(suggested)
        import webview

        windows = getattr(webview, "windows", [])
        window = windows[0] if windows else None
        if not window:
            return None
        result = window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=suggested,
            file_types=("Excel Workbook (*.xlsx)",),
        )
        return result[0] if isinstance(result, (list, tuple)) else result
