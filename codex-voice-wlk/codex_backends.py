from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from turn_files import TurnFiles
from voice_turns import VoiceTurn


CODEX_OUTPUT_INSTRUCTION = (
    "Use the same language as the user's request for both interpreting the request and reporting back. "
    "Do not output code, file paths, Markdown links, or logs. "
    "Use plain language to briefly report progress and the result."
)
CODEX_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
CODEX_MODES = ("one-time", "interactive")
INTERACTIVE_ACTIONS = ("fork", "resume")


@dataclass(frozen=True)
class CodexResult:
    mode: str
    ok: bool
    command: list[str]
    final_text: str = ""
    status_text: str = ""
    answer_path: Path | None = None
    error_path: Path | None = None
    pid: int | None = None
    returncode: int | None = None


def build_codex_prompt(prompt: str) -> str:
    return f"{prompt.strip()}\n\n{CODEX_OUTPUT_INSTRUCTION}\n"


def command_for_log(cmd: list[str]) -> list[str]:
    return ["[prompt]" if "\n" in arg else arg for arg in cmd]


def format_command(cmd: list[str]) -> str:
    return " ".join(command_for_log(cmd))


def resolve_codex_bin(codex_bin: str | None) -> str:
    if codex_bin:
        return codex_bin
    return shutil.which("codex.cmd") or shutil.which("codex") or "codex"


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


def build_one_time_cmd(codex_bin: str, answer_path: Path, sandbox_mode: str) -> list[str]:
    return [
        codex_bin,
        "exec",
        "--sandbox",
        sandbox_mode,
        "--skip-git-repo-check",
        "-o",
        str(answer_path),
        "-",
    ]


def build_interactive_cmd(
    codex_bin: str,
    action: str,
    session_id: str | None,
    sandbox_mode: str,
    prompt: str,
) -> list[str]:
    cmd = [codex_bin, action, "--sandbox", sandbox_mode]
    cmd.append(session_id or "--last")
    cmd.append(prompt)
    return cmd


class OneTimeBackend:
    def __init__(self, codex_bin: str | None, sandbox_mode: str) -> None:
        self.codex_bin = resolve_codex_bin(codex_bin)
        self.sandbox_mode = sandbox_mode

    def submit(self, turn: VoiceTurn, files: TurnFiles, cwd: Path) -> CodexResult:
        cmd = build_one_time_cmd(self.codex_bin, files.answer_path, self.sandbox_mode)
        result = run_codex_command(cmd, build_codex_prompt(turn.text), cwd)
        if result.returncode != 0:
            error_text = (
                f"[one-time] codex exited with status {result.returncode}\n"
                f"command: {format_command(cmd)}\n\n"
                f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
            )
            files.error_path.write_text(error_text, encoding="utf-8")
            return CodexResult(
                mode="one-time",
                ok=False,
                command=cmd,
                answer_path=files.answer_path,
                error_path=files.error_path,
                returncode=result.returncode,
                status_text=f"codex exited with status {result.returncode}",
            )

        if result.stderr:
            files.error_path.write_text(
                f"[one-time] codex completed with warnings\ncommand: {format_command(cmd)}\n\nstderr:\n{result.stderr}",
                encoding="utf-8",
            )
        if files.answer_path.exists():
            final_text = files.answer_path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            final_text = result.stdout.strip()
            if final_text:
                files.answer_path.write_text(final_text + "\n", encoding="utf-8")
        return CodexResult(
            mode="one-time",
            ok=True,
            command=cmd,
            final_text=final_text,
            answer_path=files.answer_path,
            error_path=files.error_path if files.error_path.exists() else None,
            returncode=result.returncode,
        )


class InteractiveBackend:
    def __init__(self, codex_bin: str | None, sandbox_mode: str, action: str, session_id: str | None) -> None:
        self.codex_bin = resolve_codex_bin(codex_bin)
        self.sandbox_mode = sandbox_mode
        self.action = action
        self.session_id = session_id

    def submit(self, turn: VoiceTurn, files: TurnFiles, cwd: Path) -> CodexResult:
        cmd = build_interactive_cmd(
            self.codex_bin,
            self.action,
            self.session_id,
            self.sandbox_mode,
            build_codex_prompt(turn.text),
        )
        log_path = files.answer_path.with_suffix(".interactive_launch.txt")
        try:
            log_path.write_text(
                f"[interactive] launched\ncommand: {format_command(cmd)}\n",
                encoding="utf-8",
            )
            creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            files.error_path.write_text(
                f"[interactive] failed to launch\ncommand: {format_command(cmd)}\n\n{exc}",
                encoding="utf-8",
            )
            return CodexResult(
                mode="interactive",
                ok=False,
                command=command_for_log(cmd),
                error_path=files.error_path,
                status_text=f"interactive launch failed: {exc}",
            )
        return CodexResult(
            mode="interactive",
            ok=True,
            command=command_for_log(cmd),
            answer_path=log_path,
            pid=process.pid,
            status_text="Interactive request opened in Codex. Continue there for progress.",
        )


def create_backend(
    mode: str,
    codex_bin: str | None,
    sandbox_mode: str,
    interactive_action: str,
    session_id: str | None,
) -> OneTimeBackend | InteractiveBackend:
    if mode == "interactive":
        return InteractiveBackend(codex_bin, sandbox_mode, interactive_action, session_id)
    return OneTimeBackend(codex_bin, sandbox_mode)
