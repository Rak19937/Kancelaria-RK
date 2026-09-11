@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPY=%BASEDIR%.venv\Scripts\python.exe"
set SPRAWNIK_OPEN_BROWSER=1
set SPRAWNIK_AUTO_SHUTDOWN=1
if not exist "%RKPY%" (
  echo Brak lokalnego .venv. Uruchom INSTALUJ_TRYB_DESKTOP.bat.
  pause
  exit /b 1
)
"%RKPY%" "%BASEDIR%app.py"
exit /b %errorlevel%
