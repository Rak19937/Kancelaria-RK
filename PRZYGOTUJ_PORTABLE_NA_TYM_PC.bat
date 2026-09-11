@echo off
setlocal EnableExtensions
chcp 65001 >nul
title RK KANCELARIA 0.2 Portable - przygotowanie
set "BASEDIR=%~dp0"
if not exist "%BASEDIR%portable.flag" (
  echo BLAD: Ta paczka nie jest oznaczona jako Portable.
  pause
  exit /b 2
)
call "%BASEDIR%INSTALUJ_PELNA_WERSJE.bat"
exit /b %errorlevel%
