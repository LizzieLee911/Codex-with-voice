@echo off
setlocal
cd /d "%~dp0WhisperLiveKit"
"%~dp0.venv\Scripts\wlk.exe" serve --backend faster-whisper --model large-v3-turbo --lan auto --pcm-input --host 127.0.0.1 --port 8000 --warmup-file=
