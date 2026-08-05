import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.dependencies import csrf_ok, require_admin, session_data
from app.services.backups import BackupError, BackupService
from app.services.errors import AppError

router = APIRouter(prefix="/backup")
log = logging.getLogger(__name__)


def render(request, name, status_code=200, **context):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name=name,
        context={"request": request, "session": session_data(request), **context},
        status_code=status_code,
    )


def _desktop_admin(request):
    if not request.app.state.settings.desktop_mode:
        return JSONResponse(
            {"ok": False, "message": "هذه الميزة متاحة في النسخة المكتبية فقط."}, 404
        )
    result = require_admin(request)
    return result if isinstance(result, RedirectResponse) else None


def _csrf(request, token):
    if not csrf_ok(request, token):
        raise AppError("رمز الحماية غير صالح، أعد تحميل الصفحة")


@router.get("", response_class=HTMLResponse)
async def backup_page(request: Request):
    if result := _desktop_admin(request):
        return result
    return render(request, "backup.html")


@router.post("/create")
async def create_backup(request: Request):
    if result := _desktop_admin(request):
        return result
    form = await request.form()
    _csrf(request, form.get("csrf_token"))
    try:
        service = BackupService(
            request.app.state.paths, request.app.state.database, request.app.state.desktop_exports
        )
        result = await service.create_backup()
        export = result["export"]
        manifest = result["manifest"]
        return JSONResponse(
            {
                "ok": True,
                "export_token": export.token,
                "suggested_filename": export.suggested_filename,
                "counts": manifest.get("counts", {}),
            }
        )
    except BackupError as exc:
        log.exception("backup creation failed")
        return JSONResponse({"ok": False, "message": str(exc)}, 400)


@router.post("/restore/stage")
async def stage_restore(request: Request):
    if result := _desktop_admin(request):
        return result
    form = await request.form()
    _csrf(request, form.get("csrf_token"))
    path = form.get("path")
    try:
        manifest = BackupService(
            request.app.state.paths, request.app.state.database, request.app.state.desktop_exports
        ).stage_restore(path)
        return JSONResponse(
            {
                "ok": True,
                "message": "تم التحقق من النسخة الاحتياطية.",
                "restart_required": True,
                "backup": {
                    "created_at": manifest.get("created_at"),
                    "app_version": manifest.get("app_version"),
                    "counts": manifest.get("counts", {}),
                },
            }
        )
    except BackupError as exc:
        log.exception("restore staging failed")
        return JSONResponse({"ok": False, "message": str(exc)}, 400)
