$ErrorActionPreference='Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root
python -m pip install -e '.[desktop]'
python -m PyInstaller --noconfirm --clean Talabiytak.spec
& (Join-Path $root 'dist/Talabiytak/Talabiytak.exe') --smoke-test
