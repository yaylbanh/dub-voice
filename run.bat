@echo off
REM Mở giao diện dub-voice bằng venv của dự án review-drama.
setlocal
set PY=%~dp0..\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -m dubvoice gui
