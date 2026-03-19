#!/usr/bin/env python3
"""Генерирует FCP XML черновой сборки из script.csv для импорта в Premiere Pro."""

import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- Конфигурация ---

BASE = Path(__file__).resolve().parent.parent
SCRIPT_CSV = BASE / "script" / "script.csv"
OUTPUT_XML = BASE / "assembly" / "tulips_rough_cut.xml"

# Секвенция: 23.976fps (timebase=24, ntsc=TRUE)
SEQ_TIMEBASE = 24
SEQ_NTSC = True
SEQ_FPS = 24000 / 1001  # 23.976...
SEQ_WIDTH = 1920
SEQ_HEIGHT = 1080

# Исходные файлы
FILES = {
    "voiceover": {
        "path": BASE / "raw" / "voiceover" / "1773574086.543356.mov",
        "width": 1280, "height": 720,
        "timebase": 30, "ntsc": False,
        "sample_rate": 44100, "channels": 2,
        "duration_sec": 1131.2,
    },
    "тюльпаны": {
        "path": BASE / "raw" / "interviews" / "Тюльпаны.mp4",
        "width": 1920, "height": 1080,
        "timebase": 24, "ntsc": True,
        "sample_rate": 48000, "channels": 1,
        "duration_sec": 5355.8,
    },
    "тюльпаны 2": {
        "path": BASE / "raw" / "interviews" / "Тюльпаны 2.mp4",
        "width": 1920, "height": 1080,
        "timebase": 24, "ntsc": True,
        "sample_rate": 48000, "channels": 1,
        "duration_sec": 4375.3,
    },
    "тюльпаны4": {
        "path": BASE / "raw" / "interviews" / "Тюльпаны4.mp4",
        "width": 1920, "height": 1080,
        "timebase": 24, "ntsc": True,
        "sample_rate": 48000, "channels": 1,
        "duration_sec": 3537.4,
    },
}


def sec_to_frames(seconds: float) -> int:
    """Конвертирует секунды в кадры секвенции (23.976fps)."""
    return round(seconds * SEQ_FPS)


def parse_tc(tc_str: str) -> float:
    """Парсит таймкод HH:MM:SS.ss или MM:SS.ss в секунды."""
    parts = tc_str.strip().split(":")
    parts = [p.strip() for p in parts]
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0


def parse_slava_tc(tc_str: str):
    """Парсит таймкод Славы: 'MM:SS -> MM:SS' → (start_sec, end_sec).

    Совместимость со старым форматом (без имени файла).
    """
    tc_str = tc_str.strip()
    if not tc_str or "->" not in tc_str:
        return None
    parts = tc_str.split("->")
    if len(parts) != 2:
        return None
    return parse_tc(parts[0]), parse_tc(parts[1])


# Маппинг имени файла → ключ в FILES
FILENAME_TO_KEY = {
    "1773574086.543356.mov": "voiceover",
    "тюльпаны.mp4": "тюльпаны",
    "тюльпаны 2.mp4": "тюльпаны 2",
    "тюльпаны4.mp4": "тюльпаны4",
}


def parse_unified_tc(tc_str: str):
    """Парсит единый формат: 'filename.ext, MM:SS.ss -> MM:SS.ss'.

    Возвращает (file_key, start_sec, end_sec) или None.
    Также поддерживает старые форматы героя (srt ссылки).
    """
    tc_str = tc_str.strip()
    if not tc_str:
        return None

    # Пропускаем VK-ссылки и не-интервью
    if "vkvideo" in tc_str or "http" in tc_str:
        return None
    if "Выгонка тюльпанов" in tc_str:
        return None

    # Новый формат: "filename.ext, MM:SS.ss -> MM:SS.ss"
    if "->" in tc_str and "," in tc_str:
        comma_idx = tc_str.index(",")
        filename = tc_str[:comma_idx].strip()
        tc_part = tc_str[comma_idx + 1:].strip()
        parts = tc_part.split("->")
        if len(parts) == 2:
            file_key = FILENAME_TO_KEY.get(filename.lower())
            if not file_key:
                print(f"  WARN: неизвестный файл '{filename}'")
                return None
            return file_key, parse_tc(parts[0]), parse_tc(parts[1])

    # Старый формат героя (srt ссылки и т.д.)
    tc_pattern = r'(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}(?:\.\d+)?)'
    timecodes = re.findall(tc_pattern, tc_str)

    file_pattern = r'тюльпан[ыа][\s_]*\d*'
    file_match = re.search(file_pattern, tc_str, re.IGNORECASE)

    if not file_match:
        return None

    name = file_match.group().lower().strip().replace("_", " ").replace(".srt", "")
    name = name.rstrip(".")
    if name == "тюльпаны 4":
        name = "тюльпаны4"
    if name not in FILES:
        print(f"  WARN: неизвестный файл '{name}' из '{tc_str}'")
        return None

    if len(timecodes) >= 2:
        return name, parse_tc(timecodes[0]), parse_tc(timecodes[1])
    elif len(timecodes) == 1:
        start = parse_tc(timecodes[0])
        return name, start, start + 15

    return None


def path_to_url(p: Path, relative: bool = False) -> str:
    """Конвертирует путь в file:// URL.

    relative=True: только имя файла (для zip-архива, где всё в одной папке).
    relative=False: абсолютный путь (для локальной работы).
    """
    from urllib.parse import quote

    if relative:
        return p.name
    else:
        abs_path = p.resolve()
        posix = str(abs_path).replace("\\", "/")
        if posix[1] == ":":
            posix = "/" + posix
        posix = quote(posix, safe="/:@")
        return f"file://localhost{posix}"


def make_rate_el(parent, timebase, ntsc):
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"
    return rate


def make_file_el(parent, file_id, file_info, define=True, relative=False):
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


def file_duration_in_seq_frames(file_info):
    """Длительность исходного файла в кадрах секвенции."""
    return sec_to_frames(file_info["duration_sec"])


def build_xml(clips, relative=False):
    """Собирает FCP XML из списка клипов."""

    xmeml = ET.Element("xmeml", version="5")
    seq = ET.SubElement(xmeml, "sequence", id="seq-1")
    ET.SubElement(seq, "name").text = "Тюльпаны — черновая сборка"

    # Длительность секвенции = конец последнего клипа
    if clips:
        seq_duration = max(c["seq_end"] for c in clips)
    else:
        seq_duration = 0
    ET.SubElement(seq, "duration").text = str(seq_duration)
    make_rate_el(seq, SEQ_TIMEBASE, SEQ_NTSC)

    media = ET.SubElement(seq, "media")

    # --- Video ---
    video = ET.SubElement(media, "video")
    fmt = ET.SubElement(video, "format")
    sc = ET.SubElement(fmt, "samplecharacteristics")
    make_rate_el(sc, SEQ_TIMEBASE, SEQ_NTSC)
    ET.SubElement(sc, "width").text = str(SEQ_WIDTH)
    ET.SubElement(sc, "height").text = str(SEQ_HEIGHT)
    ET.SubElement(sc, "anamorphic").text = "FALSE"
    ET.SubElement(sc, "pixelaspectratio").text = "square"
    ET.SubElement(sc, "fielddominance").text = "none"

    v_track_slava = ET.SubElement(video, "track")  # V1 — Слава
    v_track_hero = ET.SubElement(video, "track")   # V2 — Герой

    # --- Audio ---
    audio = ET.SubElement(media, "audio")
    a_fmt = ET.SubElement(audio, "format")
    a_sc = ET.SubElement(a_fmt, "samplecharacteristics")
    ET.SubElement(a_sc, "depth").text = "16"
    ET.SubElement(a_sc, "samplerate").text = "48000"

    a_track_slava = ET.SubElement(audio, "track")  # A1 — Слава
    a_track_hero = ET.SubElement(audio, "track")   # A2 — Герой

    # Трекаем, какие файлы уже определили
    defined_files = set()

    # Счётчик клипов на треке для clipindex (раздельный для каждого трека)
    v_clipindex_slava = 0
    v_clipindex_hero = 0
    a_clipindex_slava = 0
    a_clipindex_hero = 0

    clip_id = 0

    for clip in clips:
        clip_id += 1
        track_type = clip["track"]  # "slava" или "hero"
        file_key = clip["file_key"]
        file_info = FILES[file_key]
        file_id = f"file-{file_key.replace(' ', '_')}"
        masterclip_id = f"masterclip-{file_key.replace(' ', '_')}"

        start_frames = clip["seq_start"]
        end_frames = clip["seq_end"]
        in_frames = sec_to_frames(clip["src_start"])
        out_frames = sec_to_frames(clip["src_end"])
        src_duration = file_duration_in_seq_frames(file_info)

        is_first_def = file_id not in defined_files

        v_clip_id = f"v-clip-{clip_id}"
        a_clip_id = f"a-clip-{clip_id}"

        # Выбираем трек и clipindex по спикеру
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
        make_rate_el(v_clip, SEQ_TIMEBASE, SEQ_NTSC)
        ET.SubElement(v_clip, "in").text = str(in_frames)
        ET.SubElement(v_clip, "out").text = str(out_frames)
        ET.SubElement(v_clip, "start").text = str(start_frames)
        ET.SubElement(v_clip, "end").text = str(end_frames)

        make_file_el(v_clip, file_id, file_info, define=is_first_def, relative=relative)

        # sourcetrack
        st = ET.SubElement(v_clip, "sourcetrack")
        ET.SubElement(st, "mediatype").text = "video"

        # link к аудио
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
        make_rate_el(a_clip, SEQ_TIMEBASE, SEQ_NTSC)
        ET.SubElement(a_clip, "in").text = str(in_frames)
        ET.SubElement(a_clip, "out").text = str(out_frames)
        ET.SubElement(a_clip, "start").text = str(start_frames)
        ET.SubElement(a_clip, "end").text = str(end_frames)

        make_file_el(a_clip, file_id, file_info, define=False, relative=relative)

        # sourcetrack
        st = ET.SubElement(a_clip, "sourcetrack")
        ET.SubElement(st, "mediatype").text = "audio"
        ET.SubElement(st, "trackindex").text = track_index

        # link к видео
        link = ET.SubElement(a_clip, "link")
        ET.SubElement(link, "linkclipref").text = v_clip_id
        ET.SubElement(link, "mediatype").text = "video"
        ET.SubElement(link, "trackindex").text = track_index
        ET.SubElement(link, "clipindex").text = str(v_clipindex)

        defined_files.add(file_id)

    return xmeml


def main():
    # Читаем сценарий
    with open(SCRIPT_CSV, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    print(f"Строк в сценарии: {len(rows) - 1}")

    # Собираем клипы в порядке сценария
    clips = []
    cursor_slava = 0  # позиция на таймлайне для трека Славы
    cursor_hero = 0   # позиция на таймлайне для трека героя

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

        # Пропускаем пустые строки и заголовки
        if slava_text.startswith("ЭПИЗОД"):
            continue

        # Реплика Славы
        if slava_text and slava_tc:
            parsed = parse_unified_tc(slava_tc)
            if parsed:
                file_key, src_start, src_end = parsed
            else:
                # Fallback: старый формат без имени файла
                tc = parse_slava_tc(slava_tc)
                if tc:
                    file_key = "voiceover"
                    src_start, src_end = tc
                    parsed = True
            if parsed:
                duration_frames = sec_to_frames(src_end - src_start)
                if duration_frames > 0:
                    clips.append({
                        "track": "slava",
                        "file_key": file_key,
                        "name": slava_text[:60],
                        "src_start": src_start,
                        "src_end": src_end,
                        "seq_start": cursor_slava,
                        "seq_end": cursor_slava + duration_frames,
                        "row": row_idx + 1,
                    })
                    cursor_slava += duration_frames
                    slava_count += 1

        # Реплика героя
        if hero_text and hero_tc:
            parsed = parse_unified_tc(hero_tc)
            if parsed:
                file_key, src_start, src_end = parsed
                duration_frames = sec_to_frames(src_end - src_start)
                if duration_frames > 0:
                    clips.append({
                        "track": "hero",
                        "file_key": file_key,
                        "name": hero_text[:60],
                        "src_start": src_start,
                        "src_end": src_end,
                        "seq_start": cursor_hero,
                        "seq_end": cursor_hero + duration_frames,
                        "row": row_idx + 1,
                    })
                    cursor_hero += duration_frames
                    hero_count += 1
            else:
                if hero_tc and "http" not in hero_tc and "vkvideo" not in hero_tc and "Выгонка" not in hero_tc:
                    skipped.append((row_idx + 1, hero_tc[:60]))

    print(f"\nКлипов Славы: {slava_count}")
    print(f"Клипов героя: {hero_count}")
    print(f"Всего клипов: {len(clips)}")

    total_sec = max(cursor_slava, cursor_hero) / SEQ_FPS
    total_min = int(total_sec) // 60
    total_s = int(total_sec) % 60
    print(f"Длительность таймлайна: {total_min}:{total_s:02d}")

    if skipped:
        print(f"\nПропущено ({len(skipped)}):")
        for line_no, tc in skipped:
            print(f"  Строка {line_no}: {tc}")

    OUTPUT_XML.parent.mkdir(parents=True, exist_ok=True)

    # Генерируем оба варианта
    for relative, suffix in [(False, "_local"), (True, "")]:
        xmeml = build_xml(clips, relative=relative)

        rough = ET.tostring(xmeml, encoding="unicode", xml_declaration=False)
        dom = minidom.parseString(rough)
        pretty = dom.toprettyxml(indent="  ")
        lines = pretty.split("\n")
        if lines[0].startswith("<?xml"):
            lines = lines[1:]
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + "\n".join(lines)

        out_path = OUTPUT_XML.parent / f"tulips_rough_cut{suffix}.xml"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml_str)

        label = "относительные пути (для zip)" if not suffix else "абсолютные пути (локальный)"
        print(f"Сохранено ({label}): {out_path}")


if __name__ == "__main__":
    main()
