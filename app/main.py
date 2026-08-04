import logging
import os
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
from app.database import SQLiteDatabase, close_mongo, create_mongo
from app.desktop_paths import DesktopPaths, resource_path
from app.repositories import (
    ImportedImagesRepository,
    ImportsRepository,
    OrdersRepository,
    ProductsRepository,
)
from app.repositories.orphans import OrphanCleanupRepository
from app.repositories.sqlite import (
    SQLiteImagesRepository,
    SQLiteImportsRepository,
    SQLiteOrdersRepository,
    SQLiteOrphansRepository,
    SQLiteProductsRepository,
)
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
from app.services.orders import OrderService
from app.services.products import ProductService
from app.services.storage import ImageKitStorage, LocalImageStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
BASE = Path(__file__).parent
VERSIONED_ASSETS = ("style.css", "orders.js", "app.js")


def _asset_version(path: Path) -> str:
    """Return a stable version that changes only when the asset contents change."""
    return sha256(path.read_bytes()).hexdigest()[:12]


ASSET_VERSIONS = {
    filename: _asset_version(BASE / "static" / filename) for filename in VERSIONED_ASSETS
}


def asset_version(filename: str) -> str:
    """Look up an allow-listed, startup-cached static asset version for templates."""
    return ASSET_VERSIONS[filename]


def configure_services(app, database, storage):
    if isinstance(database, SQLiteDatabase):
        imports, images = SQLiteImportsRepository(database), SQLiteImagesRepository(database)
        products, orders = SQLiteProductsRepository(database), SQLiteOrdersRepository(database)
        orphans = SQLiteOrphansRepository(database)
    else:
        imports, images, products = (
            ImportsRepository(database),
            ImportedImagesRepository(database),
            ProductsRepository(database),
        )
        orders, orphans = OrdersRepository(database), OrphanCleanupRepository(database)
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
):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        client = None
        db = database
        if db is None:
            if settings.desktop_mode:
                app.state.paths = DesktopPaths.create(
                    Path(settings.data_dir) if settings.data_dir else None
                )
                db = await SQLiteDatabase(app.state.paths.database).open()
            else:
                client, db = create_mongo(settings)
                await db.command("ping")
        app.state.mongo_client, app.state.database = client, db
        configure_services(
            app,
            db,
            LocalImageStorage(app.state.paths.images)
            if settings.desktop_mode
            else ImageKitStorage(settings, imagekit_client, imagekit_upload_transport),
        )
        if settings.desktop_mode:
            try:
                removed = await app.state.repositories.orders.cleanup_expired()
                logging.getLogger(__name__).info("Expired order cleanup removed %s orders", removed)
            except Exception:
                logging.getLogger(__name__).exception("Expired order cleanup failed")
        try:
            yield
        finally:
            if client is not None:
                await close_mongo(client)
            elif isinstance(db, SQLiteDatabase):
                await db.close()

    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    app.state.security = Security(settings)
    template_base = (
        resource_path("app", "templates") if settings.desktop_mode else BASE / "templates"
    )
    static_base = resource_path("app", "static") if settings.desktop_mode else BASE / "static"
    app.state.templates = Jinja2Templates(directory=template_base)
    app.state.templates.env.globals["asset_version"] = asset_version
    app.state.templates.env.globals["imagekit_url"] = lambda asset: (
        asset.url
        if settings.desktop_mode and asset
        else settings.imagekit_delivery_url(asset.file_path)
        if asset
        else None
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
            if not expected or not __import__("hmac").compare_digest(token, expected):
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
        async def local_media(asset_id: str):
            if len(asset_id) != 64 or any(c not in "0123456789abcdef" for c in asset_id):
                raise HTTPException(404)
            row = await app.state.database.connection.execute(
                "SELECT image_asset FROM imported_images WHERE json_extract(image_asset,'$.file_id')=? UNION SELECT primary_image FROM products WHERE json_extract(primary_image,'$.file_id')=? LIMIT 1",
                (asset_id, asset_id),
            )
            record = await row.fetchone() if row else None
            if not record:
                raise HTTPException(404)
            meta = __import__("json").loads(record[0])
            path = app.state.storage._resolve(meta["file_path"])
            return FileResponse(
                path,
                media_type=meta["mime_type"],
                headers={"Cache-Control": "private, max-age=3600"},
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
            "unexpected request error", extra={"request_id": request.state.request_id}
        )
        return app.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "request": request,
                "code": 500,
                "message": f"حدث خطأ غير متوقع. رقم الطلب: {request.state.request_id}",
                "session": None,
            },
            status_code=500,
        )

    return app


app = None if os.environ.get("TALABIYTAK_DESKTOP_LAUNCH") == "1" else create_app()
