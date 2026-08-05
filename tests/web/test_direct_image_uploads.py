from io import BytesIO

from PIL import Image

from app.services.imports import MAX_IMAGE_UPLOAD_BYTES


def image_bytes(fmt="PNG", color="red"):
    out = BytesIO()
    with Image.new("RGB", (8, 8), color) as image:
        image.save(out, fmt)
    return out.getvalue()


def test_direct_png_upload_creates_batch(auth):
    client, app, fake, tmp, token, database = auth
    data = image_bytes("PNG")
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files={"images": ("product.png", data, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch_id = response.headers["location"].rsplit("/", 1)[-1]
    images = list(
        database.raw.imported_images.find({"import_id": database.raw.imports.find_one()["_id"]})
    )
    assert len(images) == 1
    assert images[0]["status"] == "unnamed"
    assert images[0]["original_media_name"] == "product.png"
    assert fake.files.uploads[0]["file"] == data
    assert batch_id


def test_direct_multiple_uploads_preserve_order_and_duplicates(auth):
    client, app, fake, tmp, token, database = auth
    first = image_bytes("PNG", "red")
    second = image_bytes("JPEG", "blue")
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files=[
            ("images", ("a.png", first, "image/png")),
            ("images", ("b.jpg", second, "image/jpeg")),
            ("images", ("again.png", first, "image/png")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    rows = list(database.raw.imported_images.find().sort("sequence_number", 1))
    assert [row["original_media_name"] for row in rows] == ["a.png", "b.jpg", "again.png"]
    assert [row["status"] for row in rows] == ["unnamed", "unnamed", "duplicate"]
    assert len(fake.files.uploads) == 2


def test_direct_invalid_and_oversized_images_are_reported(auth):
    client, app, fake, tmp, token, database = auth
    ok = image_bytes("WEBP", "green")
    too_big = b"x" * (MAX_IMAGE_UPLOAD_BYTES + 1)
    response = client.post(
        "/imports/new",
        data={"csrf_token": token},
        files=[
            ("images", ("ok.webp", ok, "image/webp")),
            ("images", ("fake.jpg", b"not image", "image/jpeg")),
            ("images", ("huge.png", too_big, "image/png")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch = database.raw.imports.find_one()
    rows = list(database.raw.imported_images.find().sort("sequence_number", 1))
    assert batch["counters"]["valid_images"] == 1
    assert batch["counters"]["failed_images"] == 2
    assert rows[0]["status"] == "unnamed"
    assert "ليس صورة صالحة" in rows[1]["error_message"]
    assert "10 ميغابايت" in rows[2]["error_message"]


def test_import_requires_excel_or_image(auth):
    client, app, fake, tmp, token, database = auth
    response = client.post("/imports/new", data={"csrf_token": token})
    assert response.status_code == 400
    assert "اختر ملف Excel أو صورة واحدة على الأقل." in response.text


def test_upload_without_csrf_rejected(auth):
    client, app, fake, tmp, token, database = auth
    response = client.post(
        "/imports/new",
        files={"images": ("product.png", image_bytes("PNG"), "image/png")},
    )
    assert response.status_code in {400, 422}
