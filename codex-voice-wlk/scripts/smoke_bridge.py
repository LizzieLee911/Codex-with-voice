from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "voice_bridge.py"
FIXTURE = ROOT / "fixtures" / "fake-transcript.txt"


def write_fake_codex(root: Path) -> Path:
    if os.name == "nt":
        fake = root / "fake-codex.cmd"
        fake.write_text(
            "\n".join(
                [
                    "@echo off",
                    "setlocal",
                    "set \"out=\"",
                    ":loop",
                    "if \"%~1\"==\"\" goto done",
                    "if \"%~1\"==\"-o\" goto foundout",
                    "shift",
                    "goto loop",
                    ":foundout",
                    "shift",
                    "set \"out=%~1\"",
                    "shift",
                    "goto loop",
                    ":done",
                    "if \"%out%\"==\"\" exit /b 2",
                    "echo fake bridge answer>\"%out%\"",
                    "exit /b 0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return fake

    fake = root / "fake-codex.sh"
    fake.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                "out=",
                "while [ \"$#\" -gt 0 ]; do",
                "  if [ \"$1\" = \"-o\" ]; then shift; out=\"$1\"; fi",
                "  shift",
                "done",
                "[ -n \"$out\" ] || exit 2",
                "printf 'fake bridge answer\\n' > \"$out\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="codex-voice-bridge-") as temp_dir:
        temp = Path(temp_dir)
        fake_codex = write_fake_codex(temp)
        out_dir = temp / "voice"
        cmd = [
            sys.executable,
            str(BRIDGE),
            "--transcript-file",
            str(FIXTURE),
            "--out-dir",
            str(out_dir),
            "--codex-cwd",
            str(temp),
            "--codex-bin",
            str(fake_codex),
            "--codex-sandbox",
            "danger-full-access",
            "--codex-mode",
            "one-time",
            "--submit-codex",
        ]
        result = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
        )
        combined = result.stdout + result.stderr
        if result.returncode != 0:
            print(combined)
            return result.returncode
        if "fake bridge answer" not in combined:
            print(combined)
            print("Expected fake bridge answer in bridge output.")
            return 1
        if "Submitting to Codex (one-time)" not in combined:
            print(combined)
            print("Expected one-time submit log.")
            return 1
        print("bridge smoke ok")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
