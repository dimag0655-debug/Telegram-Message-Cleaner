# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

root = Path(SPECPATH)
# Keep unrelated tools on the developer's PATH from donating incompatible CRT/ICU
# DLLs to the bundle. Windows 10/11 supplies its own Universal CRT and API sets.
windows = Path(os.environ.get('SystemRoot', os.environ.get('SYSTEMROOT', 'C:/Windows')))
os.environ['PATH'] = os.pathsep.join(str(p) for p in (
    windows / 'System32', windows, Path(sys.base_prefix), Path(sys.base_prefix) / 'DLLs',
    Path(sys.prefix) / 'Scripts'))
a = Analysis(
    [str(root / 'main.py')], pathex=[str(root)],
    binaries=[], datas=[], hiddenimports=['telethon.tl.alltlobjects'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtMultimedia', 'pytest'],
    noarchive=False,
)
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.lower().startswith(('api-ms-win-', 'ext-ms-win-'))
              and Path(entry[0]).name.lower() not in ('ucrtbase.dll', 'icuuc.dll', 'icuin.dll', 'icudt.dll')]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='TelegramMessageCleaner', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(root / 'assets' / 'app.ico'),
)
