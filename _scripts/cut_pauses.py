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


def filter_words(words, pause_threshold):
    """Filter out filler words, stutters, noise tokens. Return clean words and stats."""
    stats = {"fillers": 0, "stutters": 0, "noise": 0}
    clean = []

    for i, w in enumerate(words):
        text = w["word"].lower().strip()

        # Noise tokens: anything in square brackets
        if text.startswith("[") and text.endswith("]"):
            stats["noise"] += 1
            continue

        # Filler words
        if text in FILLER_WORDS:
            stats["fillers"] += 1
            continue

        # Stutters: same word twice in a row — skip the first occurrence
        # We check if the NEXT word is the same; if so, skip current
        if i + 1 < len(words):
            next_text = words[i + 1]["word"].lower().strip()
            if text == next_text and text not in FILLER_WORDS:
                stats["stutters"] += 1
                continue

        clean.append(w)

    return clean, stats


def build_segments(clean_words, pause_threshold):
    """Build segments of continuous speech from clean words.

    Returns list of (start, end) tuples and pause stats.
    """
    if not clean_words:
        return [], {"count": 0, "total_duration": 0}

    segments = []
    seg_start = clean_words[0]["start"]
    seg_end = clean_words[0]["end"]
    pause_count = 0
    pause_total = 0.0

    for i in range(1, len(clean_words)):
        gap = clean_words[i]["start"] - seg_end
        if gap > pause_threshold:
            segments.append((seg_start, seg_end))
            pause_count += 1
            pause_total += gap
            seg_start = clean_words[i]["start"]
        seg_end = clean_words[i]["end"]

    # Last segment
    segments.append((seg_start, seg_end))

    pause_stats = {"count": pause_count, "total_duration": pause_total}
    return segments, pause_stats


def print_report(filepath, duration, words, clean_words, segments, word_stats, pause_stats):
    """Print dry-run report."""
    clean_duration = sum(end - start for start, end in segments)
    # Add gaps between segments
    total_with_gaps = clean_duration + max(0, len(segments) - 1) * GAP_BETWEEN_SEGMENTS
    pct = (total_with_gaps / duration * 100) if duration > 0 else 0

    print(f"\n{'='*50}")
    print(f"Файл: {filepath.name} ({format_duration(duration)})")
    print(f"Найдено слов: {len(words)}")
    print(f"Удалено пауз: {pause_stats['count']} (суммарно {format_duration(pause_stats['total_duration'])})")
    print(f"Удалено филлеров: {word_stats['fillers']}")
    print(f"Удалено повторов: {word_stats['stutters']}")
    print(f"Удалено шумов: {word_stats['noise']}")
    print(f"Итоговая длительность: {format_duration(total_with_gaps)} ({pct:.0f}% от оригинала)")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    parse_args()
