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

# Fix Windows terminal encoding for Cyrillic output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}

FILLER_WORDS = {
    "эм", "ам", "короче", "типа", "значит",
    "как бы", "так сказать", "в общем", "походу",
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
    parser.add_argument("--model", default="large-v3", help="Модель Whisper (default: large-v3)")
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


_whisper_model_cache = {}


def _ensure_cuda_dll_path():
    """Add NVIDIA pip package DLLs to PATH so ctranslate2 can find them."""
    try:
        import nvidia.cublas
        site_dir = os.path.dirname(os.path.dirname(nvidia.cublas.__path__[0]))
        dll_dirs = [
            os.path.join(site_dir, "nvidia", "cublas", "bin"),
            os.path.join(site_dir, "nvidia", "cudnn", "bin"),
            os.path.join(site_dir, "nvidia", "cuda_runtime", "bin"),
        ]
        path = os.environ.get("PATH", "")
        for d in dll_dirs:
            if os.path.isdir(d) and d not in path:
                os.environ["PATH"] = d + os.pathsep + path
                path = os.environ["PATH"]
    except ImportError:
        pass


def load_whisper_model(model_name):
    """Load faster-whisper model with CUDA auto-detection and runtime verification."""
    from faster_whisper import WhisperModel

    if model_name in _whisper_model_cache:
        return _whisper_model_cache[model_name]

    _ensure_cuda_dll_path()

    # Try CUDA with a real inference test to catch missing DLLs
    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
        # Verify CUDA actually works by running a tiny inference
        import numpy as np
        silence = np.zeros(16000, dtype=np.float32)  # 1 second of silence
        list(model.transcribe(silence, language="ru")[0])
        print(f"Модель {model_name} загружена (CUDA)")
        _whisper_model_cache[model_name] = model
        return model
    except Exception:
        pass

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    print(f"Модель {model_name} загружена (CPU)")
    _whisper_model_cache[model_name] = model
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
    stats = {"fillers": 0, "stutters": 0, "noise": 0, "zero_duration": 0}
    clean = []

    for i, w in enumerate(words):
        # Zero-duration words: Whisper hallucinations
        if w["end"] <= w["start"]:
            stats["zero_duration"] += 1
            continue

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

    # Filter out invalid segments where end <= start (Whisper edge case)
    segments = [(s, e) for s, e in segments if e > s]

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
    if word_stats.get("zero_duration", 0) > 0:
        print(f"Удалено галлюцинаций: {word_stats['zero_duration']}")
    print(f"Итоговая длительность: {format_duration(total_with_gaps)} ({pct:.0f}% от оригинала)")
    print(f"{'='*50}\n")


def _detect_nvenc():
    """Check if NVIDIA NVENC encoder is available."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True,
    )
    return "h264_nvenc" in result.stdout


def _build_encode_args(use_nvenc):
    """Return ffmpeg encoding arguments for video and audio."""
    if use_nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20", "-c:a", "aac", "-b:a", "192k"]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", "-b:a", "192k"]


def cut_and_concat(filepath, segments, output_path):
    """Cut segments from video and concatenate them using ffmpeg concat demuxer."""
    from tqdm import tqdm

    use_nvenc = _detect_nvenc()
    encoder_name = "NVENC" if use_nvenc else "libx264"
    encode_args = _build_encode_args(use_nvenc)

    tmpdir = tempfile.mkdtemp(prefix="cut_pauses_")
    try:
        segment_files = []
        print(f"Нарезка: {len(segments)} сегментов ({encoder_name})...")

        for i, (start, end) in enumerate(tqdm(segments, desc="  Нарезка")):
            seg_file = os.path.join(tmpdir, f"seg_{i:05d}.mp4")
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", str(start),
                "-to", str(end),
                "-i", str(filepath),
                *encode_args,
                seg_file,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  Ошибка ffmpeg на сегменте {i}: {result.stderr.strip()}")
                continue
            segment_files.append(seg_file)

        if not segment_files:
            print("Ошибка: не удалось нарезать ни одного сегмента.")
            return False

        # Write concat list
        concat_file = os.path.join(tmpdir, "concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for sf in segment_files:
                safe_path = sf.replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

        # Concatenate (stream copy — all segments have same encoding)
        print("  Склейка...")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Ошибка склейки: {result.stderr.strip()}")
            return False

        print(f"  Готово: {output_path}")
        return True

    finally:
        # Cleanup temp files
        shutil.rmtree(tmpdir, ignore_errors=True)


def save_transcript(words, filepath):
    """Save transcription to JSON file next to the video."""
    json_path = filepath.with_suffix(".transcript.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)
    print(f"  Транскрипция сохранена: {json_path}")


def process_file(model, filepath, args):
    """Process a single video file through all three phases."""
    print(f"\n{'─'*50}")
    print(f"Файл: {filepath.name}")
    print(f"{'─'*50}")

    # Duration
    try:
        duration = get_video_duration(filepath)
    except Exception:
        print(f"  Предупреждение: не удалось определить длительность, пропускаю.")
        return

    # Phase 1: Transcribe
    words = transcribe(model, filepath)
    if not words:
        print(f"  Предупреждение: транскрипция не вернула слов, пропускаю.")
        return

    if args.save_transcript:
        save_transcript(words, filepath)

    # Phase 2: Filter
    clean_words, word_stats = filter_words(words, args.pause)
    segments, pause_stats = build_segments(clean_words, args.pause)

    # Report
    print_report(filepath, duration, words, clean_words, segments, word_stats, pause_stats)

    if args.dry_run:
        return

    if not segments:
        print("  Предупреждение: нет сегментов для нарезки, пропускаю.")
        return

    # Phase 3: Cut and concat
    output_path = get_output_path(filepath, args.output)
    cut_and_concat(filepath, segments, output_path)


def main():
    args = parse_args()
    check_ffmpeg()

    video_files = collect_video_files(args.input)
    if not video_files:
        print("Нет файлов для обработки.")
        sys.exit(1)

    print(f"Файлов для обработки: {len(video_files)}")

    # Load model once for all files
    model = load_whisper_model(args.model)

    for filepath in video_files:
        try:
            process_file(model, filepath, args)
        except KeyboardInterrupt:
            print("\nПрервано пользователем.")
            sys.exit(1)
        except Exception as e:
            print(f"  Ошибка при обработке {filepath.name}: {e}")
            continue


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)  # avoid CUDA teardown crash (exit code 127)
