"""Shared utilities for pipeline scripts."""

import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = frozenset({".mp4", ".mov", ".mkv", ".avi"})
AUDIO_EXTS = frozenset({".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"})
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


def fix_windows_stdio() -> None:
    """UTF-8 для Windows-консоли. Вызывать в начале main()."""
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def format_tc(seconds: float, *, fractional: bool = True) -> str:
    """Форматирует секунды в таймкод.

    fractional=True  → MM:SS.ss (для script.csv, candidates.json)
    fractional=False → MM:SS / H:MM:SS (для логов и дисплея)
    """
    if fractional:
        m = int(seconds // 60)
        s = seconds - m * 60
        return f"{m:02d}:{s:05.2f}"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_tc(tc_str: str) -> float:
    """Парсит таймкод HH:MM:SS.ss или MM:SS.ss в секунды."""
    parts = [p.strip() for p in tc_str.strip().split(":")]
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0.0


def probe_duration(path: Path) -> float:
    """ffprobe duration в секундах. Бросает CalledProcessError если файл невалидный."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())
