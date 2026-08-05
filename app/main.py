import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.repositories import (
    ImportedImagesRepository,
    ImportsRepository,
    OrdersRepository,
    ProductsRepository,
)
from app.repositories.orphans import OrphanCleanupRepository
from app.routes.orders import router as orders_router
from app.routes.pricing import router as pricing_router
from app.routes.web import router
from app.security.core import Security
from app.services.catalog import CatalogQueryService
from app.services.cleanup import ImportCleanupService
from app.services.errors import AppError
from app.services.excel_export import ExcelExportService
from app.services.excel_pricing import ExcelPricingService
from app.services.image_processing import ImageProcessingService
from app.services.imports import ImportService
from app.services.media import LocalMediaService
from app.services.media_urls import asset_delivery_url
from app.services.orders import OrderService
from app.services.products import ProductService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
BASE = Path(__file__).parent
VERSIONED_ASSETS = ("style.css", "orders.js", "app.js", "desktop_exports.js")


def _asset_version(path: Path) -> str:
    """Return a stable version that changes only when the asset contents change."""
    return sha256(path.read_bytes()).hexdigest()[:12]


ASSET_VERSIONS = {
    filename: _asset_version(BASE / "static" / filename) for filename in VERSIONED_ASSETS
}


def asset_version(filename: str) -> str:
    """Look up an allow-listed, startup-cached static asset version for templates."""
    return ASSET_VERSIONS[filename]


def configure_services(app, database, storage, *, backend: str):
    if backend == "sqlite":
        from app.repositories.sqlite import (
            SQLiteImagesRepository,
            SQLiteImportsRepository,
            SQLiteOrdersRepository,
            SQLiteOrphansRepository,
            SQLiteProductsRepository,
        )

        imports, images = SQLiteImportsRepository(database), SQLiteImagesRepository(database)
        products, orders = SQLiteProductsRepository(database), SQLiteOrdersRepository(database)
        orphans = SQLiteOrphansRepository(database)
    elif backend == "mongo":
        imports, images, products = (
            ImportsRepository(database),
            ImportedImagesRepository(database),
            ProductsRepository(database),
        )
        orders, orphans = OrdersRepository(database), OrphanCleanupRepository(database)
    else:
        raise ValueError(f"unsupported database backend: {backend}")
    processor = ImageProcessingService(app.state.settings)
    app.state.imports = ImportService(
        app.state.settings, processor, storage, imports, images, products, orphans
    )
    app.state.products = ProductService(storage, products, images, orphans, orders=orders)
    app.state.orders = OrderService(app.state.settings, orders, products)
    app.state.excel_export = ExcelExportService(app.state.settings, products, storage)
    app.state.excel_pricing = ExcelPricingService(app.state.settings)
    app.state.cleanup = ImportCleanupService(storage, products, images)
    app.state.catalog = CatalogQueryService(database, imports, images, products, orders)
    app.state.processor = processor
    app.state.repositories = type(
        "Repositories",
        (),
        {
            "imports": imports,
            "images": images,
            "products": products,
            "orders": orders,
            "orphans": orphans,
        },
    )()
    app.state.storage = storage


def create_app(
    settings: Settings | None = None,
    *,
    database=None,
    imagekit_client=None,
    imagekit_upload_transport=None,
    close_injected_database: bool = False,
):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        client = None
        db = database
        owns_database = database is None
        if db is None:
            if settings.desktop_mode:
                from app.database import SQLiteDatabase
                from app.desktop_paths import DesktopPaths

                app.state.paths = DesktopPaths.create(
                    Path(settings.data_dir) if settings.data_dir else None
                )
                db = await SQLiteDatabase(app.state.paths.database).open()
            else:
                from app.database import create_mongo

                client, db = create_mongo(settings)
                await db.command("ping")
        app.state.mongo_client, app.state.database = client, db
        if settings.desktop_mode:
            from app.services.storage import LocalImageStorage

            storage = LocalImageStorage(app.state.paths.images)
            backend = "sqlite"
        else:
            storage = __import__(
                "app.services.storage.imagekit", fromlist=["ImageKitStorage"]
            ).ImageKitStorage(settings, imagekit_client, imagekit_upload_transport)
            backend = "mongo"
        configure_services(app, db, storage, backend=backend)
        if settings.desktop_mode:
            from app.services.desktop_exports import DesktopExportManager

            export_root = (
                getattr(app.state, "paths", None).root / "data" / "temp" / "exports"
                if getattr(app.state, "paths", None)
                else Path(settings.data_dir or ".") / "data" / "temp" / "exports"
            )
            app.state.desktop_exports = getattr(
                app.state, "desktop_exports", None
            ) or DesktopExportManager(export_root)
            try:
                app.state.desktop_exports.cleanup_expired()
                removed = await app.state.repositories.orders.cleanup_expired()
                logging.getLogger(__name__).info("Expired order cleanup removed %s orders", removed)
            except Exception:
                logging.getLogger(__name__).exception("Expired order cleanup failed")
        try:
            yield
        finally:
            if client is not None:
                from app.database import close_mongo

                await close_mongo(client)
            elif (
                settings.desktop_mode
                and db is not None
                and (owns_database or close_injected_database)
            ):
                await db.close()

    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    app.state.security = Security(settings)
    if settings.desktop_mode:
        from app.desktop_paths import resource_path

        template_base = resource_path("app", "templates")
        static_base = resource_path("app", "static")
    else:
        template_base = BASE / "templates"
        static_base = BASE / "static"
    app.state.templates = Jinja2Templates(directory=template_base)
    app.state.templates.env.globals["asset_version"] = asset_version
    app.state.templates.env.globals["asset_delivery_url"] = lambda asset: asset_delivery_url(
        settings, asset
    )
    app.state.templates.env.globals["imagekit_url"] = lambda asset: asset_delivery_url(
        settings, asset
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
    app.mount("/static", StaticFiles(directory=static_base), name="static")
    app.include_router(router)
    app.include_router(orders_router)
    app.include_router(pricing_router)

    if settings.desktop_mode:

        @app.get("/desktop-bootstrap")
        async def desktop_bootstrap(request: Request, token: str):
            expected = getattr(app.state, "bootstrap_token", None)
            expires_at = getattr(app.state, "bootstrap_token_expires_at", None)
            expired = expires_at is not None and time.time() > expires_at
            if expired:
                app.state.bootstrap_token = None
            if not expected or expired or not __import__("hmac").compare_digest(token, expected):
                raise HTTPException(403)
            app.state.bootstrap_token = None
            response = RedirectResponse("/", 303)
            response.set_cookie(
                settings.session_cookie_name,
                app.state.security.new_session(),
                httponly=True,
                samesite="strict",
            )
            return response

        @app.get("/local-media/{asset_id}")
        async def local_media(request: Request, asset_id: str):
            from app.dependencies import session_data

            if not session_data(request):
                raise HTTPException(403)
            try:
                media = await LocalMediaService(
                    app.state.repositories.images,
                    app.state.repositories.products,
                    app.state.storage,
                ).resolve(asset_id)
            except Exception as exc:
                raise HTTPException(404) from exc
            return FileResponse(
                media.path,
                media_type=media.mime_type,
                headers={"Cache-Control": "private, max-age=3600"},
            )

        @app.get("/logs")
        async def logs_folder(request: Request):
            from app.dependencies import session_data

            if not session_data(request):
                raise HTTPException(403)
            return app.state.templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "request": request,
                    "code": "السجلات",
                    "message": "تم حفظ تفاصيل الخطأ في سجل البرنامج.",
                    "session": session_data(request),
                    "logs_path": str(app.state.paths.logs),
                },
            )

    @app.middleware("http")
    async def headers(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id", uuid.uuid4().hex)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "Content-Security-Policy": (
                    f"default-src 'self'; img-src 'self' data: "
                    f"{'' if settings.desktop_mode else settings.imagekit_origin}; style-src 'self'; script-src 'self'; "
                    "frame-ancestors 'none'; form-action 'self'"
                ),
                "X-Request-ID": request.state.request_id,
                "Cache-Control": "no-store",
            }
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"request": request, "code": 400, "message": str(exc), "session": None},
            status_code=400,
        )

    @app.exception_handler(404)
    async def not_found(request, exc):
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "request": request,
                "code": 404,
                "message": "الصفحة المطلوبة غير موجودة",
                "session": None,
            },
            status_code=404,
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logging.getLogger(__name__).exception(
            "unexpected request error request_id=%s",
            request.state.request_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        message = f"حدث خطأ غير متوقع. رقم الطلب: {request.state.request_id}"
        if settings.desktop_mode:
            message += " تم حفظ تفاصيل الخطأ في سجل البرنامج."
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "request": request,
                "code": 500,
                "message": message,
                "session": None,
                "logs_path": str(app.state.paths.logs) if settings.desktop_mode else None,
            },
            status_code=500,
        )

    return app


def _default_app():
    if os.environ.get("TALABIYTAK_DESKTOP_LAUNCH") == "1":
        return None
    try:
        return create_app()
    except Exception:
        logging.getLogger(__name__).info("Default ASGI app deferred until settings are configured")
        return None


app = _default_app()
