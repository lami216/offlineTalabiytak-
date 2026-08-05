$ErrorActionPreference='Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root
if (-not (Test-Path "assets/Talabiytak-icon.png")) { throw "Missing assets/Talabiytak-icon.png" }
python scripts/build_icon.py
if (-not (Test-Path "build-assets/Talabiytak.ico")) { throw "Icon build failed: build-assets/Talabiytak.ico missing" }
python -m pip install -e '.[desktop]'
python -m PyInstaller --noconfirm --clean Talabiytak.spec
& (Join-Path $root 'dist/Talabiytak/Talabiytak.exe') --smoke-test
