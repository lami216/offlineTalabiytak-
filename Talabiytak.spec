from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hiddenimports = []
for package in ("webview", "uvicorn", "fastapi", "aiosqlite", "openpyxl", "PIL"):
    hiddenimports.extend(collect_submodules(package))

datas = [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
    ("assets", "assets"),
]
datas.extend(collect_data_files("webview"))
datas.extend(collect_data_files("openpyxl"))

icon_path = "build-assets/Talabiytak.ico"

a = Analysis(
    ["desktop_launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pymongo", "bson", "imagekitio"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Talabiytak", console=False, icon=icon_path
)
coll = COLLECT(exe, a.binaries, a.datas, name="Talabiytak")
