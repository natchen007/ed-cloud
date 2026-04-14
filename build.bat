@echo off
REM build.bat — Compile EDCloud.exe avec PyInstaller
REM Requis : Python 3.10+, pip install -r requirements.txt, pip install pyinstaller

echo === EDCloud Builder ===

REM Aller dans le dossier du script
cd /d "%~dp0"

REM Verifier PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller non trouve. Installation...
    pip install pyinstaller
)

REM Build
python -m PyInstaller EDCloud.spec --distpath dist --noconfirm

if errorlevel 1 (
    echo.
    echo ERREUR : le build a echoue.
    pause
    exit /b 1
)

echo.
echo === Build termine : dist\EDCloud.exe ===
pause
