import hashlib
import json
import logging
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app.database.sqlite import LATEST_SCHEMA
from app.desktop_config import VERSION

log = logging.getLogger(__name__)
BACKUP_FORMAT = "talabiytak-backup"
FORMAT_VERSION = 1
REQUIRED_TABLES = {
    "schema_version",
    "imports",
    "imported_images",
    "products",
    "orders",
    "order_items",
    "orphan_cleanup",
}


class BackupError(Exception):
    pass


class InvalidBackupError(BackupError):
    pass


class RestoreError(BackupError):
    pass


@dataclass
class BackupInspection:
    manifest: dict
    archive_sha256: str | None = None


def utcstamp():
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path):
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _safe_archive_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise InvalidBackupError("تحتوي النسخة الاحتياطية على مسار غير آمن.")
    return str(p)


def _zip_is_symlink(info):
    return stat.S_ISLNK((info.external_attr >> 16) & 0o170000)


def _db_check(path: Path):
    con = sqlite3.connect(path)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise InvalidBackupError(
                "تعذر إنشاء النسخة الاحتياطية لأن قاعدة البيانات لم تجتز فحص السلامة."
            )
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise InvalidBackupError("قاعدة بيانات النسخة الاحتياطية غير مكتملة.")
        row = con.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        version = row[0] if row else 0
        if version > LATEST_SCHEMA:
            raise InvalidBackupError(
                "هذه النسخة الاحتياطية أُنشئت بإصدار أحدث من طلبياتك. حدّث التطبيق أولًا."
            )
        return version
    finally:
        con.close()


def _counts(db_path: Path, image_count: int):
    con = sqlite3.connect(db_path)
    try:
        names = ["products", "imports", "imported_images", "orders", "order_items"]
        c = {n: con.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in names}
        c["image_files"] = image_count
        return c
    finally:
        con.close()


class BackupService:
    def __init__(self, paths, database, export_manager=None):
        self.paths, self.database, self.export_manager = paths, database, export_manager

    async def create_backup(self):
        work = Path(tempfile.mkdtemp(prefix="backup-", dir=self.paths.temp))
        try:
            snap = work / "talabiytak.db"
            await self.database.backup_to(snap)
            schema = _db_check(snap)
            images = []
            if self.paths.images.exists():
                for p in self.paths.images.rglob("*"):
                    if p.is_symlink() or not p.is_file():
                        continue
                    rel = p.relative_to(self.paths.images).as_posix()
                    _safe_archive_path(rel)
                    images.append((p, f"images/{rel}"))
            files = []
            db_hash, db_size = sha256_file(snap)
            files.append({"path": "database/talabiytak.db", "size": db_size, "sha256": db_hash})
            for p, arc in images:
                digest, size = sha256_file(p)
                files.append({"path": arc, "size": size, "sha256": digest})
            manifest = {
                "format": BACKUP_FORMAT,
                "format_version": FORMAT_VERSION,
                "app_version": VERSION,
                "created_at": utcstamp(),
                "database_schema_version": schema,
                "database_path": "database/talabiytak.db",
                "files": files,
                "counts": _counts(snap, len(images)),
            }
            name = f"طلبياتك-نسخة-احتياطية-{datetime.now(UTC).strftime('%Y-%m-%d-%H%M')}.talbackup"
            target = work / (name + ".tmp")
            writing = work / (name + ".writing")
            with zipfile.ZipFile(writing, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                z.write(snap, "database/talabiytak.db")
                for p, arc in images:
                    z.write(p, arc)
            self.validate_backup(writing)
            os.replace(writing, target)
            export = (
                self.export_manager.register_existing_file(
                    target, name, "application/vnd.talabiytak.backup"
                )
                if self.export_manager
                else None
            )
            return {
                "path": target,
                "suggested_filename": name,
                "manifest": manifest,
                "export": export,
            }
        except Exception:
            shutil.rmtree(work, ignore_errors=True)
            raise

    def validate_backup(self, path):
        return inspect_backup(path)

    def stage_restore(self, archive_path):
        src = Path(archive_path)
        insp = inspect_backup(src, verify_images=True)
        pending = self.paths.temp / "pending-restore"
        pending.mkdir(parents=True, exist_ok=True)
        staged = pending / "restore.talbackup"
        shutil.copyfile(src, staged)
        digest, _ = sha256_file(staged)
        marker = {
            "archive_path": str(staged),
            "archive_sha256": digest,
            "requested_at": utcstamp(),
            "format_version": FORMAT_VERSION,
        }
        tmp = self.paths.temp / "pending-restore.json.writing"
        tmp.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.paths.temp / "pending-restore.json")
        return insp.manifest


def inspect_backup(path, verify_images=False):
    path = Path(path)
    if not path.is_file():
        raise InvalidBackupError("ملف النسخة الاحتياطية غير موجود.")
    seen = set()
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if not infos:
                raise InvalidBackupError("ملف النسخة الاحتياطية فارغ.")
            for info in infos:
                n = _safe_archive_path(info.filename)
                if n in seen:
                    raise InvalidBackupError("تحتوي النسخة الاحتياطية على ملفات مكررة.")
                if _zip_is_symlink(info):
                    raise InvalidBackupError("تحتوي النسخة الاحتياطية على رابط غير مسموح.")
                if not (
                    n == "manifest.json" or n == "database/talabiytak.db" or n.startswith("images/")
                ):
                    raise InvalidBackupError("تحتوي النسخة الاحتياطية على ملف غير مسموح.")
                seen.add(n)
            if "manifest.json" not in seen:
                raise InvalidBackupError("ملف manifest.json مفقود.")
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            if (
                manifest.get("format") != BACKUP_FORMAT
                or manifest.get("format_version") != FORMAT_VERSION
            ):
                raise InvalidBackupError("تنسيق النسخة الاحتياطية غير مدعوم.")
            dbp = manifest.get("database_path")
            if dbp != "database/talabiytak.db" or dbp not in seen:
                raise InvalidBackupError("قاعدة البيانات مفقودة من النسخة الاحتياطية.")
            listed = {f["path"]: f for f in manifest.get("files", [])}
            for n in listed:
                _safe_archive_path(n)
            if set(listed) - seen:
                raise InvalidBackupError("النسخة الاحتياطية غير مكتملة؛ توجد ملفات مفقودة.")
            for n, f in listed.items():
                info = z.getinfo(n)
                if info.file_size != f.get("size"):
                    raise InvalidBackupError("حجم ملف داخل النسخة لا يطابق manifest.")
                h = hashlib.sha256()
                with z.open(n) as src:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        h.update(chunk)
                if h.hexdigest() != f.get("sha256"):
                    raise InvalidBackupError("فشل التحقق من checksum للنسخة الاحتياطية.")
            with tempfile.TemporaryDirectory(prefix="talbackup-check-") as td:
                db = Path(td) / "db.sqlite"
                with z.open("database/talabiytak.db") as src, db.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                _db_check(db)
                if verify_images:
                    con = sqlite3.connect(db)
                    try:
                        vals = []
                        for table, col in [
                            ("products", "primary_image"),
                            ("imported_images", "image_asset"),
                        ]:
                            for (raw,) in con.execute(
                                f'SELECT {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != ""'
                            ):
                                try:
                                    vals.append(json.loads(raw).get("file_path"))
                                except Exception:
                                    pass
                        for fp in vals:
                            if not fp:
                                continue
                            n = _safe_archive_path(fp)
                            if not n.startswith("images/") or n not in seen:
                                raise InvalidBackupError(
                                    "النسخة الاحتياطية غير مكتملة؛ توجد صور مفقودة."
                                )
                    finally:
                        con.close()
    except zipfile.BadZipFile as e:
        raise InvalidBackupError("ملف النسخة الاحتياطية تالف أو ليس ZIP صالحًا.") from e
    except json.JSONDecodeError as e:
        raise InvalidBackupError("ملف manifest.json غير صالح.") from e
    digest, _ = sha256_file(path)
    return BackupInspection(manifest, digest)


def _extract_checked(archive, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            n = _safe_archive_path(info.filename)
            if n == "manifest.json":
                continue
            out = dest / n
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def apply_pending_restore(paths):
    marker = paths.temp / "pending-restore.json"
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        archive = Path(data["archive_path"])
        digest, _ = sha256_file(archive)
        if digest != data.get("archive_sha256"):
            raise RestoreError("فشل التحقق من ملف الاستعادة المؤجل.")
        inspect_backup(archive, verify_images=True)
        stage = Path(tempfile.mkdtemp(prefix="restore-apply-", dir=paths.temp))
        _extract_checked(archive, stage)
        recovered = False
        rec = (
            paths.root
            / "recovery"
            / ("pre-restore-" + datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S"))
        )
        rec.mkdir(parents=True, exist_ok=True)
        old_db = paths.database if paths.database.exists() else None
        old_img = paths.images if paths.images.exists() else None
        try:
            if old_db:
                shutil.copy2(old_db, rec / "talabiytak.db")
                recovered = True
            if old_img:
                shutil.copytree(old_img, rec / "images", symlinks=False)
                recovered = True
            paths.database.unlink(missing_ok=True)
            shutil.rmtree(paths.images, ignore_errors=True)
            shutil.move(str(stage / "database" / "talabiytak.db"), str(paths.database))
            if (stage / "images").exists():
                shutil.move(str(stage / "images"), str(paths.images))
            else:
                paths.images.mkdir(parents=True, exist_ok=True)
            _db_check(paths.database)
            marker.unlink(missing_ok=True)
            shutil.rmtree(archive.parent, ignore_errors=True)
            shutil.rmtree(stage, ignore_errors=True)
            if not recovered:
                shutil.rmtree(rec, ignore_errors=True)
            return True
        except Exception:
            paths.database.unlink(missing_ok=True)
            shutil.rmtree(paths.images, ignore_errors=True)
            if (rec / "talabiytak.db").exists():
                shutil.copy2(rec / "talabiytak.db", paths.database)
            if (rec / "images").exists():
                shutil.copytree(rec / "images", paths.images)
            raise
    except Exception:
        log.exception("pending restore failed")
        return False
