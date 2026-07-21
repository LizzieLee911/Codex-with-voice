@echo off
setlocal
set PID_FILE=%~dp0wlk_faster_whisper.pid
if not exist "%PID_FILE%" (
  set PID_FILE=%~dp0wlk_voxtral.pid
)
if not exist "%PID_FILE%" (
  echo No WLK pid file found.
  exit /b 0
)
for /f %%p in (%PID_FILE%) do (
  taskkill /PID %%p /T /F
)
