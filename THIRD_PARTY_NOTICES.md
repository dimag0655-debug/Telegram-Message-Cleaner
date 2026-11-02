# Third-party components

The executable bundles Python, Telethon, rsa, pyasn1, pyaes, PySide6/Shiboken6,
Qt Core/Gui/Widgets/Network and their required runtime components. PyInstaller
provides the executable bootloader. Runtime libraries remain dynamically loaded
from the application's temporary extraction directory.

`licenses/` contains license files copied from the installed Python distributions,
plus upstream Qt and Python license texts where available. These files are
upstream materials and do not replace the applicable terms of each component.

Upstream projects and source:

- Python: https://github.com/python/cpython
- Telethon: https://github.com/LonamiWebs/Telethon
- python-rsa: https://github.com/sybrenstuvel/python-rsa
- pyasn1: https://github.com/pyasn1/pyasn1
- pyaes: https://github.com/ricmoo/pyaes
- Qt for Python / Shiboken: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt: https://code.qt.io/cgit/qt/qtbase.git/
- Qt licensing information: https://doc.qt.io/qt-6/licensing.html
- PyInstaller: https://github.com/pyinstaller/pyinstaller (bootloader exception)

The full application source and PyInstaller build specification are supplied.
The application does not require cryptg, hachoir, Pillow, aiohttp or SOCKS proxy
packages for its implemented functionality.
