import argparse
import asyncio
import contextlib
import subprocess
from pathlib import Path

from codex_backends import CODEX_MODES, CODEX_SANDBOX_MODES, INTERACTIVE_ACTIONS, create_backend
from turn_files import write_turn_files
from voice_tts import speak_windows, speak_windows_async
from voice_turns import VoiceTurn, voice_turn_from_transcript_file


DEFAULT_WS_URL = "ws://127.0.0.1:8000/asr?language=auto&mode=full"
ACK_TEXT = "Sure, request received. Please hold on."
CANCEL_TEXTS = {"cancel", "stop", "never mind"}


async def next_turn(args: argparse.Namespace) -> VoiceTurn:
    if args.transcript_file:
        return voice_turn_from_transcript_file(Path(args.transcript_file))
    from turn_capture import capture_one_turn

    return await capture_one_turn(args)


def should_exit_after_turn(args: argparse.Namespace) -> bool:
    return args.once or bool(args.transcript_file)


async def main_async(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    codex_cwd = Path(args.codex_cwd).resolve()

    while True:
        turn = await next_turn(args)
        if not turn.text:
            print("No prompt captured. Listening again.")
            if should_exit_after_turn(args):
                return
            continue
        if turn.text.lower() in CANCEL_TEXTS:
            print("Canceled.")
            if should_exit_after_turn(args):
                return
            continue

        files = write_turn_files(out_dir, turn)
        print("Prompt file:", files.prompt_path)
        print("Prompt:", turn.text)
        if turn.language:
            print("TTS language:", turn.language)
        print("Turn source:", turn.source)

        if not args.submit_codex:
            print("Preview mode. Add --submit-codex to send this to Codex.")
            if should_exit_after_turn(args):
                return
            continue

        backend = create_backend(
            args.codex_mode,
            args.codex_bin,
            args.codex_sandbox,
            args.interactive_action,
            args.codex_session_id,
            args.codex_timeout_seconds,
        )
        print(f"Submitting to Codex ({args.codex_mode})...")
        ack_process = speak_windows_async(args.ack_text, args.tts_rate) if args.speak else None
        result = backend.submit(turn, files, codex_cwd)

        print("Codex command:", " ".join(result.command))
        if result.answer_path:
            print("Answer file:", result.answer_path)
        if result.error_path:
            print("Codex warning/error log:", result.error_path)
        if result.pid:
            print("Codex process id:", result.pid)
        if not result.ok:
            print(result.status_text or "Codex request failed.")
            if should_exit_after_turn(args):
                return
            continue

        speak_text = result.final_text or result.status_text
        if result.final_text:
            print(result.final_text)
        elif result.status_text:
            print(result.status_text)
        if args.speak and speak_text:
            if ack_process and ack_process.poll() is None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    ack_process.wait(timeout=3)
            speak_windows(speak_text, args.tts_rate, turn.language)

        if should_exit_after_turn(args):
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voice and transcript bridge for WhisperLiveKit and Codex.")
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL)
    parser.add_argument("--wake-word", action="append", default=["codex", "code x", "code ex", "kodex"])
    parser.add_argument("--silence-seconds", type=float, default=2.5)
    parser.add_argument("--rms-threshold", type=float, default=350.0)
    parser.add_argument("--input-gain", type=float, default=1.0)
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
    parser.add_argument("--transcript-file")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--codex-cwd", default=r"C:\Users\Admin\Documents\Playground")
    parser.add_argument("--codex-session-id")
    parser.add_argument("--codex-bin")
    parser.add_argument("--codex-mode", choices=CODEX_MODES, default="one-time")
    parser.add_argument("--interactive-action", choices=INTERACTIVE_ACTIONS, default="fork")
    parser.add_argument("--codex-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--codex-sandbox", choices=CODEX_SANDBOX_MODES, default="danger-full-access")
    parser.add_argument("--submit-codex", action="store_true")
    parser.add_argument("--speak", action="store_true")
    parser.add_argument("--ack-text", default=ACK_TEXT)
    parser.add_argument("--tts-rate", type=int, default=0)
    parser.add_argument("--listen-status-seconds", type=float, default=15.0)
    parser.add_argument("--debug-transcript", action="store_true")
    return parser.parse_args()


def main() -> None:
    try:
        asyncio.run(main_async(parse_args()))
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
