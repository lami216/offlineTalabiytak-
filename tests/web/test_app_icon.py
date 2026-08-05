from io import BytesIO
from pathlib import Path, PureWindowsPath

from PIL import Image

from app.desktop_config import DISPLAY_NAME
from app.main import app_icon_source_path


def test_app_icon_source_path_points_to_valid_png():
    source = app_icon_source_path()

    assert source.is_file()
    assert source.name == "Talabiytak-icon.png"
    with Image.open(source) as image:
        assert image.format == "PNG"


def test_app_icon_endpoint_renders_allowed_sizes(setup):
    client, *_ = setup

    for size in (32, 192):
        response = client.get(f"/app-icon/{size}.png")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content
        with Image.open(BytesIO(response.content)) as image:
            assert image.format == "PNG"
            assert image.size == (size, size)


def test_base_template_uses_same_origin_header_icon():
    template = Path("app/templates/base.html").read_text(encoding="utf-8")

    assert 'class="brand-icon"' in template
    assert "/app-icon/192.png" in template
    assert DISPLAY_NAME in template or "app_display_name" in template
    assert "file://" not in template
    assert str(PureWindowsPath("C:/")) not in template
    assert "\\assets\\" not in template
