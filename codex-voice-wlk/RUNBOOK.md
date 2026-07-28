# Codex Voice WLK

Local voice bridge using WhisperLiveKit for STT, Silero VAD for endpointing, Codex CLI for work, and Windows TTS for speech output.

## Start STT

```cmd
start_wlk_faster_whisper.cmd
```

Default server:

```text
backend: faster-whisper
model: large-v3-turbo
input: PCM s16le / 16kHz / mono
ws: ws://127.0.0.1:8000/asr?language=auto&mode=full
```

Stop it:

```cmd
stop_wlk.cmd
```

## Run Bridge

Preview only:

```cmd
run_voice_bridge_preview.cmd
```

One-time mode uses `codex exec` and speaks the final answer:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --speak --codex-mode one-time
```

Interactive mode launches an interactive Codex session with `codex fork --last` and speaks only the handoff status:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --speak --codex-mode interactive
```

Useful overrides:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --codex-bin C:\Users\Admin\AppData\Roaming\npm\codex.cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --codex-sandbox read-only
.venv\Scripts\python.exe voice_bridge.py --submit-codex --codex-sandbox workspace-write
.venv\Scripts\python.exe voice_bridge.py --submit-codex --codex-sandbox danger-full-access
```

## Behavior

- Wake words: `codex`, `code x`, `code ex`, `kodex`.
- After wake, transcript text is captured until Silero VAD sees enough human silence.
- Chinese hold/send/continuation phrases are supported with stable Unicode escapes in code.
- Prompt, answer, and error files are written under `.voice\turns`.
- `--submit-codex` is required before anything is sent to Codex CLI.
- `--speak` says `Sure, request received. Please hold on.` immediately after submission.

## Transcript Test

Run the bridge without microphone input:

```cmd
.venv\Scripts\python.exe voice_bridge.py --transcript-file fixtures\fake-transcript.txt --submit-codex --codex-mode one-time
```

Run the fake-Codex smoke test:

```cmd
python scripts\smoke_bridge.py
```

## Tuning

```cmd
.venv\Scripts\python.exe voice_bridge.py --human-silence-seconds 3.0
.venv\Scripts\python.exe voice_bridge.py --continuation-silence-seconds 8.0
.venv\Scripts\python.exe voice_bridge.py --hold-silence-seconds 15.0
.venv\Scripts\python.exe voice_bridge.py --vad-min-silence-ms 1200
.venv\Scripts\python.exe voice_bridge.py --debug-transcript
```

## Notes

- `ffmpeg` is not required because the server runs with `--pcm-input`.
- Voxtral 4B was removed after testing because it put too much pressure on the 8GB GPU.
- `large-v3-turbo` is downloaded in the HuggingFace cache.
