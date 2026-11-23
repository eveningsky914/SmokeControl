@echo off
cd /d "%~dp0"
echo [1/2] Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installation failed. Please check Python and Internet connection.
    pause
    exit /b 1
)
echo [2/2] Starting the Streamlit dashboard...
python -m streamlit run app.py
pause
