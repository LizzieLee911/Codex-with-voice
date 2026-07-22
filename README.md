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
- Spoken final result after Codex finishes.
- Tray mode: hide the window while the listener keeps running.
- Permission slider: `read-only`, `workspace-write`, or `danger-full-access`.
- Session mode: resume the last Codex session by default, or start a new session for each voice request.

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
3. Leave `New session` off to resume the latest Codex session, or turn it on for a fresh session each time.
4. Click `Start`.
5. Say "codex", then speak your request.
6. Wait for the spoken acknowledgement.
7. Codex runs in the background and speaks the result.

Minimize or close the window to hide it to the tray. Use the tray menu to show, start, stop, or quit.

## Notes

- This is a Windows-first prototype.
- Local speech-to-text starts before wake-word detection, so idle resource use is not minimal yet.
- Voice output uses installed system voices, so quality and language support depend on the machine.
- The default speech-to-text model is `large-v3-turbo`; use a smaller WhisperLiveKit model on memory-constrained machines.
