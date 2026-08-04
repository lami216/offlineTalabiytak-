param(
  [switch]$SkipDownload,
  [switch]$Release
)
$ErrorActionPreference='Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python 3.12 is required on the build machine.' }
$version = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($version -ne '3.12') { throw "Python 3.12 is required; found $version" }

python -m pip install -e '.[desktop,dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
git diff --check
python -m PyInstaller --noconfirm --clean Talabiytak.spec
& (Join-Path $root 'dist/Talabiytak/Talabiytak.exe') --smoke-test

$prereqDir = Join-Path $root 'installer/prerequisites'
New-Item -ItemType Directory -Force $prereqDir | Out-Null
$webview = Join-Path $prereqDir 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
if (-not $SkipDownload -or -not (Test-Path $webview)) {
  Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $webview
}
$signature = Get-AuthenticodeSignature $webview
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
  throw 'Invalid WebView2 Runtime Authenticode signature.'
}

$publisher = python -c "from app.desktop_config import PUBLISHER; print(PUBLISHER)"
if ($Release -and $publisher -eq 'PLACEHOLDER_PUBLISHER') { throw 'Release build requires a real publisher.' }
if ($Release -and -not (Test-Path 'assets/Talabiytak.ico')) { throw 'Release build requires assets/Talabiytak.ico.' }

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
  $candidate = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  if (Test-Path $candidate) { $iscc = $candidate } else { throw 'Inno Setup 6 (ISCC.exe) is required.' }
}
& $iscc installer\Talabiytak.iss
$installer = Join-Path $root 'dist-installer/Talabiytak-Setup.exe'
if (-not (Test-Path $installer) -or ((Get-Item $installer).Length -le 0)) { throw 'Installer was not created.' }
$sha = (Get-FileHash $installer -Algorithm SHA256).Hash
$sha | Set-Content "$installer.sha256" -Encoding ascii
"Installer=$installer`nSize=$((Get-Item $installer).Length)`nSHA256=$sha" | Set-Content (Join-Path $root 'dist-installer/BUILD_REPORT.txt') -Encoding utf8
Write-Host "Installer: $installer"
Write-Host "Size: $((Get-Item $installer).Length) bytes"
Write-Host "SHA256: $sha"
