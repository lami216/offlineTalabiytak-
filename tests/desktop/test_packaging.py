import json
import socket
from pathlib import Path

from PIL import Image

from app.desktop_config import APP_ID, DISPLAY_NAME, EXECUTABLE_NAME, PUBLISHER, VERSION
from desktop_launcher import reserved_loopback_socket


def test_reserved_loopback_socket_binds_only_localhost():
    sock = reserved_loopback_socket()
    try:
        host, port = sock.getsockname()
        assert host == "127.0.0.1"
        assert port > 0
        with socket.socket() as other:
            try:
                other.bind(("127.0.0.1", port))
            except OSError:
                pass
            else:
                raise AssertionError("port was not reserved")
    finally:
        sock.close()


def test_branding_name_and_icon_configuration_are_stable():
    assert DISPLAY_NAME == "طلبياتك"
    assert EXECUTABLE_NAME == "Talabiytak.exe"
    assert APP_ID == "com.talabiytak.desktop"
    assert 'icon_path = "build-assets/Talabiytak.ico"' in Path("Talabiytak.spec").read_text()
    installer = Path("installer/Talabiytak.iss").read_text(encoding="utf-8")
    assert '#define AppName "طلبياتك"' in installer
    assert "UninstallDisplayIcon={app}\\Talabiytak.exe" in installer


def test_icon_source_is_valid_square_png():
    source = Path("assets/Talabiytak-icon.png")
    assert source.is_file()
    with Image.open(source) as image:
        assert image.format == "PNG"
        assert image.width == image.height
        assert image.width >= 512


def test_arabic_desktop_metadata_json_is_ascii_and_round_trips():
    payload = json.dumps(
        {
            "display_name": DISPLAY_NAME,
            "publisher": PUBLISHER,
            "version": VERSION,
        },
        ensure_ascii=True,
    )

    assert DISPLAY_NAME not in payload
    assert "\\u0637\\u0644" in payload

    metadata = json.loads(payload)

    assert metadata["display_name"] == "طلبياتك"
    assert metadata["display_name"] == DISPLAY_NAME
    assert metadata["publisher"] == PUBLISHER
    assert metadata["version"] == VERSION


def test_installer_script_preserves_arabic_metadata_and_utf8_build_report():
    script = Path("scripts/build-installer.ps1").read_text(encoding="utf-8")
    assert "ensure_ascii=True" in script
    assert "ConvertFrom-Json" in script
    assert 'if ($appName -ne "طلبياتك")' in script
    assert '"/DAppName=$appName"' in script
    build_report = "dist-installer/BUILD_REPORT.txt') -Encoding utf8"
    assert build_report in script
