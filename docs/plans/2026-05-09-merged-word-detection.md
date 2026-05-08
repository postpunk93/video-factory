# Системный фикс merged-word артефакта Whisper — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Автоматический детект и обход случаев, когда Whisper схлопнул несколько дублей в один word-token, и клип на границе клипа попадает в этот участок.

**Architecture:** В `cmd_snap` перед `snap_to_silence` детектим «подозрительные» слова на границах клипа (длительность > 1.0с), запускаем узконаправленный `silencedetect` внутри них с низким порогом, сдвигаем `start`/`end` к найденным внутренним паузам.

**Tech Stack:** Python 3, ffmpeg silencedetect, unittest.

**Дизайн:** `docs/plans/2026-05-09-merged-word-detection-design.md`

---

### Task 1: Хелпер для silencedetect в узком окне

**Files:**
- Modify: `_scripts/match_timecodes.py` (рядом с `detect_silences`, около line 846)
- Test: `tests/test_internal_break.py` (создать)

**Step 1: Написать падающий тест**

```python
"""Тесты merged-word detection (этап B7 — обход Whisper-артефакта)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_scripts"))

from match_timecodes import find_internal_break  # noqa: E402


class TestFindInternalBreak(unittest.TestCase):
    def test_short_word_no_change(self):
        """Слово короче 1.0с — не подозрительное, границы не двигаются."""
        word_start = {"start": 10.0, "end": 10.4, "word": "На"}
        word_end = {"start": 15.0, "end": 15.5, "word": "видео"}
        new_start, new_end = find_internal_break(
            file_path=None,  # silencedetect не должен вызываться
            word_at_start=word_start,
            word_at_end=word_end,
            current_start=10.0,
            current_end=15.5,
            silencedetect_fn=lambda *args, **kwargs: self.fail("silencedetect не должен вызываться"),
        )
        self.assertEqual(new_start, 10.0)
        self.assertEqual(new_end, 15.5)
```

**Step 2: Запустить тест, убедиться что падает**

Run: `python -m unittest tests.test_internal_break -v`
Expected: FAIL — `ImportError: cannot import name 'find_internal_break'`

**Step 3: Минимальная реализация**

В `_scripts/match_timecodes.py` рядом с `detect_silences`:

```python
SUSPICIOUS_WORD_DURATION_S = 1.0


def find_internal_break(file_path, word_at_start, word_at_end,
                         current_start, current_end,
                         silencedetect_fn=None):
    """Если слово на границе клипа подозрительно длинное — ищет паузу
    внутри него и возвращает скорректированные (start, end). Иначе —
    оригинальные значения.

    Для start: сдвигает к концу ПОСЛЕДНЕЙ паузы внутри first_word.
    Для end:   сдвигает к началу ПЕРВОЙ паузы внутри last_word.

    silencedetect_fn — для DI в тестах. По умолчанию реальный ffmpeg.
    """
    new_start = current_start
    new_end = current_end

    def is_suspicious(word):
        return word and (word["end"] - word["start"]) > SUSPICIOUS_WORD_DURATION_S

    # Реальный silencedetect подключим в Task 2.
    if silencedetect_fn is None:
        return new_start, new_end

    if is_suspicious(word_at_start):
        silences = silencedetect_fn(file_path, word_at_start["start"], word_at_start["end"])
        if silences:
            new_start = silences[-1]["end"]

    if is_suspicious(word_at_end):
        silences = silencedetect_fn(file_path, word_at_end["start"], word_at_end["end"])
        if silences:
            new_end = silences[0]["start"]

    return new_start, new_end
```

**Step 4: Запустить тест, убедиться что проходит**

Run: `python -m unittest tests.test_internal_break -v`
Expected: PASS.

**Step 5: Коммит**

```bash
git add tests/test_internal_break.py _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): find_internal_break + базовый тест"
```

---

### Task 2: Тесты на сдвиг границ по найденным паузам

**Files:**
- Modify: `tests/test_internal_break.py`

**Step 1: Расширить тест**

Добавить методы в `TestFindInternalBreak`:

```python
    def test_long_start_word_with_pause_shifts_start(self):
        """Длинное first_word с паузой внутри — start сдвигается к её концу."""
        word_start = {"start": 38.99, "end": 40.58, "word": "На"}  # 1.59с
        word_end = {"start": 43.08, "end": 44.08, "word": "когтеточек."}
        # Симулируем паузу внутри слова "На" с 40.40 по 40.50
        def fake_silencedetect(path, t_start, t_end):
            if t_start == 38.99 and t_end == 40.58:
                return [{"start": 40.40, "end": 40.50}]
            return []
        new_start, new_end = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_end,
            current_start=38.99,
            current_end=44.08,
            silencedetect_fn=fake_silencedetect,
        )
        self.assertAlmostEqual(new_start, 40.50)
        self.assertEqual(new_end, 44.08)

    def test_long_end_word_with_pause_shifts_end(self):
        """Длинное last_word с паузой внутри — end сдвигается к её началу."""
        word_start = {"start": 100.0, "end": 100.3, "word": "Слово"}
        word_end = {"start": 105.0, "end": 107.5, "word": "длинное"}  # 2.5с
        def fake_silencedetect(path, t_start, t_end):
            if t_start == 105.0 and t_end == 107.5:
                return [{"start": 106.0, "end": 106.2}]
            return []
        new_start, new_end = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_end,
            current_start=100.0,
            current_end=107.5,
            silencedetect_fn=fake_silencedetect,
        )
        self.assertEqual(new_start, 100.0)
        self.assertAlmostEqual(new_end, 106.0)

    def test_long_word_no_pause_inside_fallback(self):
        """Длинное слово, но silencedetect не нашёл — возвращаются оригиналы."""
        word_start = {"start": 10.0, "end": 12.0, "word": "Длинное"}
        new_start, new_end = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_start,
            current_start=10.0,
            current_end=12.0,
            silencedetect_fn=lambda *args, **kwargs: [],
        )
        self.assertEqual(new_start, 10.0)
        self.assertEqual(new_end, 12.0)

    def test_multiple_internal_pauses_picks_last_for_start(self):
        """Несколько внутренних пауз — для start берём последнюю."""
        word_start = {"start": 0.0, "end": 3.0, "word": "X"}
        def fake(path, t_start, t_end):
            return [
                {"start": 0.5, "end": 0.7},
                {"start": 1.5, "end": 1.8},
                {"start": 2.5, "end": 2.7},
            ]
        new_start, _ = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_start,
            current_start=0.0,
            current_end=3.0,
            silencedetect_fn=fake,
        )
        self.assertAlmostEqual(new_start, 2.7)
```

**Step 2: Запустить — все 4 новых теста должны пройти (логика уже есть)**

Run: `python -m unittest tests.test_internal_break -v`
Expected: PASS (5 тестов всего).

**Step 3: Коммит**

```bash
git add tests/test_internal_break.py
git commit -m "test(match_timecodes): edge cases для find_internal_break"
```

---

### Task 3: Реальная реализация detect_silences_in_range

**Files:**
- Modify: `_scripts/match_timecodes.py` (рядом с `detect_silences`)

**Step 1: Добавить функцию**

```python
def detect_silences_in_range(video_path: Path, t_start: float, t_end: float,
                              d: float = 0.05, noise: str = "-30dB") -> list[dict]:
    """Запускает silencedetect на узком окне [t_start, t_end] с низким порогом
    минимальной длительности паузы. Используется для поиска внутренних пауз
    в подозрительно длинных Whisper-словах (схлопнутые дубли).

    Возвращает [{start, end}, ...] в АБСОЛЮТНЫХ секундах файла.
    """
    duration = t_end - t_start
    if duration <= 0:
        return []
    cmd = [
        "ffmpeg", "-ss", f"{t_start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(video_path),
        "-af", f"silencedetect=noise={noise}:d={d}",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        print("Ошибка: ffmpeg не найден", file=sys.stderr)
        sys.exit(1)

    output = result.stderr
    starts = re.findall(r"silence_start:\s*(-?[\d.]+)", output)
    ends = re.findall(r"silence_end:\s*(-?[\d.]+)", output)

    silences = []
    # ffmpeg -ss даёт времена ОТНОСИТЕЛЬНО окна. Сдвигаем на t_start.
    for i in range(min(len(starts), len(ends))):
        s = float(starts[i]) + t_start
        e = float(ends[i]) + t_start
        # Отсекаем выходящие за окно (бывают артефакты на границах)
        if s < t_start - 0.01 or e > t_end + 0.01:
            continue
        silences.append({"start": max(s, t_start), "end": min(e, t_end)})
    return silences
```

**Step 2: Smoke-тест на реальном файле**

```bash
PYTHONIOENCODING=utf-8 python -c "
from pathlib import Path
import sys
sys.path.insert(0, '_scripts')
from match_timecodes import detect_silences_in_range
p = Path('projects/2026-04-kogtetochki/raw/voiceover/запись славы.mov')
silences = detect_silences_in_range(p, 38.99, 40.58, d=0.05)
print(f'silences in [38.99-40.58]: {silences}')
"
```

Expected: список содержит хотя бы одну паузу — это та самая «спрятанная» пауза между дублями. Если пусто — увеличить `d` до 0.03 или ослабить `noise` до `-25dB`.

**Step 3: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): detect_silences_in_range для поиска внутри слов"
```

---

### Task 4: Подключить detect_silences_in_range к find_internal_break по умолчанию

**Files:**
- Modify: `_scripts/match_timecodes.py`

**Step 1: Изменить default silencedetect_fn**

В `find_internal_break` заменить:

```python
    if silencedetect_fn is None:
        return new_start, new_end
```

на:

```python
    if silencedetect_fn is None:
        silencedetect_fn = lambda path, ts, te: detect_silences_in_range(path, ts, te)
```

**Step 2: Запустить существующие тесты**

Run: `python -m unittest tests.test_internal_break -v`
Expected: PASS (все 5 — DI всё ещё работает в тестах).

**Step 3: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): подключить ffmpeg silencedetect к find_internal_break"
```

---

### Task 5: Интеграция в cmd_snap

**Files:**
- Modify: `_scripts/match_timecodes.py:cmd_snap` (около line 1100, перед `snap_to_silence`)

**Step 1: Найти границы слов для clip start/end**

В `cmd_snap` внутри цикла `for p in parts`, перед существующим вычислением `prev/nxt`, добавить:

```python
            # Найти words file (загружены в words_cache выше)
            words = words_cache.get(fname, [])
            # word_at_start = слово, в которое попадает p["start"]
            # word_at_end   = слово, в которое попадает p["end"]
            word_at_start = next(
                (w for w in words
                 if w.get("start", 0) - 0.01 <= p["start"] <= w.get("end", 0) + 0.01),
                None,
            )
            word_at_end = next(
                (w for w in words
                 if w.get("start", 0) - 0.01 <= p["end"] <= w.get("end", 0) + 0.01),
                None,
            )

            # Поиск внутренней паузы для merged-word case
            video_path = None
            for d in raw_dirs:
                cand = d / fname
                if cand.exists():
                    video_path = cand
                    break
            if video_path and (word_at_start or word_at_end):
                new_start, new_end = find_internal_break(
                    file_path=video_path,
                    word_at_start=word_at_start,
                    word_at_end=word_at_end,
                    current_start=p["start"],
                    current_end=p["end"],
                )
                if new_start != p["start"] or new_end != p["end"]:
                    print(f"  ↻ row {row['row_idx']}: merged-word fix "
                          f"start={p['start']:.2f}->{new_start:.2f} "
                          f"end={p['end']:.2f}->{new_end:.2f}")
                    p = dict(p)
                    p["start"] = new_start
                    p["end"] = new_end
```

**Важно:** `p = dict(p)` чтобы не мутировать verified.json. Дальше уже работает с локальной копией.

**Step 2: Откатить ручной фикс row 3 в verified.json**

```bash
PYTHONIOENCODING=utf-8 python -c "
import json
p = 'projects/2026-04-kogtetochki/script/verified.json'
d = json.load(open(p, encoding='utf-8'))
for r in d['rows']:
    if r['row_idx'] == 3:
        r['chosen_parts'][0]['start'] = 38.99
        r['note'] = ''
json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('row 3 start: вернул на 38.99')
"
```

**Step 3: Запустить snap**

```bash
PYTHONIOENCODING=utf-8 python _scripts/match_timecodes.py snap projects/2026-04-kogtetochki/ 2>&1 | grep -E "row 3|Строка 3"
```

Expected:
```
  ↻ row 3: merged-word fix start=38.99->40.5x end=44.08->44.08
  Строка 3: 1 часть(и) — запись славы.mov: 00:40.5x — 00:44.08
```

**Step 4: Коммит**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): merged-word detect в cmd_snap"
```

---

### Task 6: Проверить что fix не сломал остальной snap

**Files:** none (verification only)

**Step 1: Сравнить script.csv до/после фикса**

```bash
PYTHONIOENCODING=utf-8 python projects/2026-04-kogtetochki/script/_diff_csv.py 2>&1 | head -30
```

Expected: row 3 теперь показывает изменение (start=40.5 vs 38.99 в before-rerun = 38.24); остальные строки либо без изменений, либо незначительные сдвиги (если у них тоже были merged words).

**Step 2: Полный E2E** — пересобрать XML и убедиться что всё парсится.

```bash
PYTHONIOENCODING=utf-8 python _scripts/build_xml.py projects/2026-04-kogtetochki/ --davinci 2>&1 | tail -5
PYTHONIOENCODING=utf-8 python -c "
import xml.etree.ElementTree as ET
ET.parse('projects/2026-04-kogtetochki/assembly/2026-04-kogtetochki_rough_cut.fcpxml')
print('xml ok')
"
```

Expected: `xml ok`.

**Step 3: Визуальная проверка пользователем**

Передать пользователю: «Открой `assembly/2026-04-kogtetochki_rough_cut.fcpxml` в DaVinci. Row 3 (первый клип) должен начинаться с чистого «На моём канале...», без дубля».

**Step 4: Если ок — коммит CHANGELOG в дизайн** (опционально):

В конец `docs/plans/2026-05-09-merged-word-detection-design.md` добавить:

```markdown
## Реализация

Внедрено 2026-05-09. E2E проверка на kogtetochki: row 3 автоматически начинается с 40.5x вместо 38.24, дубль пропал.
```

```bash
git add docs/plans/2026-05-09-merged-word-detection-design.md
git commit -m "docs: пометить merged-word fix как реализованный"
```

---

### Task 7: Обновить memory

**Files:** memory entries

**Step 1: Добавить запись в auto-memory**

Создать файл `C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\project_merged_word_fix.md`:

```markdown
---
name: merged-word-fix
description: Snap-level детект Whisper merged-word артефакта (несколько дублей в одном word-token)
type: project
---

Реализовано 2026-05-09 в `_scripts/match_timecodes.py:find_internal_break` + `detect_silences_in_range`.

При snap'е: если первое/последнее слово клипа > 1.0с длиной — запускаем silencedetect внутри слова с d=0.05 -30dB. Если паузы найдены — start сдвигается к концу последней (для first_word), end — к началу первой (для last_word).

**Why:** Whisper иногда схлопывает несколько дублей произнесения в один token с расширенной длительностью (например, «На» 1.59с в kogtetochki row 3 содержал 2 дубля «На моём канале...»). Word-boundary constraint в snap не помогал — границы слова трактовались как атомарные.

**How to apply:** При новых E2E прогонах не должно быть мусорных дублей в начале клипов. Если появились — проверять не сидит ли проблема ВНУТРИ клипа (в этом случае нужно multipart разбиение, отдельная фича).
```

И добавить в `MEMORY.md` строку:
```markdown
- [project_merged_word_fix.md](project_merged_word_fix.md) — Snap-level фикс Whisper merged-word артефакта
```

**Step 2: Пометить что улучшение нарезки полностью закрыто**

Открыть `C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\project_cutting_improvements.md` и обновить «Не закрыто» → отметить E2E на kogtetochki как завершённый, добавить ссылку на merged-word fix.

(Detailed update text — по контексту, что E2E прошёл, баг с opacity файла r43 нашли+пофиксили, дубли в row 3 системно пофиксили в Task 5.)
