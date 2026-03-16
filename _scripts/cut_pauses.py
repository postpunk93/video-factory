#!/usr/bin/env python3
"""cut_pauses.py — removes pauses, filler words, stutters, and noise from video."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}

FILLER_WORDS = {
    "ну", "вот", "это", "эм", "ам", "короче", "типа", "значит",
    "как бы", "так сказать", "в общем", "допустим", "слушай",
    "смотри", "ладно", "блин", "походу",
}

GAP_BETWEEN_SEGMENTS = 0.15  # 150 ms gap to keep speech natural


def check_ffmpeg():
    """Check that ffmpeg is available in PATH."""
    if not shutil.which("ffmpeg"):
        print("Ошибка: ffmpeg не найден в PATH.")
        print("Установите ffmpeg:")
        print("  Windows: скачать с https://ffmpeg.org и добавить в PATH")
        print("  macOS:   brew install ffmpeg")
        print("  Ubuntu:  sudo apt install ffmpeg")
        sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Удаляет паузы, слова-паразиты и шум из видео."
    )
    parser.add_argument("input", help="Видеофайл или папка с видео")
    parser.add_argument("--output", help="Папка или файл для результата")
    parser.add_argument("--model", default="medium", help="Модель Whisper (default: medium)")
    parser.add_argument("--pause", type=float, default=0.5, help="Порог паузы в секундах (default: 0.5)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать отчёт, не обрабатывать")
    parser.add_argument("--save-transcript", action="store_true", help="Сохранить транскрипцию в JSON")
    return parser.parse_args()


def collect_video_files(input_path):
    """Return list of video file paths from input (file or directory)."""
    p = Path(input_path)
    if p.is_file():
        if p.suffix.lower() in VIDEO_EXTENSIONS:
            return [p]
        else:
            print(f"Предупреждение: {p} — не видеофайл, пропускаю.")
            return []
    elif p.is_dir():
        files = sorted(
            f for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )
        if not files:
            print(f"Предупреждение: в папке {p} нет видеофайлов.")
        return files
    else:
        print(f"Ошибка: {p} не существует.")
        sys.exit(1)


def get_output_path(input_file, output_arg):
    """Determine output file path based on input file and --output argument."""
    stem = input_file.stem + "_clean"
    suffix = input_file.suffix

    if output_arg is None:
        return input_file.parent / f"{stem}{suffix}"

    out = Path(output_arg)
    # If processing multiple files, output_arg is always treated as directory
    # If single file and output_arg has a video extension, treat as file path
    if out.suffix.lower() in VIDEO_EXTENSIONS:
        return out
    else:
        out.mkdir(parents=True, exist_ok=True)
        return out / f"{stem}{suffix}"


def get_video_duration(filepath):
    """Get video duration in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def format_duration(seconds):
    """Format seconds as MM:SS."""
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def load_whisper_model(model_name):
    """Load faster-whisper model with CUDA auto-detection."""
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
        print(f"Модель {model_name} загружена (CUDA)")
    except Exception:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print(f"Модель {model_name} загружена (CPU)")
    return model


def transcribe(model, filepath):
    """Transcribe video and return list of word dicts with start/end times."""
    print(f"Транскрипция: {filepath.name}...")
    segments, info = model.transcribe(
        str(filepath),
        language="ru",
        word_timestamps=True,
    )

    words = []
    segment_count = 0
    for segment in segments:
        segment_count += 1
        if segment_count % 10 == 0:
            print(f"  ...обработано сегментов: {segment_count}", end="\r")
        if segment.words:
            for w in segment.words:
                words.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })

    if segment_count >= 10:
        print()  # newline after \r
    print(f"  Найдено слов: {len(words)}")
    return words


if __name__ == "__main__":
    parse_args()
