@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Apply-AccelaPreset.ps1" >nul

if not exist "%~dp0ACCELA.exe" (
  echo ACCELA.exe nao encontrado nesta pasta.
  pause
  exit /b 1
)

start "" "%~dp0ACCELA.exe"
exit /b 0
