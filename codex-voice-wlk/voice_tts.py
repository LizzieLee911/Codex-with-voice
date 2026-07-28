from __future__ import annotations

import subprocess

from voice_turns import normalize_tts_language


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def tts_script(rate: int, language: str | None = None) -> str:
    preferred_culture = ps_quote(normalize_tts_language(language))
    return (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$voices = $s.GetInstalledVoices(); "
        "$voice = $null; "
        f"$preferredCulture = {preferred_culture}; "
        "if ($preferredCulture) { "
        "$voice = $voices | Where-Object { $_.VoiceInfo.Culture.Name -ieq $preferredCulture } | Select-Object -First 1; "
        "if (-not $voice) { $voice = $voices | Where-Object { $_.VoiceInfo.Culture.Name -like \"$preferredCulture-*\" } | Select-Object -First 1 }; "
        "} "
        "if (-not $voice) { $voice = $voices | Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | Select-Object -First 1 }; "
        "if ($voice) { $s.SelectVoice($voice.VoiceInfo.Name) }; "
        f"$s.Rate = {rate}; "
        "$text = [Console]::In.ReadToEnd(); "
        "$s.Speak($text)"
    )


def speak_windows(text: str, rate: int, language: str | None = None) -> None:
    if not text:
        return
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", tts_script(rate, language)],
        input=text,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def speak_windows_async(text: str, rate: int, language: str | None = None) -> subprocess.Popen[str] | None:
    if not text:
        return None
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", tts_script(rate, language)],
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
