import argparse
import asyncio
import contextlib
import json
import math
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets
from whisperlivekit.silero_vad_iterator import FixedVADIterator, OnnxWrapper, load_onnx_session


DEFAULT_WS_URL = "ws://127.0.0.1:8000/asr?language=auto&mode=full"
CODEX_OUTPUT_INSTRUCTION = (
    "Default to English for both interpreting the request and reporting back. "
    "Do not output code, file paths, Markdown links, or logs. "
    "Use plain English to briefly report progress and the result."
)
CODEX_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
ACK_TEXT = "Sure, request received. Please hold on."
SEND_NOW_PHRASES = ("发吧", "就这样", "就这些", "可以了", "send now", "that's it", "go ahead")
HOLD_PHRASES = ("等一下", "我想一下", "让我想想", "hold on", "wait a second", "let me think")
CONTINUATION_TAILS = ("嗯", "呃", "额", "em", "emm", "emmm", "um", "uh", "然后", "就是")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def build_codex_prompt(prompt: str) -> str:
    return f"{prompt.strip()}\n\n{CODEX_OUTPUT_INSTRUCTION}\n"


def compile_wake_regex(words: list[str]) -> re.Pattern[str]:
    escaped = sorted((re.escape(w.strip()) for w in words if w.strip()), key=len, reverse=True)
    return re.compile(r"(?i)(?<![A-Za-z0-9_])(" + "|".join(escaped) + r")(?![A-Za-z0-9_])")


def text_after_wake(text: str, wake_re: re.Pattern[str]) -> str | None:
    matches = list(wake_re.finditer(text))
    if not matches:
        return None
    return normalize_space(text[matches[-1].end() :])


def update_prompt_from_visible(
    visible_text: str,
    wake_re: re.Pattern[str],
    active: bool,
    current_prompt: str,
) -> tuple[bool, str]:
    after_wake = text_after_wake(visible_text, wake_re)
    if after_wake is not None:
        if after_wake:
            return True, after_wake
        return True, current_prompt
    if active and visible_text:
        return False, visible_text
    return False, current_prompt


def text_has_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def has_continuation_tail(text: str) -> bool:
    tail = normalize_space(text).lower().rstrip(" ,.!?。！？；;，")
    return any(tail.endswith(phrase) for phrase in CONTINUATION_TAILS)


def human_silence_needed(prompt: str, args: argparse.Namespace) -> float:
    if text_has_any(prompt, HOLD_PHRASES):
        return args.hold_silence_seconds
    if has_continuation_tail(prompt):
        return args.continuation_silence_seconds
    return args.human_silence_seconds


def extract_visible_text(message: dict) -> str:
    parts: list[str] = []
    for line in message.get("lines") or []:
        text = line.get("text")
        if text:
            parts.append(str(text))
    buffer_text = message.get("buffer_transcription")
    if buffer_text:
        parts.append(str(buffer_text))
    return normalize_space(" ".join(parts))


def extract_detected_language(message: dict) -> str | None:
    for key in ("lines", "new_lines"):
        for line in message.get(key) or []:
            language = line.get("detected_language")
            if language:
                return str(language)
    return None


def pcm_rms(data: bytes) -> float:
    if not data:
        return 0.0
    count = len(data) // 2
    if count == 0:
        return 0.0
    total = 0
    for i in range(0, len(data) - 1, 2):
        value = int.from_bytes(data[i : i + 2], "little", signed=True)
        total += value * value
    return math.sqrt(total / count)


def pcm16_to_float32(data: bytes) -> np.ndarray:
    if not data:
        return np.array([], dtype=np.float32)
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


async def capture_one_turn(args: argparse.Namespace) -> str:
    wake_re = compile_wake_regex(args.wake_word)
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=20)
    loop = asyncio.get_running_loop()
    vad = FixedVADIterator(
        OnnxWrapper(load_onnx_session(force_onnx_cpu=True)),
        threshold=args.vad_threshold,
        sampling_rate=args.sample_rate,
        min_silence_duration_ms=args.vad_min_silence_ms,
        speech_pad_ms=args.vad_speech_pad_ms,
    )

    active = False
    prompt_candidate = ""
    last_visible_text = ""
    last_text_at = time.monotonic()
    last_voice_at = time.monotonic()
    last_human_speech_at = time.monotonic()
    human_speech_active = False
    wake_at = 0.0
    finalizing = False
    reported_language = ""

    def enqueue_audio(data: bytes) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            audio_queue.put_nowait(data)

    def audio_callback(indata, frames, callback_time, status):
        nonlocal last_voice_at
        data = bytes(indata)
        rms = pcm_rms(data)
        if rms >= args.rms_threshold:
            last_voice_at = time.monotonic()
        loop.call_soon_threadsafe(enqueue_audio, data)

    async with websockets.connect(args.ws_url, max_size=None) as ws:
        stream = sd.RawInputStream(
            samplerate=args.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=int(args.sample_rate * args.chunk_seconds),
            callback=audio_callback,
        )
        stream.start()
        print("Listening. Say one of:", ", ".join(args.wake_word))

        async def sender():
            nonlocal human_speech_active, last_human_speech_at, last_voice_at
            while True:
                chunk = await audio_queue.get()
                if finalizing:
                    return
                now = time.monotonic()
                for event in vad(pcm16_to_float32(chunk)):
                    now = time.monotonic()
                    if "start" in event:
                        human_speech_active = True
                        last_human_speech_at = now
                        last_voice_at = now
                    if "end" in event:
                        human_speech_active = False
                        last_human_speech_at = now
                if human_speech_active:
                    last_human_speech_at = now
                    last_voice_at = now
                await ws.send(chunk)

        sender_task = asyncio.create_task(sender())
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
                except asyncio.TimeoutError:
                    raw = None

                if raw is not None:
                    try:
                        message = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue

                    if message.get("type") == "config":
                        continue
                    if message.get("type") == "ready_to_stop":
                        break

                    detected_language = extract_detected_language(message)
                    if detected_language and detected_language != reported_language:
                        reported_language = detected_language
                        print("Detected language:", reported_language)

                    visible_text = extract_visible_text(message)
                    if visible_text and visible_text != last_visible_text:
                        last_visible_text = visible_text
                        last_text_at = time.monotonic()
                        wake_found, next_prompt = update_prompt_from_visible(
                            visible_text,
                            wake_re,
                            active,
                            prompt_candidate,
                        )
                        if wake_found:
                            if not active:
                                print("Wake word detected.")
                                wake_at = time.monotonic()
                                last_voice_at = wake_at
                            active = True
                        if active and next_prompt != prompt_candidate:
                            prompt_candidate = next_prompt
                            if prompt_candidate and args.debug_transcript:
                                print("Prompt:", prompt_candidate)

                if active:
                    prompt_ready = len(prompt_candidate) >= args.min_prompt_chars
                    past_grace = time.monotonic() - wake_at >= args.post_wake_grace_seconds
                    text_settled = time.monotonic() - last_text_at >= args.text_settle_seconds
                    if prompt_ready and past_grace and text_settled and text_has_any(prompt_candidate, SEND_NOW_PHRASES):
                        print("Send-now phrase detected. Finalizing.")
                        break

                    human_silence = time.monotonic() - max(last_human_speech_at, wake_at)
                    needed_silence = human_silence_needed(prompt_candidate, args)
                    if prompt_ready and past_grace and text_settled and human_silence >= needed_silence:
                        print(f"No human speech for {human_silence:.1f}s. Finalizing.")
                        break

                    last_activity = max(last_text_at, last_voice_at)
                    fallback_silence = max(args.silence_seconds, needed_silence)
                    if prompt_ready and time.monotonic() - last_activity >= fallback_silence:
                        print(f"No audio/text for {fallback_silence:.1f}s. Finalizing fallback.")
                        break
                    if not prompt_ready and time.monotonic() - wake_at >= args.empty_prompt_timeout_seconds:
                        print("Wake word heard, but no prompt body was captured.")
                        break
        finally:
            finalizing = True
            stream.stop()
            stream.close()
            sender_task.cancel()
            try:
                await ws.send(b"")
                end_by = time.monotonic() + 5
                while time.monotonic() < end_by:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                    try:
                        message = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if message.get("type") == "ready_to_stop":
                        break
                    visible_text = extract_visible_text(message)
                    detected_language = extract_detected_language(message)
                    if detected_language and detected_language != reported_language:
                        reported_language = detected_language
                        print("Detected language:", reported_language)
                    if visible_text:
                        _, prompt_candidate = update_prompt_from_visible(
                            visible_text,
                            wake_re,
                            active,
                            prompt_candidate,
                        )
            except Exception:
                pass

    return normalize_space(prompt_candidate)


def write_turn_files(out_dir: Path, prompt: str) -> tuple[Path, Path, Path]:
    turns_dir = out_dir / "turns"
    turns_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    prompt_path = turns_dir / f"{stamp}.prompt.txt"
    answer_path = turns_dir / f"{stamp}.codex_answer.txt"
    error_path = turns_dir / f"{stamp}.codex_error.txt"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    return prompt_path, answer_path, error_path


def resolve_codex_bin(codex_bin: str | None) -> str:
    if codex_bin:
        return codex_bin
    return shutil.which("codex.cmd") or shutil.which("codex") or "codex"


def build_codex_cmd(
    codex_bin: str,
    answer_path: Path,
    session_id: str | None,
    resume: bool,
    sandbox_mode: str,
) -> list[str]:
    cmd = [codex_bin, "exec"]
    if resume:
        cmd.extend(["resume", "-c", f'sandbox_mode="{sandbox_mode}"'])
        cmd.append(session_id or "--last")
    else:
        cmd.extend(["--sandbox", sandbox_mode])
    cmd.extend(["--skip-git-repo-check", "-o", str(answer_path), "-"])
    return cmd


def run_codex_command(cmd: list[str], prompt: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=prompt,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def run_codex(
    prompt: str,
    answer_path: Path,
    error_path: Path,
    cwd: Path,
    session_id: str | None,
    codex_bin: str | None,
    fallback_new_session: bool,
    sandbox_mode: str,
    new_session: bool,
) -> str:
    resolved_bin = resolve_codex_bin(codex_bin)
    codex_prompt = build_codex_prompt(prompt)
    if new_session:
        attempts: list[tuple[str, list[str]]] = [
            ("new-session", build_codex_cmd(resolved_bin, answer_path, None, resume=False, sandbox_mode=sandbox_mode))
        ]
    else:
        attempts = [
            ("resume", build_codex_cmd(resolved_bin, answer_path, session_id, resume=True, sandbox_mode=sandbox_mode))
        ]
    if not new_session and fallback_new_session and not session_id:
        attempts.append(
            ("new-session", build_codex_cmd(resolved_bin, answer_path, None, resume=False, sandbox_mode=sandbox_mode))
        )

    errors: list[str] = []
    for label, cmd in attempts:
        result = run_codex_command(cmd, codex_prompt, cwd)
        if result.returncode == 0:
            if result.stderr:
                errors.append(
                    f"[{label}] codex completed with warnings\n"
                    f"command: {' '.join(cmd)}\n\nstderr:\n{result.stderr}"
                )
            if errors:
                error_path.write_text("\n\n".join(errors), encoding="utf-8")
            break
        error_text = (
            f"[{label}] codex exited with status {result.returncode}\n"
            f"command: {' '.join(cmd)}\n\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
        errors.append(error_text)
        if label == "resume" and len(attempts) > 1:
            print(f"Codex resume failed with status {result.returncode}; trying a fresh session.")
        else:
            print(f"Codex {label} failed with status {result.returncode}.")
    else:
        error_path.write_text("\n\n".join(errors), encoding="utf-8")
        raise RuntimeError(f"codex execution failed; see {error_path}")

    if answer_path.exists():
        return answer_path.read_text(encoding="utf-8", errors="replace").strip()
    if result.stdout.strip():
        answer_path.write_text(result.stdout.strip() + "\n", encoding="utf-8")
        return result.stdout.strip()
    return ""


def tts_script(rate: int) -> str:
    return (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$voice = $s.GetInstalledVoices() | "
        "Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | "
        "Select-Object -First 1; "
        "if ($voice) { $s.SelectVoice($voice.VoiceInfo.Name) }; "
        f"$s.Rate = {rate}; "
        "$text = [Console]::In.ReadToEnd(); "
        "$s.Speak($text)"
    )


def speak_windows(text: str, rate: int) -> None:
    if not text:
        return
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", tts_script(rate)],
        input=text,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def speak_windows_async(text: str, rate: int) -> subprocess.Popen[str] | None:
    if not text:
        return None
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", tts_script(rate)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdin:
            process.stdin.write(text)
            process.stdin.close()
        return process
    except OSError as exc:
        print(f"Initial TTS failed: {exc}")
        return None


async def main_async(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    codex_cwd = Path(args.codex_cwd).resolve()

    while True:
        prompt = await capture_one_turn(args)
        if not prompt:
            print("No prompt captured. Listening again.")
            continue
        if prompt.lower() in {"cancel", "stop", "never mind"}:
            print("Canceled.")
            continue

        prompt_path, answer_path, error_path = write_turn_files(out_dir, prompt)
        print("Prompt file:", prompt_path)
        print("Prompt:", prompt)

        if not args.submit_codex:
            print("Preview mode. Add --submit-codex to send this to Codex CLI.")
            continue

        session_mode = "new session" if args.codex_new_session else "resume last"
        print(f"Submitting to Codex CLI ({session_mode})...")
        ack_process = speak_windows_async(args.ack_text, args.tts_rate) if args.speak else None
        try:
            answer = run_codex(
                prompt,
                answer_path,
                error_path,
                codex_cwd,
                args.codex_session_id,
                args.codex_bin,
                args.codex_fallback_new_session,
                args.codex_sandbox,
                args.codex_new_session,
            )
        except RuntimeError as exc:
            print(exc)
            print("Listening again.")
            continue
        print("Answer file:", answer_path)
        if error_path.exists():
            print("Codex warning/error log:", error_path)
        if answer:
            print(answer)
            if args.speak:
                if ack_process and ack_process.poll() is None:
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        ack_process.wait(timeout=3)
                speak_windows(answer, args.tts_rate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="STT-after-wake bridge for WhisperLiveKit and Codex CLI.")
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL)
    parser.add_argument("--wake-word", action="append", default=["codex", "code x", "code ex", "kodex"])
    parser.add_argument("--silence-seconds", type=float, default=5.0)
    parser.add_argument("--rms-threshold", type=float, default=350.0)
    parser.add_argument("--post-wake-grace-seconds", type=float, default=1.2)
    parser.add_argument("--text-settle-seconds", type=float, default=0.6)
    parser.add_argument("--human-silence-seconds", type=float, default=2.5)
    parser.add_argument("--continuation-silence-seconds", type=float, default=6.0)
    parser.add_argument("--hold-silence-seconds", type=float, default=12.0)
    parser.add_argument("--empty-prompt-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--min-prompt-chars", type=int, default=2)
    parser.add_argument("--vad-threshold", type=float, default=0.5)
    parser.add_argument("--vad-min-silence-ms", type=int, default=900)
    parser.add_argument("--vad-speech-pad-ms", type=int, default=120)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-seconds", type=float, default=0.5)
    parser.add_argument("--out-dir", default=".voice")
    parser.add_argument("--codex-cwd", default=r"C:\Users\Admin\Documents\Playground")
    parser.add_argument("--codex-session-id")
    parser.add_argument("--codex-bin")
    parser.add_argument("--codex-fallback-new-session", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--codex-new-session", action="store_true")
    parser.add_argument("--codex-sandbox", choices=CODEX_SANDBOX_MODES, default="danger-full-access")
    parser.add_argument("--submit-codex", action="store_true")
    parser.add_argument("--speak", action="store_true")
    parser.add_argument("--ack-text", default=ACK_TEXT)
    parser.add_argument("--tts-rate", type=int, default=0)
    parser.add_argument("--debug-transcript", action="store_true")
    return parser.parse_args()


def main() -> None:
    try:
        asyncio.run(main_async(parse_args()))
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
