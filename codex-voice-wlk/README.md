# Codex Voice WLK

This folder is a local voice bridge for talking to Codex through the Codex CLI.
It uses WhisperLiveKit for streaming speech-to-text, a small Python bridge for
wake-word and endpointing, and optional Windows TTS for spoken Codex answers.

## Current Shape

```text
microphone
  -> voice_bridge.py
  -> ws://127.0.0.1:8000/asr?language=auto&mode=full
  -> WhisperLiveKit / faster-whisper
  -> transcript after wake word
  -> codex exec resume --last
  -> .voice/turns/*.codex_answer.txt
  -> optional Windows System.Speech TTS
```

The project-specific code is intentionally small:

| Path | Purpose |
| --- | --- |
| `voice_bridge.py` | Captures mic audio, streams PCM to WhisperLiveKit, detects wake words, decides turn end, writes turn files, optionally submits to Codex CLI, optionally speaks the answer. |
| `start_wlk_faster_whisper.cmd` | Starts the local WhisperLiveKit server with `faster-whisper` and `large-v3-turbo`. |
| `run_voice_bridge_preview.cmd` | Runs the bridge without submitting anything to Codex. |
| `run_voice_bridge_codex.cmd` | Runs the bridge, submits captured prompts to Codex, and speaks answers. |
| `stop_wlk.cmd` | Stops the known WLK server PID from the pid file if present. |
| `RUNBOOK.md` | Short operational commands and tuning snippets. |
| `WhisperLiveKit/` | Local clone of the upstream real-time STT server and model backends. This directory is ignored by git. |

## Requirements

- Windows-first setup.
- Python virtual environment at `.venv`.
- Working microphone accepted by `sounddevice`.
- Local `wlk.exe` from a clone of WhisperLiveKit installed into `.venv`.
- Codex CLI available as `codex`.
- Hugging Face model cache containing or able to download `faster-whisper/large-v3-turbo`.
- For local GPU acceleration, CUDA-capable PyTorch and an NVIDIA GPU.

The checked setup currently uses Python 3.11 inside `.venv`. The host shell
Python may be different and should not be used to run the bridge.

## Start The STT Server

```cmd
start_wlk_faster_whisper.cmd
```

This starts:

```text
backend: faster-whisper
model: large-v3-turbo
input: PCM s16le / 16kHz / mono
host: 127.0.0.1
port: 8000
```

Health checks:

```cmd
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/models
```

Expected model response:

```json
{"object":"list","data":[{"id":"faster-whisper/large-v3-turbo","object":"model","owned_by":"whisperlivekit"}]}
```

Stop the known local server:

```cmd
stop_wlk.cmd
```

## Run The Voice Bridge

Preview mode captures a prompt and writes it under `.voice\turns`, but does not
send it to Codex:

```cmd
run_voice_bridge_preview.cmd
```

Codex mode sends the captured prompt to the latest Codex CLI session and speaks
the final answer through Windows TTS:

```cmd
run_voice_bridge_codex.cmd
```

To target a specific Codex CLI session:

```cmd
.venv\Scripts\python.exe voice_bridge.py --submit-codex --speak --codex-session-id YOUR_SESSION_ID
```

## Conversation Behavior

Default wake words:

```text
codex, code x, code ex, kodex
```

After the bridge sees a wake word in the transcript, it keeps the transcript
text after the wake word as the prompt body. Later transcript updates can
replace the current prompt candidate even when they do not repeat the wake word.

Turn finalization uses several signals:

- transcript contains at least `--min-prompt-chars` characters;
- at least `--post-wake-grace-seconds` has passed after wake;
- transcript has been stable for `--text-settle-seconds`;
- local Silero VAD saw post-wake speech end;
- fallback: no voice or text activity for `--silence-seconds`;
- fallback: wake word heard but no body before `--empty-prompt-timeout-seconds`.

Useful tuning examples:

```cmd
.venv\Scripts\python.exe voice_bridge.py --silence-seconds 2.0
.venv\Scripts\python.exe voice_bridge.py --rms-threshold 500
.venv\Scripts\python.exe voice_bridge.py --wake-word codex --wake-word assistant
.venv\Scripts\python.exe voice_bridge.py --vad-min-silence-ms 1200
.venv\Scripts\python.exe voice_bridge.py --post-wake-grace-seconds 1.8
.venv\Scripts\python.exe voice_bridge.py --text-settle-seconds 1.0
```

## Output Files

Captured turns are written under:

```text
.voice/turns/
```

Each turn gets:

```text
YYYYMMDD-HHMMSS.prompt.txt
YYYYMMDD-HHMMSS.codex_answer.txt
```

These files are useful for debugging recognition errors and Codex response
quality. They may contain private spoken prompts and should not be committed.

## Resource Notes

The low-resource path is currently `faster-whisper` with `large-v3-turbo`; the
Voxtral 4B path was disabled after testing because it pressured the 8GB laptop
GPU and offloaded parameters to CPU.

On the checked machine while WLK was running:

- WLK health reported `backend=faster-whisper` and `ready=true`.
- The active model was `faster-whisper/large-v3-turbo`.
- The main Python STT process had roughly 1.9GB working set and 5.4GB private memory.
- `nvidia-smi` showed an RTX 3080 Laptop GPU with 8GB total memory and about 2.3GB used overall at that moment.

Treat these as local observations, not hard requirements. Measure again after
model, backend, or chunking changes.

## Known Limitations

- `voice_bridge.py` mixes audio capture, wake logic, endpointing, file output,
  Codex submission, and TTS in one module.
- Wake detection is transcript-based, so the ASR model is always running before
  wake. This is simple, but not the lowest possible idle resource design.
- Endpointing combines WLK transcript updates with a second local Silero VAD.
  The duplicated VAD can be useful, but it also makes timing harder to reason
  about.
- `codex exec resume --last` is convenient but can attach to the wrong session;
  use `--codex-session-id` when continuity matters.
- `run_codex` is synchronous, so listening stops while Codex is answering.
- Windows TTS is simple and local, but voice quality and interruption handling
  are limited.
- `stop_wlk.cmd` depends on pid files and may miss a manually started server or
  stale process tree.
## Direction For A Lower-Resource Human-Like Loop

Near-term, keep the current preview-first workflow but split the bridge into
small pieces:

```text
audio input
wake gate
streaming STT client
turn endpointing
Codex session adapter
TTS output
conversation controller
```

The main resource win is to avoid full STT while idle. A practical next step is
hotkey or tiny wake-gate first, then start or resume STT only for the user turn.
If hands-free wake is required, add a small dedicated wake model and keep the
large STT model warm only when the user is actively speaking.

For human-like interaction, the next bottlenecks are interruption handling,
barge-in while TTS is speaking, streaming partial Codex responses, and explicit
state for whether the system is idle, listening, thinking, or speaking.
