@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] Installing optional public data downloader...
python -m pip install datagokr-mcp
if errorlevel 1 (
    echo Installer failed. Please use official public data portal links in README.
    pause
    exit /b 1
)
echo [2/2] Attempting to download and validate 3 public CSV datasets...
python download_official.py
if errorlevel 1 (
    echo Some data were not downloaded. Please open README and download missing files manually.
)
pause
