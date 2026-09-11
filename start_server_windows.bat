@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPY=%BASEDIR%.venv\Scripts\python.exe"
set SPRAWNIK_HOST=0.0.0.0
set SPRAWNIK_OPEN_BROWSER=0
set SPRAWNIK_AUTO_SHUTDOWN=0
if not exist "%RKPY%" (
  echo Brak lokalnego .venv. Uruchom INSTALUJ_TRYB_DESKTOP.bat.
  pause
  exit /b 1
)
"%RKPY%" "%BASEDIR%app.py"
if errorlevel 1 pause
exit /b %errorlevel%
