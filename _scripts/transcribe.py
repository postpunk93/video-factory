#!/usr/bin/env python3
"""transcribe.py — транскрибация с определением спикеров (диаризация)."""

import argparse
import gc
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# Fix Windows terminal encoding for Cyrillic output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
ALL_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


# ── CLI и сбор файлов ─────────────────────────────────────────────


def parse_args():
    parser = argparse.ArgumentParser(
        description="Транскрибация с определением спикеров (диаризация)."
    )
    parser.add_argument("input", help="Аудио/видеофайл или папка")
    parser.add_argument("--speakers", type=int, default=2,
                        help="Ожидаемое число спикеров (default: 2)")
    parser.add_argument("--model", default="large-v3",
                        help="Модель Whisper (default: large-v3)")
    parser.add_argument("--output", help="Папка для результатов")
    parser.add_argument("--hf-token", default=None,
                        help="HuggingFace токен (или переменная HF_TOKEN)")
    return parser.parse_args()


def get_hf_token(args):
    """Получить HF токен из аргументов или переменной окружения."""
    token = args.hf_token or os.environ.get("HF_TOKEN")
    if not token:
        print("Ошибка: нужен HuggingFace токен для диаризации.")
        print("Укажите через --hf-token или переменную HF_TOKEN.")
        print("Получить токен: https://huggingface.co/settings/tokens")
        print("Принять условия модели:")
        print("  https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("  https://huggingface.co/pyannote/segmentation-3.0")
        sys.exit(1)
    return token


def collect_files(input_path):
    """Собрать аудио/видеофайлы из пути."""
    p = Path(input_path)
    if p.is_file():
        if p.suffix.lower() in ALL_EXTENSIONS:
            return [p]
        else:
            print(f"Предупреждение: {p} — неподдерживаемый формат.")
            return []
    elif p.is_dir():
        files = sorted(
            f for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in ALL_EXTENSIONS
        )
        if not files:
            print(f"Предупреждение: в папке {p} нет аудио/видеофайлов.")
        return files
    else:
        print(f"Ошибка: {p} не существует.")
        sys.exit(1)


# ── CUDA и устройство ─────────────────────────────────────────────


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


def detect_device():
    """Определить устройство: cuda или cpu."""
    _ensure_cuda_dll_path()
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def _free_gpu():
    """Освободить GPU-память между фазами."""
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass


# ── Фаза 1: транскрибация ────────────────────────────────────────


def transcribe(audio_path, model_name, device, compute_type):
    """Фаза 1: транскрибация + выравнивание слов."""
    import whisperx

    print(f"Загрузка модели {model_name} ({device})...")
    model = whisperx.load_model(model_name, device, compute_type=compute_type,
                                language="ru")

    print("Транскрибация...")
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=16, print_progress=True)

    # Освобождаем GPU
    del model
    _free_gpu()

    # Выравнивание по словам
    print("Выравнивание таймкодов...")
    model_a, metadata = whisperx.load_align_model(language_code="ru", device=device)
    result = whisperx.align(result["segments"], model_a, metadata, audio, device)

    del model_a
    _free_gpu()

    return audio, result


# ── Фаза 2: диаризация ───────────────────────────────────────────


def diarize(audio, result, hf_token, num_speakers, device):
    """Фаза 2: определение спикеров и присвоение слов."""
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    print(f"Диаризация (ожидаем спикеров: {num_speakers})...")
    diarize_model = DiarizationPipeline(token=hf_token, device=device)
    diarize_segments = diarize_model(
        audio,
        min_speakers=num_speakers,
        max_speakers=num_speakers,
    )

    del diarize_model
    _free_gpu()

    result = whisperx.assign_word_speakers(diarize_segments, result,
                                           fill_nearest=True)

    # Проверить сколько спикеров нашли
    speakers_found = set()
    for seg in result["segments"]:
        if "speaker" in seg:
            speakers_found.add(seg["speaker"])

    print(f"Найдено спикеров: {len(speakers_found)}")
    if len(speakers_found) != num_speakers:
        print(f"  Предупреждение: ожидалось {num_speakers}, найдено {len(speakers_found)}")

    return result, sorted(speakers_found)


# ── Фаза 3: форматирование и вывод ───────────────────────────────


def merge_segments(segments):
    """Склеить смежные сегменты одного спикера в блоки."""
    if not segments:
        return []

    blocks = []
    current = {
        "speaker": segments[0].get("speaker", "?"),
        "start": segments[0]["start"],
        "end": segments[0]["end"],
        "text": segments[0].get("text", ""),
        "words": list(segments[0].get("words", [])),
    }

    for seg in segments[1:]:
        spk = seg.get("speaker", "?")
        if spk == current["speaker"]:
            current["end"] = seg["end"]
            current["text"] += " " + seg.get("text", "")
            current["words"].extend(seg.get("words", []))
        else:
            blocks.append(current)
            current = {
                "speaker": spk,
                "start": seg["start"],
                "end": seg["end"],
                "text": seg.get("text", ""),
                "words": list(seg.get("words", [])),
            }

    blocks.append(current)
    return blocks


def build_speaker_map(speakers):
    """SPEAKER_00 → Спикер 1, SPEAKER_01 → Спикер 2, ..."""
    return {spk: f"Спикер {i + 1}" for i, spk in enumerate(speakers)}


def format_time(seconds):
    """Секунды → HH:MM:SS или MM:SS."""
    s = int(seconds)
    h, remainder = divmod(s, 3600)
    m, sec = divmod(remainder, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def save_txt(blocks, speaker_map, source_name, duration, output_path):
    """Сохранить расшифровку в TXT."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"Расшифровка: {source_name}\n")
        f.write(f"Дата: {date.today().isoformat()}\n")
        f.write(f"Спикеры: {len(speaker_map)}\n")
        f.write(f"Длительность: {format_time(duration)}\n")
        f.write(f"\n{'─' * 40}\n")

        for block in blocks:
            spk = speaker_map.get(block["speaker"], block["speaker"])
            t1 = format_time(block["start"])
            t2 = format_time(block["end"])
            f.write(f"\n[{t1} → {t2}] {spk}:\n")
            f.write(f"{block['text'].strip()}\n")

        f.write(f"\n{'─' * 40}\n")

    print(f"  TXT: {output_path}")


def save_json(blocks, speaker_map, source_name, duration, output_path):
    """Сохранить расшифровку в JSON."""
    data = {
        "source": source_name,
        "date": date.today().isoformat(),
        "duration": round(duration, 2),
        "speakers_count": len(speaker_map),
        "segments": [],
    }

    for block in blocks:
        seg = {
            "speaker": speaker_map.get(block["speaker"], block["speaker"]),
            "start": round(block["start"], 2),
            "end": round(block["end"], 2),
            "text": block["text"].strip(),
            "words": [
                {
                    "word": w.get("word", ""),
                    "start": round(w.get("start", 0), 2),
                    "end": round(w.get("end", 0), 2),
                }
                for w in block["words"]
                if "word" in w
            ],
        }
        data["segments"].append(seg)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  JSON: {output_path}")


# ── Сборка: process_file и main ──────────────────────────────────


def get_duration(filepath):
    """Получить длительность файла через ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def get_output_paths(filepath, output_arg):
    """Определить пути для TXT и JSON."""
    if output_arg:
        out_dir = Path(output_arg)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = filepath.parent

    stem = filepath.stem
    return (
        out_dir / f"{stem}.transcript.txt",
        out_dir / f"{stem}.transcript.json",
    )


def process_file(filepath, args, device, compute_type, token):
    """Обработать один файл: транскрибация → диаризация → вывод."""
    print(f"\n{'─' * 50}")
    print(f"Файл: {filepath.name}")
    print(f"{'─' * 50}")

    try:
        duration = get_duration(filepath)
        print(f"Длительность: {format_time(duration)}")
    except Exception:
        print("Предупреждение: не удалось определить длительность.")
        duration = 0.0

    # Фаза 1: транскрибация
    audio, result = transcribe(filepath, args.model, device, compute_type)

    # Фаза 2: диаризация
    result, speakers = diarize(audio, result, token, args.speakers, device)

    # Фаза 3: форматирование и вывод
    speaker_map = build_speaker_map(speakers)
    blocks = merge_segments(result["segments"])

    txt_path, json_path = get_output_paths(filepath, args.output)
    save_txt(blocks, speaker_map, filepath.name, duration, txt_path)
    save_json(blocks, speaker_map, filepath.name, duration, json_path)

    print(f"\nГотово: {len(blocks)} блоков, {len(speakers)} спикеров")


def main():
    args = parse_args()
    token = get_hf_token(args)

    files = collect_files(args.input)
    if not files:
        print("Нет файлов для обработки.")
        sys.exit(1)

    print(f"Файлов: {len(files)}, спикеров: {args.speakers}")

    device, compute_type = detect_device()

    for filepath in files:
        try:
            process_file(filepath, args, device, compute_type, token)
        except KeyboardInterrupt:
            print("\nПрервано пользователем.")
            sys.exit(1)
        except Exception as e:
            print(f"Ошибка при обработке {filepath.name}: {e}")
            continue


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)  # avoid CUDA teardown crash
