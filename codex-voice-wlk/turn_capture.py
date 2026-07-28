from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import re
import time

import numpy as np
import sounddevice as sd
import websockets
from whisperlivekit.silero_vad_iterator import FixedVADIterator, OnnxWrapper, load_onnx_session

from voice_turns import VoiceTurn, build_voice_turn, normalize_space


SEND_NOW_PHRASES = (
    "\u53d1\u5427",
    "\u5c31\u8fd9\u6837",
    "\u5c31\u8fd9\u4e9b",
    "\u53ef\u4ee5\u4e86",
    "send now",
    "that's it",
    "go ahead",
)
HOLD_PHRASES = (
    "\u7b49\u4e00\u4e0b",
    "\u6211\u60f3\u4e00\u4e0b",
    "\u8ba9\u6211\u60f3\u60f3",
    "hold on",
    "wait a second",
    "let me think",
)
CONTINUATION_TAILS = (
    "\u55ef",
    "\u5443",
    "\u989d",
    "em",
    "emm",
    "emmm",
    "um",
    "uh",
    "\u7136\u540e",
    "\u5c31\u662f",
)


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
    tail = normalize_space(text).lower().rstrip(" ,.!?;:\u3002\uff01\uff1f\uff1b\uff1a")
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


async def capture_one_turn(args: argparse.Namespace) -> VoiceTurn:
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
    turn_language = ""
    last_rms = 0.0
    audio_chunks = 0
    last_status_at = time.monotonic()

    def enqueue_audio(data: bytes) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            audio_queue.put_nowait(data)

    def audio_callback(indata, frames, callback_time, status):
        nonlocal audio_chunks, last_rms, last_voice_at
        data = bytes(indata)
        rms = pcm_rms(data)
        audio_chunks += 1
        last_rms = rms
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
                        if active and detected_language:
                            turn_language = detected_language

                if not active and args.listen_status_seconds > 0:
                    now = time.monotonic()
                    if now - last_status_at >= args.listen_status_seconds:
                        last_status_at = now
                        print(f"Listening status: audio chunks={audio_chunks}, last rms={last_rms:.1f}, waiting for wake word.")

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
                    if active and detected_language:
                        turn_language = detected_language
            except Exception:
                pass

    return build_voice_turn(prompt_candidate, turn_language or reported_language, source="microphone")
