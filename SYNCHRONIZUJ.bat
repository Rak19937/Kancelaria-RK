@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPY=%BASEDIR%.venv\Scripts\python.exe"
if exist "%RKPY%" goto run
where py >nul 2>nul && set "RKPY=py -3" && goto run
where python >nul 2>nul && set "RKPY=python" && goto run
echo Brak Pythona. Najpierw uruchom INSTALUJ_PELNA_WERSJE.bat.
pause
exit /b 2
:run
%RKPY% "%BASEDIR%rk_sync.py" --gui
exit /b %errorlevel%
