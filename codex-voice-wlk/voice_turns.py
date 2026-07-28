from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


LANGUAGE_ALIASES = {
    "chinese": "zh",
    "mandarin": "zh",
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "arabic": "ar",
}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def normalize_space(text: str) -> str:
    return " ".join(str(text or "").split())


def normalize_tts_language(language: str | None) -> str:
    if not language:
        return ""
    cleaned = language.strip().lower().replace("_", "-")
    cleaned = LANGUAGE_ALIASES.get(cleaned, cleaned)
    match = re.match(r"^[a-z]{2,3}(?:-[a-z0-9]+)?", cleaned)
    return match.group(0) if match else ""


def infer_language_from_text(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u0400-\u04ff]", text):
        return "ru"
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar"
    return ""


@dataclass(frozen=True)
class VoiceTurn:
    text: str
    language: str = ""
    source: str = "microphone"
    created_at: str = field(default_factory=now_stamp)


def build_voice_turn(text: str, language: str = "", source: str = "microphone") -> VoiceTurn:
    prompt = normalize_space(text)
    turn_language = infer_language_from_text(prompt) or normalize_tts_language(language)
    return VoiceTurn(text=prompt, language=turn_language, source=source)


def voice_turn_from_transcript_file(path: Path) -> VoiceTurn:
    text = path.read_text(encoding="utf-8", errors="replace")
    return build_voice_turn(text, source=f"transcript-file:{path}")
