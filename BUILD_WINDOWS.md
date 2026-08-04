# Building on Windows

Requirements on the build machine: Python 3.12 and Inno Setup 6. End users need neither. For development run `pip install -e ".[dev]"` then `powershell -File scripts/run-desktop-dev.ps1`.

Build the one-folder app with `powershell -File scripts/build-desktop.ps1`. Put Microsoft's signed WebView2 Evergreen Standalone x64 installer at the documented prerequisite path, then run:

`powershell -ExecutionPolicy Bypass -File scripts/build-installer.ps1`

The result is `dist-installer/Talabiytak-Setup.exe`. GitHub Actions performs the official download, signature check, tests, lint, both builds, and publishes artifact **Talabiytak-Windows-Installer**. Tags `v*` and manual dispatch are supported. The temporary icon is replaced by overwriting `assets/Talabiytak.ico`.

## Icons

The repository keeps only the text-based placeholder `assets/Talabiytak.svg` so source control does not store generated binary icon files. Before a branded Windows release, place a trusted `assets/Talabiytak.ico` next to the SVG; the PyInstaller spec and Inno Setup script will use it automatically when present.
