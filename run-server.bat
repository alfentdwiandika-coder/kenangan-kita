@echo off
cd /d "%~dp0"
echo ============================================
echo   Kenangan Kita — Video Generator
echo ============================================
echo.
echo Menjalankan server di http://localhost:8000
echo Tekan Ctrl+C untuk stop.
echo.
start "" "http://localhost:8000"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
