@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPY=%BASEDIR%.venv\Scripts\python.exe"
if not exist "%RKPY%" (
  echo Brak lokalnego .venv. Najpierw uruchom INSTALUJ_TRYB_DESKTOP.bat.
  pause
  exit /b 1
)
"%RKPY%" "%BASEDIR%utworz_skrot.py"
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" echo GOTOWE: skrot utworzony.
pause
exit /b %RC%
