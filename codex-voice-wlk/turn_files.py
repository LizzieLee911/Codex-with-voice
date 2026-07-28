from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from voice_turns import VoiceTurn


@dataclass(frozen=True)
class TurnFiles:
    prompt_path: Path
    answer_path: Path
    error_path: Path


def write_turn_files(out_dir: Path, turn: VoiceTurn) -> TurnFiles:
    turns_dir = out_dir / "turns"
    turns_dir.mkdir(parents=True, exist_ok=True)
    base = turns_dir / turn.created_at
    prompt_path = base.with_suffix(".prompt.txt")
    answer_path = base.with_suffix(".codex_answer.txt")
    error_path = base.with_suffix(".codex_error.txt")
    prompt_path.write_text(turn.text + "\n", encoding="utf-8")
    return TurnFiles(prompt_path=prompt_path, answer_path=answer_path, error_path=error_path)
