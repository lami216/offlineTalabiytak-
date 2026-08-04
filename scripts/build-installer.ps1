$ErrorActionPreference='Stop'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.12 is required on the build machine.' }
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
& "$PSScriptRoot/build-desktop.ps1"
$iscc=(Get-Command ISCC.exe -ErrorAction SilentlyContinue)
if (-not $iscc) { $candidate="$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"; if(Test-Path $candidate){$iscc=$candidate}else{throw 'Inno Setup 6 (ISCC.exe) is required.'} }
& $iscc installer\Talabiytak.iss
Write-Host "Installer: $PWD\dist-installer\Talabiytak-Setup.exe"
