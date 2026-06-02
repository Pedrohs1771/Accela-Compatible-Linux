@echo off
setlocal
set "ROOT=%~dp0"

if exist "%ROOT%.venv\Scripts\pythonw.exe" (
  "%ROOT%.venv\Scripts\pythonw.exe" "%ROOT%bin\src\main.py" %*
  exit /b %ERRORLEVEL%
)

if exist "%ROOT%.venv\Scripts\python.exe" (
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%bin\src\main.py" %*
  exit /b %ERRORLEVEL%
)

echo [LumaTools] Python environment not found in "%ROOT%.venv"
exit /b 1
