# Рефакторинг структуры проекта — План имплементации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Очистить проект от мусора, вынести build_xml.py в generic-скрипт с автодетектом через ffprobe.

**Architecture:** Generic `_scripts/build_xml.py` принимает путь к проекту, сканирует `raw/` для медиафайлов, снимает метаданные через ffprobe, читает `script/script.csv`, генерирует FCP XML. Остальное — удаление мусора и перемещение документов.

**Tech Stack:** Python 3, ffprobe, xml.etree.ElementTree, pathlib

---

### Task 1: Создать `_scripts/build_xml.py` — ffprobe и сканирование файлов

**Files:**
- Create: `_scripts/build_xml.py`

**Step 1: Написать функцию `probe_file(path)` — получение метаданных через ffprobe**

```python
#!/usr/bin/env python3
"""Генерирует FCP XML черновой сборки из script.csv для импорта в Premiere Pro.

Использование:
    python _scripts/build_xml.py <project_dir>
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

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi"}


def probe_file(path: Path) -> dict:
    """Получает метаданные медиафайла через ffprobe.

    Возвращает dict с ключами: width, height, timebase, ntsc,
    sample_rate, channels, duration_sec.
    """
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)

    # Видео-стрим
    vid = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    # Аудио-стрим
    aud = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)

    width = int(vid["width"]) if vid else 1920
    height = int(vid["height"]) if vid else 1080

    # FPS: r_frame_rate = "24000/1001" или "25/1"
    fps_num, fps_den = 30, 1
    if vid and "r_frame_rate" in vid:
        parts = vid["r_frame_rate"].split("/")
        fps_num, fps_den = int(parts[0]), int(parts[1]) if len(parts) > 1 else 1

    # NTSC: 24000/1001, 30000/1001, 60000/1001
    ntsc = fps_den == 1001
    timebase = round(fps_num / fps_den) if not ntsc else fps_num // 1000

    sample_rate = int(aud.get("sample_rate", 48000)) if aud else 48000
    channels = int(aud.get("channels", 2)) if aud else 2

    duration_sec = float(data["format"].get("duration", 0))

    return {
        "width": width, "height": height,
        "timebase": timebase, "ntsc": ntsc,
        "sample_rate": sample_rate, "channels": channels,
        "duration_sec": duration_sec,
    }
```

**Step 2: Написать функцию `scan_project(project_dir)` — поиск и probe всех медиафайлов**

```python
def scan_project(project_dir: Path) -> dict[str, dict]:
    """Сканирует raw/voiceover/ и raw/interviews/, возвращает FILES dict.

    Ключ = имя файла в нижнем регистре без расширения для voiceover,
    или полное имя в нижнем регистре для interviews.
    """
    files = {}
    filename_to_key = {}

    for subdir, role in [("raw/voiceover", "voiceover"), ("raw/interviews", "interview")]:
        dir_path = project_dir / subdir
        if not dir_path.exists():
            continue
        for f in sorted(dir_path.iterdir()):
            if f.suffix.lower() not in VIDEO_EXTS:
                continue
            print(f"  Probe: {f.name}...")
            info = probe_file(f)
            info["path"] = f
            info["role"] = role

            key = "voiceover" if role == "voiceover" else f.stem.lower()
            files[key] = info
            filename_to_key[f.name] = key

    return files, filename_to_key
```

**Step 3: Проверить scan на tulips**

Запустить: `python -c "from pathlib import Path; exec(open('_scripts/build_xml.py').read()); files, fmap = scan_project(Path('projects/tulips')); print(json.dumps({k: {kk: str(vv) for kk, vv in v.items()} for k, v in files.items()}, indent=2, ensure_ascii=False))"`

Ожидаемый результат: dict с 4 файлами (voiceover + 3 интервью), метаданные совпадают с захардкоженными в старом build_xml.py.

**Step 4: Коммит**

```bash
git add _scripts/build_xml.py
git commit -m "feat(build_xml): скелет скрипта — ffprobe и сканирование проекта"
```

---

### Task 2: FCP XML генерация — перенос из проектных скриптов

**Files:**
- Modify: `_scripts/build_xml.py`

**Step 1: Перенести вспомогательные функции XML-генерации**

Из `projects/tulips/assembly/build_xml.py` скопировать без изменений:
- `path_to_url(p, relative)` (строка 156-172)
- `make_rate_el(parent, timebase, ntsc)` (строка 175-179)
- `make_file_el(parent, file_id, file_info, define, relative)` (строка 182-212)

**Step 2: Перенести `build_xml(clips, files, seq_config, seq_name, relative)`**

Взять `build_xml()` из thermobags-версии (чище, без legacy-хаков tulips). Изменения:
- Добавить параметры `files`, `seq_config`, `seq_name` вместо глобалов
- `FILES[file_key]` → `files[file_key]`
- `SEQ_TIMEBASE` → `seq_config["timebase"]`
- Имя секвенции из параметра

```python
def sec_to_frames(seconds: float, fps: float) -> int:
    """Конвертирует секунды в кадры."""
    return round(seconds * fps)


def build_xml(clips, files, seq_config, seq_name, relative=False):
    """Собирает FCP XML из списка клипов.

    seq_config: dict с ключами timebase, ntsc, fps, width, height.
    """
    # ... (код из thermobags-версии с параметризацией)
```

**Step 3: Перенести парсинг таймкодов и main()**

Взять `parse_tc`, `parse_unified_tc` из thermobags (чище). Написать `main()`:

```python
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
    """Парсит 'filename.ext, MM:SS.ss -> MM:SS.ss' → (file_key, start, end) или None."""
    tc_str = tc_str.strip()
    if not tc_str or "->" not in tc_str or "," not in tc_str:
        return None
    comma_idx = tc_str.index(",")
    filename = tc_str[:comma_idx].strip()
    tc_part = tc_str[comma_idx + 1:].strip()
    parts = tc_part.split("->")
    if len(parts) != 2:
        return None
    file_key = filename_to_key.get(filename)
    if not file_key:
        print(f"  WARN: неизвестный файл '{filename}'")
        return None
    return file_key, parse_tc(parts[0]), parse_tc(parts[1])


def main():
    parser = argparse.ArgumentParser(description="Генерация FCP XML из script.csv")
    parser.add_argument("project_dir", type=Path, help="Путь к папке проекта")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    project_name = project_dir.name
    print(f"=== Сборка XML: {project_name} ===\n")

    # Сканируем медиафайлы
    files, filename_to_key = scan_project(project_dir)
    print(f"  Найдено файлов: {len(files)}\n")

    # Определяем параметры секвенции по первому интервью
    interview = next((f for f in files.values() if f["role"] == "interview"), None)
    if interview:
        seq_timebase = interview["timebase"]
        seq_ntsc = interview["ntsc"]
    else:
        seq_timebase, seq_ntsc = 25, False

    seq_fps = seq_timebase * (1000 / 1001 if seq_ntsc else 1)
    seq_config = {
        "timebase": seq_timebase, "ntsc": seq_ntsc, "fps": seq_fps,
        "width": 1920, "height": 1080,
    }

    # Читаем сценарий
    csv_path = project_dir / "script" / "script.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    print(f"Строк в сценарии: {len(rows) - 1}")

    # Собираем клипы
    clips = []
    cursor = 0
    slava_count = hero_count = 0
    skipped = []

    for row_idx in range(1, len(rows)):
        row = rows[row_idx]
        while len(row) < 4:
            row.append("")

        slava_text, slava_tc = row[0].strip(), row[1].strip()
        hero_text, hero_tc = row[2].strip(), row[3].strip()

        if slava_text.startswith("ЭПИЗОД"):
            continue

        for text, tc, track in [(slava_text, slava_tc, "slava"), (hero_text, hero_tc, "hero")]:
            if not text or not tc:
                continue
            parsed = parse_unified_tc(tc, filename_to_key)
            if not parsed:
                skipped.append((row_idx + 1, f"{track}: {tc[:60]}"))
                continue
            file_key, src_start, src_end = parsed
            duration_frames = sec_to_frames(src_end - src_start, seq_fps)
            if duration_frames > 0:
                clips.append({
                    "track": track,
                    "file_key": file_key,
                    "name": text[:60],
                    "src_start": src_start,
                    "src_end": src_end,
                    "seq_start": cursor,
                    "seq_end": cursor + duration_frames,
                    "row": row_idx + 1,
                })
                cursor += duration_frames
                if track == "slava":
                    slava_count += 1
                else:
                    hero_count += 1

    print(f"\nКлипов Славы: {slava_count}")
    print(f"Клипов героя: {hero_count}")
    print(f"Всего клипов: {len(clips)}")

    total_sec = cursor / seq_fps
    print(f"Длительность таймлайна: {int(total_sec) // 60}:{int(total_sec) % 60:02d}")

    if skipped:
        print(f"\nПропущено ({len(skipped)}):")
        for line_no, tc in skipped:
            print(f"  Строка {line_no}: {tc}")

    # Генерируем XML
    seq_name = f"{project_name} — черновая сборка"
    out_dir = project_dir / "assembly"
    out_dir.mkdir(parents=True, exist_ok=True)

    for relative, suffix in [(False, "_local"), (True, "")]:
        xmeml = build_xml(clips, files, seq_config, seq_name, relative=relative)
        rough = ET.tostring(xmeml, encoding="unicode", xml_declaration=False)
        dom = minidom.parseString(rough)
        pretty = dom.toprettyxml(indent="  ")
        lines = pretty.split("\n")
        if lines[0].startswith("<?xml"):
            lines = lines[1:]
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + "\n".join(lines)

        out_path = out_dir / f"{project_name}_rough_cut{suffix}.xml"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml_str)
        label = "абсолютные пути (локальный)" if suffix == "_local" else "относительные пути (для zip)"
        print(f"Сохранено ({label}): {out_path}")


if __name__ == "__main__":
    main()
```

**Step 4: Проверить на tulips**

```bash
python _scripts/build_xml.py projects/tulips
```

Ожидаемый результат: генерирует XML, выводит количество клипов Славы/героя, длительность.
Сравнить количество клипов с выводом старого скрипта (запустить старый отдельно).

**Step 5: Проверить на thermobags**

```bash
python _scripts/build_xml.py projects/2026-03-thermobags
```

Ожидаемый результат: аналогично tulips — XML генерируется, количество клипов совпадает.

**Step 6: Коммит**

```bash
git add _scripts/build_xml.py
git commit -m "feat(build_xml): generic-скрипт с ffprobe-автодетектом"
```

---

### Task 3: Удаление мусора из проектов

**Files:**
- Delete: см. списки ниже

**Step 1: Удалить устаревшие скрипты из tulips**

```bash
rm projects/tulips/script/match_timecodes.py
rm projects/tulips/script/merge_verified.py
```

**Step 2: Удалить промежуточные артефакты из tulips**

```bash
rm projects/tulips/script/chunk_*.json
rm projects/tulips/script/*_context.txt
```

**Step 3: Удалить устаревшие скрипты из thermobags**

```bash
rm projects/2026-03-thermobags/script/_merge_verified.py
```

**Step 4: Удалить промежуточные артефакты из thermobags**

```bash
rm projects/2026-03-thermobags/script/_chunk*.json
rm projects/2026-03-thermobags/script/_verify_*.json
rm projects/2026-03-thermobags/script/_hero_rows.json
rm projects/2026-03-thermobags/script/_slava_rows.json
rm projects/2026-03-thermobags/script/_unverified.json
```

**Step 5: Удалить проектные build_xml.py (заменены generic)**

```bash
rm projects/tulips/assembly/build_xml.py
rm projects/2026-03-thermobags/assembly/build_xml.py
```

**Step 6: Удалить все *.tmp.* файлы**

```bash
find . -name "*.tmp.*" -not -path "./.git/*" -delete
```

**Step 7: Коммит**

```bash
git add -A
git commit -m "refactor: удалить устаревшие скрипты и артефакты из проектов"
```

---

### Task 4: Очистка корня и перемещение документов

**Files:**
- Move: `audio*.txt` → `docs/notes/audio-process-call/`
- Move: `pipeline.md`, `youtube-script.md` → `docs/notes/`

**Step 1: Переместить audio-файлы**

```bash
mkdir -p docs/notes/audio-process-call
mv audio1343572807.txt docs/notes/audio-process-call/
mv audio1367966378.txt docs/notes/audio-process-call/
mv audio1375241478.txt docs/notes/audio-process-call/
```

**Step 2: Переместить pipeline.md и youtube-script.md**

```bash
mkdir -p docs/notes
mv pipeline.md docs/notes/
mv youtube-script.md docs/notes/
```

**Step 3: Коммит**

```bash
git add -A
git commit -m "refactor: переместить документы в docs/notes/"
```

---

### Task 5: Обновить CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Добавить build_xml.py в секцию Scripts**

Добавить после секции `match_timecodes.py`:

```markdown
### build_xml.py — генерация FCP XML для Premiere Pro

\`\`\`bash
python _scripts/build_xml.py <project_dir>
\`\`\`

Сканирует `raw/` проекта, снимает метаданные через `ffprobe`, читает `script/script.csv` с таймкодами, генерирует FCP 7 XML. Выход: `assembly/{name}_rough_cut.xml` (относительные пути) и `{name}_rough_cut_local.xml` (абсолютные).
```

**Step 2: Коммит**

```bash
git add CLAUDE.md
git commit -m "docs: добавить build_xml.py в CLAUDE.md"
```
