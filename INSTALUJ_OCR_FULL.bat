@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPY=%BASEDIR%.venv\Scripts\python.exe"
if not exist "%RKPY%" (
  echo Najpierw uruchom INSTALUJ_TRYB_DESKTOP.bat.
  pause
  exit /b 1
)
"%RKPY%" "%BASEDIR%ocr_setup.py" --interactive
pause
