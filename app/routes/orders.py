import math
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.dependencies import csrf_ok, require_admin, session_data
from app.services.desktop_exports import MIME_XLSX
from app.services.errors import AppError, ValidationError
from app.services.excel_export import safe_excel_filename
from app.services.media_urls import asset_delivery_url

router = APIRouter(prefix="/orders")


def render(request, name, status_code=200, **context):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name=name,
        context={"request": request, "session": session_data(request), **context},
        status_code=status_code,
    )


def guard(request):
    return require_admin(request)


def check(request, token):
    if not csrf_ok(request, token):
        raise AppError("رمز الحماية غير صالح، أعد تحميل الصفحة")


async def submitted(request):
    form = await request.form()
    check(request, form.get("csrf_token"))
    return form.get("title", ""), form.getlist("product_id"), form.getlist("quantity")


@router.get("", response_class=HTMLResponse)
async def order_list(request: Request, page: int = 1):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    orders = await request.app.state.orders.list_active(max(page, 1), 24)
    total = await request.app.state.repositories.orders.count_active()
    return render(
        request, "orders.html", orders=orders, page=page, pages=max(1, math.ceil(total / 24))
    )


@router.get("/new", response_class=HTMLResponse)
async def order_new(request: Request):
    result = guard(request)
    return (
        result
        if isinstance(result, RedirectResponse)
        else render(request, "order_form.html", order=None)
    )


@router.post("/new")
async def order_create(request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    title, ids, quantities = await submitted(request)
    try:
        order = await request.app.state.orders.create(title, ids, quantities)
    except AppError as exc:
        return render(request, "order_form.html", 400, order=None, error=str(exc))
    suffix = "?save_excel=1" if request.app.state.settings.desktop_mode else ""
    return RedirectResponse(f"/orders/{order.id}{suffix}", 303)


@router.get("/product-search")
async def product_search(request: Request, q: str = "", page: int = 1):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    products, total = await request.app.state.products.search(q, max(page, 1), 12)
    return JSONResponse(
        {
            "items": [
                {
                    "id": p.id,
                    "name": p.name,
                    "image_url": asset_delivery_url(request.app.state.settings, p.primary_image),
                }
                for p in products
            ],
            "total": total,
        }
    )


async def active_or_error(request, order_id):
    try:
        return await request.app.state.orders.get_active(order_id)
    except ValidationError:
        return None


@router.get("/{order_id}", response_class=HTMLResponse)
async def order_detail(order_id: str, request: Request, save_excel: int = 0):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    order = await active_or_error(request, order_id)
    if not order:
        return render(
            request, "error.html", 404, code=404, message="الطلبية غير موجودة أو تم حذفها."
        )
    products = {
        item.product_id: await request.app.state.products.get(item.product_id)
        for item in order.items
    }
    return render(
        request, "order_detail.html", order=order, products=products, save_excel=save_excel
    )


@router.get("/{order_id}/edit", response_class=HTMLResponse)
async def order_edit(order_id: str, request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    order = await active_or_error(request, order_id)
    return (
        render(request, "order_form.html", order=order)
        if order
        else render(request, "error.html", 404, code=404, message="الطلبية غير موجودة أو تم حذفها.")
    )


@router.post("/{order_id}/edit")
async def order_update(order_id: str, request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    title, ids, quantities = await submitted(request)
    try:
        order = await request.app.state.orders.update(order_id, title, ids, quantities)
    except AppError as exc:
        existing = await active_or_error(request, order_id)
        return render(
            request,
            "order_form.html" if existing else "error.html",
            400 if existing else 404,
            order=existing,
            error=str(exc),
            code=404,
            message=str(exc),
        )
    return RedirectResponse(f"/orders/{order.id}", 303)


@router.post("/{order_id}/delete")
async def order_delete(order_id: str, request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    form = await request.form()
    check(request, form.get("csrf_token"))
    try:
        await request.app.state.orders.delete(order_id)
    except ValidationError:
        pass
    return RedirectResponse("/orders", 303)


@router.post("/{order_id}/prepare-export")
async def prepare_order_export(order_id: str, request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    form = await request.form()
    check(request, form.get("csrf_token"))
    order = await active_or_error(request, order_id)
    if not order:
        return JSONResponse({"ok": False, "message": "الطلبية غير موجودة أو تم حذفها."}, 404)
    data = await request.app.state.excel_export.build(order)
    filename = safe_excel_filename(order.title)
    if request.app.state.settings.desktop_mode:
        export = request.app.state.desktop_exports.register(data, filename, MIME_XLSX)
        return JSONResponse(
            {"ok": True, "export_token": export.token, "suggested_filename": filename}
        )
    return JSONResponse({"ok": True, "download_url": f"/orders/{order_id}/download"})


@router.get("/{order_id}/download")
async def order_download(order_id: str, request: Request):
    if isinstance(result := guard(request), RedirectResponse):
        return result
    order = await active_or_error(request, order_id)
    if not order:
        return render(
            request, "error.html", 404, code=404, message="الطلبية غير موجودة أو تم حذفها."
        )
    if request.app.state.settings.desktop_mode:
        return render(
            request,
            "error.html",
            400,
            code=400,
            message="استخدم زر حفظ ملف Excel داخل التطبيق.",
        )
    data = await request.app.state.excel_export.build(order)
    filename = safe_excel_filename(order.title)
    fallback = "order.xlsx"
    disposition = f"attachment; filename={fallback}; filename*=UTF-8''{quote(filename)}"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )
