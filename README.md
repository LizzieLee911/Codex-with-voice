# Codex with Voice

Codex with Voice is a local desktop companion, not a built-in Codex feature: say "codex", speak your request, let Codex CLI work, and hear the result.

<img src="assets/codex-voice-companion.png" alt="Codex Voice Companion desktop app" width="60%">

## Why

Codex is powerful, but it is still mostly keyboard-first. This project adds a lightweight voice layer around Codex CLI without modifying the closed-source Codex desktop app.

## Features

- Wake word: say "codex" before each request.
- Local speech-to-text through WhisperLiveKit.
- Silero VAD endpointing, so pauses feel more natural than a fixed timer.
- Spoken acknowledgement before Codex starts working.
- Spoken final result in `One-time` mode; spoken handoff status in `Interactive` mode.
- Tray mode: hide the window while the listener keeps running.
- Permission slider: `read-only`, `workspace-write`, or `danger-full-access`.
- Codex mode slider: `One-time` uses `codex exec` and speaks the final result; `Interactive` launches `codex fork --last` so the task can continue in Codex.
- Multilingual output: uses the detected request language when choosing a local system voice, then falls back to English.

## Quick Start

Requirements:

- Windows 10 or Windows 11.
- Node.js and npm.
- Python 3.11.
- Git.
- A working microphone.
- Codex CLI installed and logged in.
- Optional: NVIDIA GPU with CUDA for faster local speech-to-text.

Clone the repo:

```cmd
git clone https://github.com/LizzieLee911/Codex-with-voice.git
cd Codex-with-voice
```

Install the voice engine:

```cmd
cd codex-voice-wlk
git clone https://github.com/QuentinFuxa/WhisperLiveKit.git
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".\WhisperLiveKit[listen]"
```

Install and start the desktop app:

```cmd
cd ..\codex-voice-desktop
npm install
npm start
```

## Use It

1. Open the app.
2. Choose the permission mode.
3. Choose `One-time` for quick spoken tasks, or `Interactive` when you want to continue in Codex.
4. Click `Start`.
5. Say "codex", then speak your request.
6. Wait for the spoken acknowledgement.
7. In `One-time`, Codex runs in the background and speaks the result. In `Interactive`, Codex opens an interactive task and the app speaks the handoff status.

Minimize or close the window to hide it to the tray. Use the tray menu to show, start, stop, or quit.

## Notes

- This is a Windows-first prototype.
- Local speech-to-text starts before wake-word detection, so idle resource use is not minimal yet.
- Voice output uses installed system voices, so quality and language support depend on the machine. If no matching voice is installed, it falls back to English.
- The default speech-to-text model is `large-v3-turbo`; use a smaller WhisperLiveKit model on memory-constrained machines.
- Bridge-only smoke test: `cd codex-voice-desktop && npm run smoke:bridge`.
