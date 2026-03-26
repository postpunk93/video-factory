#!/usr/bin/env python3
"""Генерирует FCP 7 XML черновой сборки из script.csv для импорта в Premiere Pro.

Использование:
    python _scripts/build_xml.py <project_dir>

Сканирует raw/voiceover/ и raw/interviews/, получает метаданные через ffprobe,
читает script/script.csv и генерирует XML в assembly/.
"""

import argparse
import csv
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote
from xml.dom import minidom

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------

def probe_file(path: Path) -> dict:
    """Получает метаданные медиафайла через ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe ошибка для {path}: {result.stderr}")
    data = json.loads(result.stdout)

    info = {
        "path": path,
        "width": 0, "height": 0,
        "timebase": 25, "ntsc": False,
        "sample_rate": 48000, "channels": 2,
        "duration_sec": 0.0,
    }

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            info["width"] = int(stream.get("width", 0))
            info["height"] = int(stream.get("height", 0))

            # fps / NTSC detection
            r_frame_rate = stream.get("r_frame_rate", "25/1")
            num, den = (int(x) for x in r_frame_rate.split("/"))
            if den == 1001:
                # NTSC: 24000/1001 → timebase=24, ntsc=True
                info["ntsc"] = True
                info["timebase"] = num // 1000
            else:
                info["ntsc"] = False
                info["timebase"] = num // den if den else num

            duration = stream.get("duration")
            if duration:
                info["duration_sec"] = float(duration)

        elif codec_type == "audio":
            info["sample_rate"] = int(stream.get("sample_rate", 48000))
            info["channels"] = int(stream.get("channels", 2))

            # Если видео-трек не дал duration, берём из аудио
            if not info["duration_sec"]:
                duration = stream.get("duration")
                if duration:
                    info["duration_sec"] = float(duration)

    # Финальный fallback: duration из format (контейнер)
    if not info["duration_sec"]:
        fmt_duration = data.get("format", {}).get("duration")
        if fmt_duration:
            info["duration_sec"] = float(fmt_duration)

    return info


# ---------------------------------------------------------------------------
# Сканирование проекта
# ---------------------------------------------------------------------------

def scan_project(project_dir: Path) -> tuple[dict, dict, dict]:
    """Сканирует raw/voiceover/ и raw/interviews/.

    Возвращает (files_dict, filename_to_key, seq_settings).
    """
    files = {}
    filename_to_key = {}

    voiceover_dir = project_dir / "raw" / "voiceover"
    interviews_dir = project_dir / "raw" / "interviews"

    first_interview_info = None

    # Voiceover files
    voiceover_count = 0
    if voiceover_dir.exists():
        for f in sorted(voiceover_dir.iterdir()):
            if f.suffix.lower() in VIDEO_EXTENSIONS:
                voiceover_count += 1
                if voiceover_count > 1:
                    print(f"  WARN: несколько voiceover-файлов, используется последний: {f.name}")
                print(f"  Сканирую: {f.name}")
                info = probe_file(f)
                key = "voiceover"
                files[key] = info
                filename_to_key[f.name] = key

    # Interview files
    if interviews_dir.exists():
        for f in sorted(interviews_dir.iterdir()):
            if f.suffix.lower() in VIDEO_EXTENSIONS:
                print(f"  Сканирую: {f.name}")
                info = probe_file(f)
                key = f.stem.lower()
                files[key] = info
                filename_to_key[f.name] = key

                if first_interview_info is None:
                    first_interview_info = info

    # Определяем параметры секвенции из первого интервью
    if first_interview_info:
        seq_timebase = first_interview_info["timebase"]
        seq_ntsc = first_interview_info["ntsc"]
    else:
        seq_timebase = 25
        seq_ntsc = False

    seq_fps = seq_timebase * (1000 / 1001 if seq_ntsc else 1.0)

    seq_settings = {
        "timebase": seq_timebase,
        "ntsc": seq_ntsc,
        "fps": seq_fps,
        "width": 1920,
        "height": 1080,
    }

    return files, filename_to_key, seq_settings


# ---------------------------------------------------------------------------
# Таймкоды
# ---------------------------------------------------------------------------

def parse_tc(tc_str: str) -> float:
    """Парсит таймкод HH:MM:SS.ss или MM:SS.ss в секунды."""
    parts = tc_str.strip().split(":")
    parts = [p.strip() for p in parts]
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0


def parse_unified_tc(tc_str: str, filename_to_key: dict):
    """Парсит формат: 'filename.ext, MM:SS.ss -> MM:SS.ss'.

    Возвращает (file_key, start_sec, end_sec) или None.
    """
    tc_str = tc_str.strip()
    if not tc_str or "->" not in tc_str or "," not in tc_str:
        return None

    comma_idx = tc_str.index(",")
    filename = tc_str[:comma_idx].strip()
    tc_part = tc_str[comma_idx + 1:].strip()
    parts = tc_part.split("->")
    if len(parts) != 2:
        return None

    # Пробуем точное совпадение, потом lowercase
    file_key = filename_to_key.get(filename)
    if not file_key:
        file_key = filename_to_key.get(filename.lower())
    if not file_key:
        # Поиск по lowercase имени
        lower_map = {k.lower(): v for k, v in filename_to_key.items()}
        file_key = lower_map.get(filename.lower())
    if not file_key:
        print(f"  WARN: неизвестный файл '{filename}'")
        return None

    return file_key, parse_tc(parts[0]), parse_tc(parts[1])


# ---------------------------------------------------------------------------
# FCP XML helpers
# ---------------------------------------------------------------------------

def sec_to_frames(seconds: float, seq_fps: float) -> int:
    """Конвертирует секунды в кадры секвенции."""
    return round(seconds * seq_fps)


def path_to_url(p: Path, relative: bool = False) -> str:
    """Конвертирует путь в file:// URL."""
    if relative:
        return p.name
    else:
        abs_path = p.resolve()
        posix = str(abs_path).replace("\\", "/")
        if len(posix) > 1 and posix[1] == ":":
            posix = "/" + posix
        posix = quote(posix, safe="/:@")
        return f"file://localhost{posix}"


def make_rate_el(parent, timebase, ntsc):
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"
    return rate


def make_file_el(parent, file_id, file_info, seq_fps, define=True, relative=False):
    """Создаёт <file> элемент. define=True — полное определение, False — ссылка."""
    file_el = ET.SubElement(parent, "file", id=file_id)
    if not define:
        return file_el

    ET.SubElement(file_el, "name").text = file_info["path"].stem
    ET.SubElement(file_el, "pathurl").text = path_to_url(file_info["path"], relative=relative)

    make_rate_el(file_el, file_info["timebase"], file_info["ntsc"])

    src_fps = file_info["timebase"] * (1000 / 1001 if file_info["ntsc"] else 1)
    ET.SubElement(file_el, "duration").text = str(round(file_info["duration_sec"] * src_fps))

    media = ET.SubElement(file_el, "media")

    vid = ET.SubElement(media, "video")
    vid_sc = ET.SubElement(vid, "samplecharacteristics")
    make_rate_el(vid_sc, file_info["timebase"], file_info["ntsc"])
    ET.SubElement(vid_sc, "width").text = str(file_info["width"])
    ET.SubElement(vid_sc, "height").text = str(file_info["height"])
    ET.SubElement(vid_sc, "anamorphic").text = "FALSE"
    ET.SubElement(vid_sc, "pixelaspectratio").text = "square"
    ET.SubElement(vid_sc, "fielddominance").text = "none"

    aud = ET.SubElement(media, "audio")
    aud_sc = ET.SubElement(aud, "samplecharacteristics")
    ET.SubElement(aud_sc, "depth").text = "16"
    ET.SubElement(aud_sc, "samplerate").text = str(file_info["sample_rate"])

    return file_el


# ---------------------------------------------------------------------------
# Сборка XML
# ---------------------------------------------------------------------------

def build_xml(clips, files, seq_settings, seq_name, relative=False):
    """Собирает FCP XML из списка клипов."""
    seq_timebase = seq_settings["timebase"]
    seq_ntsc = seq_settings["ntsc"]
    seq_fps = seq_settings["fps"]

    xmeml = ET.Element("xmeml", version="5")
    seq = ET.SubElement(xmeml, "sequence", id="seq-1")
    ET.SubElement(seq, "name").text = seq_name

    if clips:
        seq_duration = max(c["seq_end"] for c in clips)
    else:
        seq_duration = 0
    ET.SubElement(seq, "duration").text = str(seq_duration)
    make_rate_el(seq, seq_timebase, seq_ntsc)

    media = ET.SubElement(seq, "media")

    # --- Video ---
    video = ET.SubElement(media, "video")
    fmt = ET.SubElement(video, "format")
    sc = ET.SubElement(fmt, "samplecharacteristics")
    make_rate_el(sc, seq_timebase, seq_ntsc)
    ET.SubElement(sc, "width").text = str(seq_settings["width"])
    ET.SubElement(sc, "height").text = str(seq_settings["height"])
    ET.SubElement(sc, "anamorphic").text = "FALSE"
    ET.SubElement(sc, "pixelaspectratio").text = "square"
    ET.SubElement(sc, "fielddominance").text = "none"

    v_track_slava = ET.SubElement(video, "track")   # V1 — Слава
    v_track_hero = ET.SubElement(video, "track")     # V2 — Герой

    # --- Audio ---
    audio = ET.SubElement(media, "audio")
    a_fmt = ET.SubElement(audio, "format")
    a_sc = ET.SubElement(a_fmt, "samplecharacteristics")
    ET.SubElement(a_sc, "depth").text = "16"
    ET.SubElement(a_sc, "samplerate").text = "48000"

    a_track_slava = ET.SubElement(audio, "track")   # A1 — Слава
    a_track_hero = ET.SubElement(audio, "track")     # A2 — Герой

    defined_files = set()

    v_clipindex_slava = 0
    v_clipindex_hero = 0
    a_clipindex_slava = 0
    a_clipindex_hero = 0

    clip_id = 0

    for clip in clips:
        clip_id += 1
        track_type = clip["track"]
        file_key = clip["file_key"]
        file_info = files[file_key]
        file_id = f"file-{file_key.replace(' ', '_')}"
        masterclip_id = f"masterclip-{file_key.replace(' ', '_')}"

        start_frames = clip["seq_start"]
        end_frames = clip["seq_end"]
        in_frames = sec_to_frames(clip["src_start"], seq_fps)
        out_frames = sec_to_frames(clip["src_end"], seq_fps)
        src_duration = sec_to_frames(file_info["duration_sec"], seq_fps)

        is_first_def = file_id not in defined_files

        v_clip_id = f"v-clip-{clip_id}"
        a_clip_id = f"a-clip-{clip_id}"

        if track_type == "slava":
            v_track_cur = v_track_slava
            a_track_cur = a_track_slava
            v_clipindex_slava += 1
            a_clipindex_slava += 1
            v_clipindex = v_clipindex_slava
            a_clipindex = a_clipindex_slava
            track_index = "1"
        else:
            v_track_cur = v_track_hero
            a_track_cur = a_track_hero
            v_clipindex_hero += 1
            a_clipindex_hero += 1
            v_clipindex = v_clipindex_hero
            a_clipindex = a_clipindex_hero
            track_index = "2"

        # --- Video clipitem ---
        v_clip = ET.SubElement(v_track_cur, "clipitem", id=v_clip_id)
        ET.SubElement(v_clip, "masterclipid").text = masterclip_id
        ET.SubElement(v_clip, "name").text = clip["name"][:60]
        ET.SubElement(v_clip, "enabled").text = "TRUE"
        ET.SubElement(v_clip, "duration").text = str(src_duration)
        make_rate_el(v_clip, seq_timebase, seq_ntsc)
        ET.SubElement(v_clip, "in").text = str(in_frames)
        ET.SubElement(v_clip, "out").text = str(out_frames)
        ET.SubElement(v_clip, "start").text = str(start_frames)
        ET.SubElement(v_clip, "end").text = str(end_frames)

        make_file_el(v_clip, file_id, file_info, seq_fps,
                     define=is_first_def, relative=relative)

        st = ET.SubElement(v_clip, "sourcetrack")
        ET.SubElement(st, "mediatype").text = "video"

        link = ET.SubElement(v_clip, "link")
        ET.SubElement(link, "linkclipref").text = a_clip_id
        ET.SubElement(link, "mediatype").text = "audio"
        ET.SubElement(link, "trackindex").text = track_index
        ET.SubElement(link, "clipindex").text = str(a_clipindex)

        # --- Audio clipitem ---
        a_clip = ET.SubElement(a_track_cur, "clipitem", id=a_clip_id)
        ET.SubElement(a_clip, "masterclipid").text = masterclip_id
        ET.SubElement(a_clip, "name").text = clip["name"][:60]
        ET.SubElement(a_clip, "enabled").text = "TRUE"
        ET.SubElement(a_clip, "duration").text = str(src_duration)
        make_rate_el(a_clip, seq_timebase, seq_ntsc)
        ET.SubElement(a_clip, "in").text = str(in_frames)
        ET.SubElement(a_clip, "out").text = str(out_frames)
        ET.SubElement(a_clip, "start").text = str(start_frames)
        ET.SubElement(a_clip, "end").text = str(end_frames)

        make_file_el(a_clip, file_id, file_info, seq_fps, define=False, relative=relative)

        st = ET.SubElement(a_clip, "sourcetrack")
        ET.SubElement(st, "mediatype").text = "audio"
        ET.SubElement(st, "trackindex").text = track_index

        link = ET.SubElement(a_clip, "link")
        ET.SubElement(link, "linkclipref").text = v_clip_id
        ET.SubElement(link, "mediatype").text = "video"
        ET.SubElement(link, "trackindex").text = track_index
        ET.SubElement(link, "clipindex").text = str(v_clipindex)

        defined_files.add(file_id)

    return xmeml


def xml_to_string(xmeml) -> str:
    """Конвертирует ElementTree в отформатированную XML-строку."""
    rough = ET.tostring(xmeml, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(rough)
    pretty = dom.toprettyxml(indent="  ")
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines = lines[1:]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Генерация FCP 7 XML черновой сборки из script.csv")
    parser.add_argument("project_dir", type=Path, help="Путь к папке проекта")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        print(f"Ошибка: директория не найдена: {project_dir}")
        sys.exit(1)

    script_csv = project_dir / "script" / "script.csv"
    if not script_csv.exists():
        print(f"Ошибка: script.csv не найден: {script_csv}")
        sys.exit(1)

    project_name = project_dir.name
    seq_name = f"{project_name} — черновая сборка"

    print(f"Проект: {project_name}")
    print(f"Сканирую медиафайлы...")

    files, filename_to_key, seq_settings = scan_project(project_dir)

    print(f"\nНайдено файлов: {len(files)}")
    for key, info in files.items():
        fps_str = f"{info['timebase']}{'(NTSC)' if info['ntsc'] else ''}fps"
        print(f"  {key}: {info['width']}x{info['height']}, {fps_str}, "
              f"{info['duration_sec']:.1f}с")

    print(f"\nСеквенция: {seq_settings['timebase']}fps"
          f"{' NTSC' if seq_settings['ntsc'] else ''}"
          f" ({seq_settings['fps']:.3f})")

    # Читаем сценарий
    with open(script_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    print(f"Строк в сценарии: {len(rows) - 1}")

    seq_fps = seq_settings["fps"]
    clips = []
    cursor = 0

    slava_count = 0
    hero_count = 0
    skipped = []

    for row_idx in range(1, len(rows)):
        row = rows[row_idx]
        while len(row) < 4:
            row.append("")

        slava_text = row[0].strip()
        slava_tc = row[1].strip()
        hero_text = row[2].strip()
        hero_tc = row[3].strip()

        if slava_text.startswith("ЭПИЗОД"):
            continue

        # Реплика Славы
        if slava_text and slava_tc:
            parsed = parse_unified_tc(slava_tc, filename_to_key)
            if parsed:
                file_key, src_start, src_end = parsed
                duration_frames = sec_to_frames(src_end - src_start, seq_fps)
                if duration_frames > 0:
                    clips.append({
                        "track": "slava",
                        "file_key": file_key,
                        "name": slava_text[:60],
                        "src_start": src_start,
                        "src_end": src_end,
                        "seq_start": cursor,
                        "seq_end": cursor + duration_frames,
                        "row": row_idx + 1,
                    })
                    cursor += duration_frames
                    slava_count += 1
            else:
                skipped.append((row_idx + 1, f"slava: {slava_tc[:60]}"))

        # Реплика героя
        if hero_text and hero_tc:
            parsed = parse_unified_tc(hero_tc, filename_to_key)
            if parsed:
                file_key, src_start, src_end = parsed
                duration_frames = sec_to_frames(src_end - src_start, seq_fps)
                if duration_frames > 0:
                    clips.append({
                        "track": "hero",
                        "file_key": file_key,
                        "name": hero_text[:60],
                        "src_start": src_start,
                        "src_end": src_end,
                        "seq_start": cursor,
                        "seq_end": cursor + duration_frames,
                        "row": row_idx + 1,
                    })
                    cursor += duration_frames
                    hero_count += 1
            else:
                skipped.append((row_idx + 1, f"hero: {hero_tc[:60]}"))

    print(f"\nКлипов Славы: {slava_count}")
    print(f"Клипов героя: {hero_count}")
    print(f"Всего клипов: {len(clips)}")

    total_sec = cursor / seq_fps
    total_min = int(total_sec) // 60
    total_s = int(total_sec) % 60
    print(f"Длительность таймлайна: {total_min}:{total_s:02d}")

    if skipped:
        print(f"\nПропущено ({len(skipped)}):")
        for line_no, tc in skipped:
            print(f"  Строка {line_no}: {tc}")

    # Сохранение XML
    assembly_dir = project_dir / "assembly"
    assembly_dir.mkdir(parents=True, exist_ok=True)

    for relative, suffix in [(False, "_local"), (True, "")]:
        xmeml = build_xml(clips, files, seq_settings, seq_name, relative=relative)
        xml_str = xml_to_string(xmeml)

        out_path = assembly_dir / f"{project_name}_rough_cut{suffix}.xml"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml_str)

        label = ("абсолютные пути (локальный)" if suffix == "_local"
                 else "относительные пути (для zip)")
        print(f"Сохранено ({label}): {out_path}")


if __name__ == "__main__":
    main()
