@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer, x64, and add it to PATH.
  exit /b 1
)
python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ is required'"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean TelegramMessageCleaner.spec
if errorlevel 1 exit /b 1
start /wait "" "dist\TelegramMessageCleaner.exe" --self-test "build\packaged-smoke"
if errorlevel 1 exit /b 1
if not exist "build\packaged-smoke\self-test.json" exit /b 1
echo Built and smoke-tested dist\TelegramMessageCleaner.exe
endlocal
