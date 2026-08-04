from pathlib import Path
from PyInstaller.utils.hooks import collect_all
hiddenimports=[]
for package in ('webview','uvicorn','fastapi','aiosqlite','openpyxl','PIL'):
    _, binaries, imports = collect_all(package); hiddenimports += imports

a=Analysis(['desktop_launcher.py'], pathex=[], binaries=[], datas=[('app/templates','app/templates'),('app/static','app/static'),('assets','assets')], hiddenimports=hiddenimports)
pyz=PYZ(a.pure)
icon_path = 'assets/Talabiytak.ico' if Path('assets/Talabiytak.ico').exists() else None
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Talabiytak',console=False,icon=icon_path)
coll=COLLECT(exe,a.binaries,a.datas,name='Talabiytak')
