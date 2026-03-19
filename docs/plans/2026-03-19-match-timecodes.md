# match-timecodes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Многопроходное сопоставление реплик сценария с таймкодами в записях (начитка + интервью).

**Architecture:** Python-скрипт для алгоритмического поиска (проход 1) и snap to silence (проход 3). Агентная верификация (проход 2) — через Claude Code skill. Промежуточные данные — JSON-файлы.

**Tech Stack:** Python 3.10+, pathlib, csv, json, re, subprocess (ffmpeg silencedetect)

---

### Task 1: Скрипт match_timecodes.py — каркас и загрузка данных

**Files:**
- Create: `_scripts/match_timecodes.py`
- Reference: `projects/tulips/script/match_timecodes.py` (существующий, проектно-специфичный)
- Reference: `_scripts/transcribe.py` (формат transcript.json)

**Step 1: Создать скрипт с CLI**

```python
#!/usr/bin/env python3
"""Многопроходное сопоставление реплик сценария с таймкодами в записях.

Использование:
  python _scripts/match_timecodes.py search <project_dir>   # Проход 1: поиск кандидатов
  python _scripts/match_timecodes.py snap <project_dir>      # Проход 3: snap to silence
  python _scripts/match_timecodes.py compact <project_dir>   # Генерация words_compact.txt
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def parse_args():
    parser = argparse.ArgumentParser(description="Сопоставление реплик сценария с таймкодами")
    parser.add_argument("command", choices=["search", "snap", "compact"],
                        help="search=проход 1, snap=проход 3, compact=генерация words_compact.txt")
    parser.add_argument("project_dir", type=Path, help="Путь к папке проекта")
    return parser.parse_args()
```

**Step 2: Функции загрузки данных**

```python
def load_script(project_dir: Path) -> list[dict]:
    """Загружает script.csv, возвращает список реплик с метаданными."""
    csv_path = project_dir / "script" / "script.csv"
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row_idx, row in enumerate(reader, start=2):
            while len(row) < 4:
                row.append("")
            slava_text = row[0].strip()
            hero_text = row[2].strip()
            if slava_text and not slava_text.startswith("ЭПИЗОД"):
                rows.append({"row_idx": row_idx, "speaker": "slava", "text": slava_text, "col": 1})
            if hero_text and not hero_text.startswith("ЭПИЗОД"):
                rows.append({"row_idx": row_idx, "speaker": "hero", "text": hero_text, "col": 3})
    return rows


def load_transcripts(project_dir: Path) -> dict[str, dict]:
    """Загружает все transcript.json, возвращает {filename: {words, full_text, char_map}}."""
    transcripts = {}
    for json_path in (project_dir / "transcripts").glob("*.transcript.json"):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        source = data.get("source", json_path.stem.replace(".transcript", ""))
        words = []
        for seg in data["segments"]:
            words.extend(w for w in seg.get("words", []) if "word" in w)
        full_text, char_map = build_text_index(words)
        transcripts[source] = {
            "words": words,
            "full_text": full_text,
            "char_map": char_map,
            "json_path": str(json_path),
        }
    return transcripts
```

**Step 3: Проверить загрузку на реальных данных**

```bash
cd C:/Users/Alex/Videos/factory
python _scripts/match_timecodes.py search projects/tulips
```

Ожидаем: скрипт загружает CSV и транскрипты без ошибок, выводит количество реплик и транскриптов.

**Step 4: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match-timecodes): каркас скрипта — CLI, загрузка CSV и транскриптов"
```

---

### Task 2: Проход 1 — алгоритмический поиск кандидатов

**Files:**
- Modify: `_scripts/match_timecodes.py`

**Step 1: Функции нормализации и индексации**

Перенести из существующего `projects/tulips/script/match_timecodes.py`:

```python
def normalize(text: str) -> str:
    """Нижний регистр, ё→е, убираем пунктуацию."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_text_index(words: list[dict]) -> tuple[str, list[int]]:
    """Полный нормализованный текст + карта char→word_idx."""
    parts = []
    char_to_widx = []
    for i, w in enumerate(words):
        norm = normalize(w["word"])
        parts.append(norm)
        char_to_widx.extend([i] * (len(norm) + 1))  # +1 для пробела
    full_text = " ".join(parts)
    return full_text, char_to_widx
```

**Step 2: Поиск кандидатов — n-граммный алгоритм**

```python
def find_candidates(phrase: str, transcripts: dict[str, dict]) -> list[dict]:
    """Ищет фразу во всех транскриптах, возвращает всех кандидатов."""
    phrase_norm = normalize(phrase)
    pwords = phrase_norm.split()
    if len(pwords) < 3:
        return []

    all_candidates = []
    for filename, tr in transcripts.items():
        matches = []
        # N-граммы от 6 до 3
        for n in range(min(6, len(pwords)), 2, -1):
            for i in range(len(pwords) - n + 1):
                gram = " ".join(pwords[i : i + n])
                start = 0
                while True:
                    pos = tr["full_text"].find(gram, start)
                    if pos == -1:
                        break
                    if pos < len(tr["char_map"]):
                        widx = tr["char_map"][pos]
                        start_widx = max(0, widx - i)
                        end_widx = min(len(tr["words"]) - 1, start_widx + len(pwords) - 1)
                        start_time = tr["words"][start_widx].get("start", 0)
                        end_time = tr["words"][end_widx].get("end", 0)
                        # Схлопываем дубли ближе 5с
                        merged = False
                        for m in matches:
                            if abs(m["start"] - start_time) < 5:
                                if n > m["ngram_len"]:
                                    m.update(start=start_time, end=end_time,
                                             words_start=start_widx, words_end=end_widx,
                                             ngram_len=n)
                                merged = True
                                break
                        if not merged:
                            matches.append({
                                "file": filename,
                                "start": round(start_time, 2),
                                "end": round(end_time, 2),
                                "words_start": start_widx,
                                "words_end": end_widx,
                                "ngram_len": n,
                            })
                    start = pos + 1
            if matches:
                break
        all_candidates.extend(matches)
    return sorted(all_candidates, key=lambda c: c["start"])
```

**Step 3: Команда search — собрать candidates.json**

```python
def cmd_search(project_dir: Path):
    """Проход 1: алгоритмический поиск кандидатов."""
    rows = load_script(project_dir)
    transcripts = load_transcripts(project_dir)
    print(f"Реплик: {len(rows)}, транскриптов: {len(transcripts)}")

    # Определяем, какие транскрипты для какого спикера
    voiceover_dir = project_dir / "raw" / "voiceover"
    interview_dir = project_dir / "raw" / "interviews"
    vo_files = {p.name for p in voiceover_dir.glob("*") if p.is_file()} if voiceover_dir.exists() else set()
    iv_files = {p.name for p in interview_dir.glob("*") if p.is_file()} if interview_dir.exists() else set()

    results = []
    stats = {"single": 0, "multiple": 0, "not_found": 0}

    for row in rows:
        # Фильтр транскриптов по спикеру
        if row["speaker"] == "slava":
            tr_subset = {k: v for k, v in transcripts.items() if k in vo_files}
        else:
            tr_subset = {k: v for k, v in transcripts.items() if k in iv_files}
        # Fallback: если фильтр пуст, ищем во всех
        if not tr_subset:
            tr_subset = transcripts

        candidates = find_candidates(row["text"], tr_subset)
        status = "not_found" if not candidates else "single" if len(candidates) == 1 else "multiple"
        stats[status] += 1

        results.append({
            "row_idx": row["row_idx"],
            "speaker": row["speaker"],
            "col": row["col"],
            "text": row["text"],
            "candidates": candidates,
            "status": status,
        })
        label = "  ✓" if status == "single" else "  ?" if status == "multiple" else "  ✗"
        cands = ", ".join(f'{c["file"]}@{c["start"]:.1f}' for c in candidates)
        print(f"{label} row {row['row_idx']}: {row['text'][:50]}... → {cands or 'NOT FOUND'}")

    out_path = project_dir / "script" / "candidates.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"rows": results, "stats": stats}, f, ensure_ascii=False, indent=2)
    print(f"\nСтатистика: {stats}")
    print(f"Сохранено: {out_path}")
```

**Step 4: Запустить на проекте tulips**

```bash
python _scripts/match_timecodes.py search projects/tulips
```

Ожидаем: candidates.json с кандидатами для всех реплик. Проверить stats — сколько single/multiple/not_found.

**Step 5: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match-timecodes): проход 1 — алгоритмический поиск кандидатов"
```

---

### Task 3: Генерация words_compact.txt

**Files:**
- Modify: `_scripts/match_timecodes.py`

**Step 1: Команда compact**

```python
def cmd_compact(project_dir: Path):
    """Генерация words_compact.txt из transcript.json для агентов."""
    transcripts_dir = project_dir / "transcripts"
    for json_path in transcripts_dir.glob("*.transcript.json"):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        words = []
        for seg in data["segments"]:
            words.extend(w for w in seg.get("words", []) if "word" in w)

        out_name = json_path.stem.replace(".transcript", "") + ".words_compact.txt"
        out_path = transcripts_dir / out_name
        with open(out_path, "w", encoding="utf-8") as f:
            for i, w in enumerate(words):
                s = w.get("start", 0)
                e = w.get("end", 0)
                f.write(f"{i:5d} {s:8.2f}-{e:8.2f} {w['word']}\n")
        print(f"  {out_path.name}: {len(words)} слов")
```

**Step 2: Запустить**

```bash
python _scripts/match_timecodes.py compact projects/tulips
```

Ожидаем: `*.words_compact.txt` файлы в `transcripts/`.

**Step 3: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match-timecodes): генерация words_compact.txt для агентов"
```

---

### Task 4: Проход 3 — snap to silence

**Files:**
- Modify: `_scripts/match_timecodes.py`

**Step 1: Парсинг silencedetect**

```python
def detect_silences(video_path: Path, noise_db: int = -30, min_dur: float = 0.3) -> list[dict]:
    """Запускает ffmpeg silencedetect, возвращает [{start, end}, ...]."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
        "-f", "null", "/dev/null",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    silences = []
    current_start = None
    for line in result.stderr.splitlines():
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([\d.]+)", line)
            if m:
                current_start = float(m.group(1))
        elif "silence_end:" in line and current_start is not None:
            m = re.search(r"silence_end:\s*([\d.]+)", line)
            if m:
                silences.append({"start": current_start, "end": float(m.group(1))})
                current_start = None
    return silences
```

**Step 2: Функция snap**

```python
def snap_to_silence(start: float, end: float, silences: list[dict],
                     window: float = 2.0) -> tuple[float, float]:
    """Привязывает start/end к ближайшим паузам."""
    new_start = start
    new_end = end
    # Начало: ищем silence_end ближайший к start (в окне -window..start)
    best_dist = window
    for s in silences:
        if start - window <= s["end"] <= start + 0.1:
            dist = abs(s["end"] - start)
            if dist < best_dist:
                new_start = s["end"]
                best_dist = dist
    # Конец: ищем silence_start ближайший к end (в окне end..end+window)
    best_dist = window
    for s in silences:
        if end - 0.1 <= s["start"] <= end + window:
            dist = abs(s["start"] - end)
            if dist < best_dist:
                new_end = s["start"]
                best_dist = dist
    return round(new_start, 2), round(new_end, 2)
```

**Step 3: Команда snap — чтение verified.json, запись script.csv**

```python
def fmt_tc(seconds: float) -> str:
    """Секунды → MM:SS.ss"""
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:05.2f}"


def cmd_snap(project_dir: Path):
    """Проход 3: snap to silence + запись в script.csv."""
    verified_path = project_dir / "script" / "verified.json"
    with open(verified_path, "r", encoding="utf-8") as f:
        verified = json.load(f)

    # Собираем уникальные файлы и их пути
    raw_dir = project_dir / "raw"
    file_paths = {}
    for d in [raw_dir / "voiceover", raw_dir / "interviews"]:
        if d.exists():
            for p in d.iterdir():
                if p.is_file():
                    file_paths[p.name] = p

    # Детектим тишину для каждого файла
    print("Детекция пауз:")
    silence_map = {}
    for fname, fpath in file_paths.items():
        silences = detect_silences(fpath)
        silence_map[fname] = silences
        print(f"  {fname}: {len(silences)} пауз")

    # Загружаем CSV
    csv_path = project_dir / "script" / "script.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        csv_rows = list(csv.reader(f))

    # Применяем snap и записываем таймкоды
    for row_data in verified["rows"]:
        chosen = row_data.get("chosen")
        if not chosen:
            continue
        fname = chosen["file"]
        silences = silence_map.get(fname, [])
        start, end = snap_to_silence(chosen["start"], chosen["end"], silences)

        tc_str = f"{fname}, {fmt_tc(start)} -> {fmt_tc(end)}"
        col = row_data["col"]
        row_idx = row_data["row_idx"] - 1  # CSV 1-indexed в row_idx, но list 0-indexed (минус header)
        while len(csv_rows[row_idx]) < 4:
            csv_rows[row_idx].append("")
        csv_rows[row_idx][col] = tc_str

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_rows)
    print(f"\nОбновлён: {csv_path}")
```

**Step 4: Тестируем на реальных данных** (после прохода 2)

```bash
python _scripts/match_timecodes.py snap projects/tulips
```

**Step 5: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match-timecodes): проход 3 — snap to silence + запись CSV"
```

---

### Task 5: Main + связка команд

**Files:**
- Modify: `_scripts/match_timecodes.py`

**Step 1: Точка входа**

```python
def main():
    args = parse_args()
    project_dir = args.project_dir.resolve()
    if not project_dir.exists():
        print(f"Папка не найдена: {project_dir}", file=sys.stderr)
        sys.exit(1)
    if args.command == "search":
        cmd_search(project_dir)
    elif args.command == "snap":
        cmd_snap(project_dir)
    elif args.command == "compact":
        cmd_compact(project_dir)


if __name__ == "__main__":
    main()
```

**Step 2: Полный прогон прохода 1 + compact на tulips**

```bash
python _scripts/match_timecodes.py compact projects/tulips
python _scripts/match_timecodes.py search projects/tulips
```

Проверить: candidates.json создан, words_compact.txt создан.

**Step 3: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match-timecodes): полный скрипт с командами search/snap/compact"
```

---

### Task 6: Проход 2 — агентная верификация (скилл)

**Files:**
- Create: Claude Code skill file (путь определяется позже)

**Step 1: Описать workflow агентной верификации**

Скилл `match-timecodes` делает следующее:

1. Проверяет наличие `candidates.json`
2. Группирует реплики: `not_found` → полный контекст, `multiple` → контекст ±30 слов, `single` → беглая проверка
3. Запускает 4 параллельных Explore-агента, каждый получает:
   - Свой кусок реплик
   - Соответствующие `words_compact.txt`
   - Инструкцию: для каждой реплики вернуть JSON с выбранным кандидатом

4. Собирает ответы в `verified.json`

**Step 2: Формат verified.json**

```json
{
  "rows": [
    {
      "row_idx": 2,
      "speaker": "slava",
      "col": 1,
      "text": "В первую неделю марта...",
      "chosen": {
        "file": "1773574086.543356.mov",
        "start": 79.88,
        "end": 87.40,
        "words_start": 120,
        "words_end": 138
      },
      "confidence": "high",
      "note": ""
    }
  ]
}
```

**Step 3: Промпт для агентов**

Ключевые инструкции:
- Для `multiple`: "Прочитай контекст вокруг каждого кандидата. Определи, полная это реплика или фальстарт. Выбери последний ПОЛНЫЙ дубль."
- Для `not_found`: "Открой words_compact.txt и найди фрагмент по смыслу. Текст в сценарии мог быть переписан."
- Для `single`: "Проверь, что начало и конец не обрезают слова."
- Формат ответа: JSON-объект с выбранным кандидатом.

**Step 4: Коммит скилла**

```bash
git add <skill-path>
git commit -m "feat: скилл match-timecodes — агентная верификация таймкодов"
```

---

### Task 7: Обновить CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Добавить секцию match_timecodes.py**

```markdown
### match_timecodes.py — сопоставление реплик сценария с таймкодами

\```bash
python _scripts/match_timecodes.py search <project_dir>    # Проход 1: поиск кандидатов → candidates.json
python _scripts/match_timecodes.py snap <project_dir>       # Проход 3: snap to silence → обновляет script.csv
python _scripts/match_timecodes.py compact <project_dir>    # Генерация words_compact.txt для агентов
\```

Требует `ffmpeg` на PATH (для silencedetect). Транскрипты должны быть в `transcripts/*.transcript.json`.
Проход 2 (агентная верификация) выполняется скиллом match-timecodes.
```

**Step 2: Коммит**

```bash
git add CLAUDE.md
git commit -m "docs: добавить match_timecodes.py в CLAUDE.md"
```

---

### Task 8: Интеграционный тест на проекте tulips

**Step 1: Полный прогон**

```bash
# Проход 1
python _scripts/match_timecodes.py compact projects/tulips
python _scripts/match_timecodes.py search projects/tulips

# Проход 2 — вручную через скилл (агенты)
# Результат: verified.json

# Проход 3
python _scripts/match_timecodes.py snap projects/tulips
```

**Step 2: Проверка результата**

- Открыть `script.csv` — все реплики имеют таймкоды в формате `filename.ext, MM:SS.ss -> MM:SS.ss`
- Сравнить проблемный отрезок "Чем крупнее луковица..." — должен быть ~06:29, не 06:18
- Проверить что границы не режут слова (snap to silence сработал)

**Step 3: Финальный коммит**

```bash
git add projects/tulips/script/candidates.json projects/tulips/script/verified.json
git commit -m "feat(tulips): таймкоды сценария через match-timecodes (3 прохода)"
```
