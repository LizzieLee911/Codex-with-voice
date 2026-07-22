# Codex Voice WLK

Local voice bridge using WhisperLiveKit as STT and Codex CLI as the text agent.

## Start STT server

Default lightweight local server:

```cmd
start_wlk_faster_whisper.cmd
```

This starts:

```text
backend: faster-whisper
model: large-v3-turbo
input: PCM s16le / 16kHz / mono
```

The server listens on:

```text
http://127.0.0.1:8000
ws://127.0.0.1:8000/asr?language=auto&mode=full
```

Stop the background server started by Codex setup:

```cmd
stop_wlk.cmd
```

## Run bridge

Preview mode only writes prompt files and prints the captured text:

```cmd
run_voice_bridge_preview.cmd
```

Codex mode sends the final prompt to the latest Codex CLI session and speaks the final answer:

```cmd
run_voice_bridge_codex.cmd
```

To lock to one exact Codex CLI session:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --speak --codex-session-id YOUR_SESSION_ID
```

On Windows the bridge prefers `codex.cmd` for CLI submission. Override the executable if needed:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --codex-bin C:\Users\Admin\AppData\Roaming\npm\codex.cmd
```

By default the bridge tries `codex exec resume --last`. If that local resume target is broken, it logs the failure to `.voice\turns\*.codex_error.txt` and falls back to a fresh `codex exec` for the same saved prompt. Successful runs keep Codex's internal warnings in the same log file instead of flooding the voice window. Disable fallback when you only want a specific session:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --no-codex-fallback-new-session
```

To skip `resume --last` and start a fresh Codex session for every captured voice request:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --speak --codex-new-session
```

## Behavior

- Wake words: `codex`, `code x`, `code ex`, `kodex`
- After wake word, the bridge keeps collecting later transcript text even when later chunks do not repeat the wake word.
- Silero VAD continuously tracks human speech, then endpointing waits for post-wake human-speech absence.
- Old server-side silence segments before wake are ignored.
- It waits at least 1.2 seconds after wake before accepting a turn end.
- Default endpoint waits for 2.5 seconds without human speech.
- If the transcript ends like `emmm`, `嗯`, `呃`, `然后`, or `就是`, it waits 6 seconds.
- If the transcript includes `等一下`, `我想一下`, or `let me think`, it waits 12 seconds.
- If the transcript includes `发吧`, `就这样`, or `send now`, it finalizes quickly.
- It only saves a prompt after a non-empty body is captured after wake.
- It finalizes after no audio/text activity as a fallback, but never faster than the current dynamic human-silence wait.
- It writes files under `.voice\turns`.
- `--submit-codex` is required before anything is sent to Codex CLI.
- Default Codex session behavior is `resume --last`; `--codex-new-session` starts each voice request in a fresh Codex session.
- Submitted Codex requests append an English output-style instruction: default to English, no code, file paths, Markdown links, or logs; report progress and results in plain English.
- Codex sandbox defaults to `danger-full-access`. Override it with `--codex-sandbox read-only`, `--codex-sandbox workspace-write`, or `--codex-sandbox danger-full-access`.
- `--speak` uses Windows local TTS. When a prompt is submitted, it immediately says `Sure, request received. Please hold on.` before Codex finishes; override with `--ack-text`.
- `--debug-transcript` prints live transcript updates; by default only key events and the final prompt are printed.

## Useful tuning

```cmd
.venv\Scripts\python.exe voice_bridge.py --silence-seconds 2.0
.venv\Scripts\python.exe voice_bridge.py --rms-threshold 500
.venv\Scripts\python.exe voice_bridge.py --wake-word codex --wake-word assistant
.venv\Scripts\python.exe voice_bridge.py --vad-min-silence-ms 1200
.venv\Scripts\python.exe voice_bridge.py --post-wake-grace-seconds 1.8
.venv\Scripts\python.exe voice_bridge.py --text-settle-seconds 1.0
.venv\Scripts\python.exe voice_bridge.py --human-silence-seconds 3.0
.venv\Scripts\python.exe voice_bridge.py --continuation-silence-seconds 8.0
.venv\Scripts\python.exe voice_bridge.py --hold-silence-seconds 15.0
.venv\Scripts\python.exe voice_bridge.py --debug-transcript
```

## Notes

- `ffmpeg` is not required for this path because the server is started with `--pcm-input`.
- Voxtral 4B was removed after testing because it put too much pressure on the 8GB GPU.
- `large-v3-turbo` is downloaded in the HuggingFace cache.
- The installed torch is CUDA-enabled and sees the RTX 3080 Laptop GPU.
