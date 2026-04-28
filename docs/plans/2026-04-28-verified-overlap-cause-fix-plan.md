# Verified Overlap Cause Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Соседние split-mode кандидаты в одной строке скрипта и одном файле никогда не пересекаются по word-границам в `candidates.json`.

**Architecture:** Пробросить `words_start`/`words_end` из `find_candidates` в финальные кандидаты `find_quote_parts`. Добавить пост-обработку `_dedupe_split_overlaps` — для каждой пары соседних script-частей, для каждой пары их кандидатов в одном файле с пересекающимися word-индексами клипить по середине пересечения, граничное слово выкидывать из обоих ренжей. Вызывается ДО `merge_adjacent_parts` и только в split-ветке. Whole-mode не трогается.

**Tech Stack:** Python 3, stdlib only. Никакого pytest — верификация smoke-тестами через `python -c` и регрессией на реальных проектах.

**Дизайн:** `docs/plans/2026-04-28-verified-overlap-cause-fix-design.md`

---

## Контекст для исполнителя

В проекте нет тестового фреймворка. Проверка делается:
1. **Smoke-тесты** через `python -c` на синтетических данных — для функции `_dedupe_split_overlaps`.
2. **Регрессия** на baseline-проекте `projects/2026-03-thermobags`: rows 51, 81, 90 имеют известный 1-word оверлап в `candidates.json`. После фикса оверлапов быть не должно.
3. **Сравнение CSV** до/после в смежных проектах с `||` — не сломали ли существующие single-cand цепочки.

`find_candidates` уже возвращает `words_start`/`words_end` в каждом кандидате (`_scripts/match_timecodes.py:470–477`). `find_quote_parts` сейчас срезает эти поля при сборке `parts_out`. Фикс пробрасывает их и добавляет пост-обработку.

Известные реальные кейсы (термосумки):
- row 51: `1774165021…mov` 443.05–451.39 vs 451.29–456.93 (overlap 0.10s, граничное слово "и")
- row 81: `1774165021…mov` 670.08–675.27 vs 675.11–678.25 (overlap 0.16s, граничное слово "по")
- row 90: `термосумки 2.mp4` 1839.00–1845.10 vs 1845.02–1851.45 (overlap 0.08s, граничное слово "Но")

Row 80 (нелинейная цитата из 2 файлов с близкими границами) **не должна** меняться — наш E3-фильтр пропускает out-of-order соседей.

---

## Task 1: Зафиксировать baseline

**Files:**
- Read: `projects/2026-03-thermobags/script/candidates.json`

**Step 1: Сохранить baseline-оверлапы**

Запустить detect-script для baseline (вывод сохранить в `/tmp/baseline_overlaps.txt` или просто запомнить):

```bash
python -c "
import json
c = json.load(open('projects/2026-03-thermobags/script/candidates.json', encoding='utf-8'))
for row in c.get('rows', []):
    parts = row.get('parts') or []
    for i in range(len(parts) - 1):
        for ca in parts[i].get('candidates', []):
            for cb in parts[i+1].get('candidates', []):
                if ca.get('file') != cb.get('file'):
                    continue
                if ca['end'] > cb['start'] and ca['start'] <= cb['start']:
                    print(f\"row={row.get('row_idx')} file={ca['file']} A={ca['start']:.2f}-{ca['end']:.2f} B={cb['start']:.2f}-{cb['end']:.2f} overlap={ca['end']-cb['start']:.2f}s\")
"
```

Ожидаемое (примерно):
```
row=51 file=1774165021.6478019.mov A=443.05-451.39 B=451.29-456.93 overlap=0.10s
row=81 file=1774165021.6478019.mov A=670.08-675.27 B=675.11-678.25 overlap=0.16s
row=90 file=термосумки 2.mp4 A=1839.00-1845.10 B=1845.02-1851.45 overlap=0.08s
```

(Точные кейсы могут отличаться от текущего CSV, но row 51/81/90 должны присутствовать.)

**Step 2: Commit**

Этот шаг ничего не меняет в репо — пропускаем коммит.

---

## Task 2: Написать `_dedupe_split_overlaps` (TDD-стиль через smoke-тест)

**Files:**
- Modify: `_scripts/match_timecodes.py` (добавить функцию рядом с `merge_adjacent_parts`, ~строка 311)

**Step 1: Написать smoke-тест**

Создать файл `/tmp/smoke_dedupe.py`:

```python
import sys
sys.path.insert(0, '_scripts')

# Заглушка для words: объекты с .start/.end/.get
class W:
    def __init__(self, s, e):
        self._s = s
        self._e = e
    def get(self, k, default=None):
        return {'start': self._s, 'end': self._e}.get(k, default)
    @property
    def start(self): return self._s
    @property
    def end(self): return self._e

# Транскрипт: 21 слово, по 0.5с с зазорами 0.05с
words = [W(i * 0.55, i * 0.55 + 0.5) for i in range(21)]
transcripts = {"a.mp4": {"words": words}}

# Импорт ПОСЛЕ объявления заглушек
from match_timecodes import _dedupe_split_overlaps  # noqa: E402

# Кейс 1: 1-word оверлап (граничное слово K=10)
parts = [
    {"text": "S1", "candidates": [{"file": "a.mp4", "words_start": 0, "words_end": 10,
                                    "start": 0.0, "end": 5.5}]},
    {"text": "S2", "candidates": [{"file": "a.mp4", "words_start": 10, "words_end": 20,
                                    "start": 5.5, "end": 11.0}]},
]
_dedupe_split_overlaps(parts, transcripts)
ca, cb = parts[0]["candidates"][0], parts[1]["candidates"][0]
assert ca["words_end"] == 9, f"E1.1: words_end={ca['words_end']} expected 9"
assert cb["words_start"] == 11, f"E1.2: words_start={cb['words_start']} expected 11"
assert ca["end"] == round(words[9].end, 2), f"E1.3: end={ca['end']}"
assert cb["start"] == round(words[11].start, 2), f"E1.4: start={cb['start']}"
print("Кейс 1 (1-word оверлап) ✓")

# Кейс 2: 2-word оверлап (общие слова 9, 10)
parts = [
    {"text": "S1", "candidates": [{"file": "a.mp4", "words_start": 0, "words_end": 10,
                                    "start": 0.0, "end": 5.5}]},
    {"text": "S2", "candidates": [{"file": "a.mp4", "words_start": 9, "words_end": 20,
                                    "start": 4.95, "end": 11.0}]},
]
_dedupe_split_overlaps(parts, transcripts)
ca, cb = parts[0]["candidates"][0], parts[1]["candidates"][0]
# mid = (9 + 10) // 2 = 9; new_a_end = 8, new_b_start = 10
assert ca["words_end"] == 8, f"E2.1: words_end={ca['words_end']} expected 8"
assert cb["words_start"] == 10, f"E2.2: words_start={cb['words_start']} expected 10"
print("Кейс 2 (2-word оверлап) ✓")

# Кейс 3: Нет оверлапа
parts = [
    {"text": "S1", "candidates": [{"file": "a.mp4", "words_start": 0, "words_end": 5,
                                    "start": 0.0, "end": 3.0}]},
    {"text": "S2", "candidates": [{"file": "a.mp4", "words_start": 7, "words_end": 15,
                                    "start": 3.85, "end": 8.5}]},
]
_dedupe_split_overlaps(parts, transcripts)
ca, cb = parts[0]["candidates"][0], parts[1]["candidates"][0]
assert ca["words_end"] == 5 and cb["words_start"] == 7, "E3: не должно меняться"
print("Кейс 3 (нет оверлапа) ✓")

# Кейс 4: Разные файлы
parts = [
    {"text": "S1", "candidates": [{"file": "a.mp4", "words_start": 0, "words_end": 10,
                                    "start": 0.0, "end": 5.5}]},
    {"text": "S2", "candidates": [{"file": "b.mp4", "words_start": 5, "words_end": 15,
                                    "start": 2.75, "end": 8.5}]},
]
_dedupe_split_overlaps(parts, {"a.mp4": {"words": words}, "b.mp4": {"words": words}})
ca, cb = parts[0]["candidates"][0], parts[1]["candidates"][0]
assert ca["words_end"] == 10 and cb["words_start"] == 5, "E4: разные файлы — не меняется"
print("Кейс 4 (разные файлы) ✓")

# Кейс 5: Out-of-order по источнику (cb идёт раньше ca в транскрипте)
parts = [
    {"text": "S1", "candidates": [{"file": "a.mp4", "words_start": 10, "words_end": 18,
                                    "start": 5.5, "end": 9.9}]},
    {"text": "S2", "candidates": [{"file": "a.mp4", "words_start": 2, "words_end": 11,
                                    "start": 1.1, "end": 6.05}]},
]
_dedupe_split_overlaps(parts, transcripts)
ca, cb = parts[0]["candidates"][0], parts[1]["candidates"][0]
assert ca["words_end"] == 18 and cb["words_start"] == 2, "E5: out-of-order — не меняется"
print("Кейс 5 (out-of-order) ✓")

# Кейс 6: Защита от схлопывания (ренж 1 слова)
parts = [
    {"text": "S1", "candidates": [{"file": "a.mp4", "words_start": 5, "words_end": 5,
                                    "start": 2.75, "end": 3.25}]},
    {"text": "S2", "candidates": [{"file": "a.mp4", "words_start": 5, "words_end": 12,
                                    "start": 2.75, "end": 6.7}]},
]
_dedupe_split_overlaps(parts, transcripts)
ca, cb = parts[0]["candidates"][0], parts[1]["candidates"][0]
# mid = 5; new_a_end = 4 < ca.words_start (5) → пропускаем; new_b_start = 6 ≤ cb.words_end (12) → но мы пропускаем всю пару
assert ca["words_end"] == 5, f"E6.1: должно остаться 5, получено {ca['words_end']}"
assert cb["words_start"] == 5, f"E6.2: должно остаться 5, получено {cb['words_start']}"
print("Кейс 6 (защита от схлопывания) ✓")

print("\nВсе кейсы прошли.")
```

**Step 2: Запустить smoke-тест — должен упасть на ImportError**

```bash
cd C:/Users/Alex/Videos/factory
python /tmp/smoke_dedupe.py
```

Ожидаемое: `ImportError: cannot import name '_dedupe_split_overlaps'`

**Step 3: Реализовать `_dedupe_split_overlaps`**

Добавить в `_scripts/match_timecodes.py` сразу после `merge_adjacent_parts` (после строки 328):

```python
def _dedupe_split_overlaps(parts: list[dict], transcripts: dict) -> None:
    """Подрезает word-индексы соседних split-кандидатов в одном файле,
    если их ренжи в транскрипте пересекаются. Меняет parts in-place.

    Для каждой пары соседних script-частей, для каждой пары их кандидатов
    в одном файле где cand_a.words_end >= cand_b.words_start и cand_b
    лежит позже в источнике (cb.words_start >= ca.words_start) — клипит
    обе по середине пересечения. Граничное слово при 1-word оверлапе
    выкидывается из обоих ренжей.

    Whole-mode (fuzzy_whole_match) не трогается — там ренжи не пересекаются
    по построению.
    """
    for i in range(len(parts) - 1):
        for ca in parts[i].get("candidates", []):
            if "words_start" not in ca or "words_end" not in ca:
                continue
            for cb in parts[i + 1].get("candidates", []):
                if "words_start" not in cb or "words_end" not in cb:
                    continue
                if ca["file"] != cb["file"]:
                    continue
                # Нет пересечения по word-индексам
                if ca["words_end"] < cb["words_start"]:
                    continue
                # Out-of-order: cb лежит в источнике раньше ca — не наш кейс
                if cb["words_start"] < ca["words_start"]:
                    continue

                mid = (cb["words_start"] + ca["words_end"]) // 2
                new_a_end = mid - 1
                new_b_start = mid + 1

                # Защита от схлопывания
                if new_a_end < ca["words_start"]:
                    continue
                if new_b_start > cb["words_end"]:
                    continue

                # Монотонные клипы (для случая множественных пересечений)
                if new_a_end < ca["words_end"]:
                    ca["words_end"] = new_a_end
                    words = transcripts[ca["file"]]["words"]
                    ca["end"] = round(_safe_time(words[new_a_end], "end", words, new_a_end), 2)
                if new_b_start > cb["words_start"]:
                    cb["words_start"] = new_b_start
                    words = transcripts[cb["file"]]["words"]
                    cb["start"] = round(_safe_time(words[new_b_start], "start", words, new_b_start), 2)
```

**Step 4: Запустить smoke-тест — должен пройти**

```bash
python /tmp/smoke_dedupe.py
```

Ожидаемое: все 6 кейсов выводят `✓` и финальное `Все кейсы прошли.`

Если падает на E1 (округление времени): проверить что `_safe_time` возвращает float и `round(..., 2)` не усекает важные знаки.

**Step 5: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): _dedupe_split_overlaps для устранения оверлапа word-границ"
```

---

## Task 3: Пробросить `words_start`/`words_end` в `find_quote_parts` и подключить дедуп

**Files:**
- Modify: `_scripts/match_timecodes.py:380–421` (тело split-ветки `find_quote_parts`)

**Step 1: Заменить блок построения `parts_out` и финальный return**

Найти блок (строки 380–421):

```python
    parts_out = []
    unmatched = []
    for s in sentences:
        cands = find_candidates(s, transcripts)
        cands.sort(key=lambda c: c["start"])
        if not cands:
            unmatched.append(s)
            continue
        parts_out.append({
            "text": s,
            "candidates": [
                {"file": c["file"], "start": c["start"], "end": c["end"]}
                for c in cands
            ],
        })

    # Мёрдж соседних: только для частей с единственным кандидатом.
    single_cand_parts = [
        {"file": p["candidates"][0]["file"],
         "start": p["candidates"][0]["start"],
         "end": p["candidates"][0]["end"],
         "text": p["text"]}
        for p in parts_out if len(p["candidates"]) == 1
    ]
    merged = merge_adjacent_parts(single_cand_parts)

    # Сливаем обратно: если все parts_out имеют 1 кандидата — возвращаем merged.
    # Иначе оставляем как есть (агент-ревьюер выберет).
    if all(len(p["candidates"]) == 1 for p in parts_out):
        parts_out = [
            {
                "text": m["text"],
                "candidates": [{"file": m["file"], "start": m["start"], "end": m["end"]}],
            }
            for m in merged
        ]

    return {
        "parts": parts_out,
        "unmatched": unmatched,
        "mode": "split",
    }
```

Заменить на:

```python
    parts_out = []
    unmatched = []
    for s in sentences:
        cands = find_candidates(s, transcripts)
        cands.sort(key=lambda c: c["start"])
        if not cands:
            unmatched.append(s)
            continue
        parts_out.append({
            "text": s,
            "candidates": [
                {"file": c["file"], "start": c["start"], "end": c["end"],
                 "words_start": c["words_start"], "words_end": c["words_end"]}
                for c in cands
            ],
        })

    # Дедуп оверлапов word-границ соседних split-кандидатов в одном файле.
    # Должно идти ДО merge_adjacent_parts: если merge склеит две части в одну,
    # оверлапа всё равно нет; если не склеит — клипа уже хватит.
    _dedupe_split_overlaps(parts_out, transcripts)

    # Мёрдж соседних: только для частей с единственным кандидатом.
    single_cand_parts = [
        {"file": p["candidates"][0]["file"],
         "start": p["candidates"][0]["start"],
         "end": p["candidates"][0]["end"],
         "text": p["text"]}
        for p in parts_out if len(p["candidates"]) == 1
    ]
    merged = merge_adjacent_parts(single_cand_parts)

    # Сливаем обратно: если все parts_out имеют 1 кандидата — возвращаем merged.
    # Иначе оставляем как есть (агент-ревьюер выберет).
    if all(len(p["candidates"]) == 1 for p in parts_out):
        parts_out = [
            {
                "text": m["text"],
                "candidates": [{"file": m["file"], "start": m["start"], "end": m["end"]}],
            }
            for m in merged
        ]

    return {
        "parts": parts_out,
        "unmatched": unmatched,
        "mode": "split",
    }
```

Два изменения:
- В `parts_out.append`: добавлены `words_start`/`words_end` в каждый candidate.
- Между циклом и `merge_adjacent_parts` вызывается `_dedupe_split_overlaps`.

`words_start`/`words_end` в `merged` исчезают — `merge_adjacent_parts` берёт только `file`/`start`/`end`/`text`. После merge переписываем `parts_out` без word-индексов. Это нормально: после merge оверлапы уже невозможны (соседи склеены в одну часть).

**Step 2: Verify (синтаксис)**

```bash
python -c "import sys; sys.path.insert(0, '_scripts'); import match_timecodes"
```

Ожидаемое: ничего не печатает (импорт успешный).

**Step 3: Прогнать smoke-тест ещё раз**

```bash
python /tmp/smoke_dedupe.py
```

Ожидаемое: всё ещё все 6 кейсов проходят (мы не меняли `_dedupe_split_overlaps`, только подключили).

**Step 4: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "fix(match_timecodes): подключить _dedupe_split_overlaps в find_quote_parts"
```

---

## Task 3.5: Фикс `_safe_time` (второй корень, обнаружен Task 4 регрессией)

**Files:**
- Modify: `_scripts/match_timecodes.py:80-102` (функция `_safe_time`)

**Контекст:** Task 4 регрессия показала что `_dedupe_split_overlaps` чинит 5 из 6 кейсов в `candidates.json` термосумок. Row 81 остаётся с оверлапом 0.16с — другая причина: `_safe_time` при fallback берёт **то же** поле у соседа (`end` для `end`-lookup), что семантически некорректно. Должно брать **противоположное** поле (`start` следующего слова как верхняя граница для `end[K]`). Подробности: `docs/plans/2026-04-28-verified-overlap-cause-fix-design.md` секция «Дополнение».

**Step 1: Расширить smoke-тест двумя кейсами**

Добавить в существующий тест из Task 2 (или временный smoke-тест) два новых кейса:

```python
# Кейс 7: _safe_time для end слова с пустым таймом — должен брать start следующего слова
import sys; sys.path.insert(0, '_scripts')
from match_timecodes import _safe_time

words7 = [
    {"start": 1.0, "end": 1.5, "word": "ok1"},
    {"start": 0.0, "end": 0.0, "word": "empty"},  # idx=1 — пустое
    {"start": 2.5, "end": 3.0, "word": "ok2"},
]
assert _safe_time(words7[1], "end", words7, 1) == 2.5, "E7: end fallback должен брать start следующего"
assert _safe_time(words7[1], "start", words7, 1) == 1.5, "E7: start fallback должен брать end предыдущего"
print("Кейс 7 (_safe_time fallback из противоположного поля) ✓")

# Кейс 8: цепочка пустых слов — fallback идёт дальше
words8 = [
    {"start": 1.0, "end": 1.5, "word": "ok1"},
    {"start": 0.0, "end": 0.0, "word": "empty1"},
    {"start": 0.0, "end": 0.0, "word": "empty2"},
    {"start": 3.0, "end": 3.5, "word": "ok2"},
]
assert _safe_time(words8[1], "end", words8, 1) == 3.0, "E8: цепочка пустых — end берёт start ok2"
assert _safe_time(words8[2], "start", words8, 2) == 1.5, "E8: цепочка пустых — start берёт end ok1"
print("Кейс 8 (цепочка пустых слов) ✓")
```

**Step 2: Запустить — должен упасть на assertion**

```bash
python C:/Users/Alex/Videos/factory/.tmp_smoke_safe_time.py
```

Ожидаемое: первый assert E7 падает (текущий `_safe_time` для end fallback возвращает `words[2].end = 3.0`, а ожидаем 2.5).

**Step 3: Реализовать фикс `_safe_time`**

Заменить функцию (`_scripts/match_timecodes.py:80-102`) на:

```python
def _safe_time(word: dict, field: str, words: list[dict], idx: int) -> float:
    """Берёт start/end из слова; если 0.0 — ищет у соседей.

    Для end: ограничивает длительность слова MAX_WORD_DURATION
    (артефакт Whisper — end последнего слова сегмента часто растянут на тишину).

    Fallback из противоположного поля соседа: end → start следующего (верхняя
    граница), start → end предыдущего (нижняя граница). Whisperx-слова не
    пересекаются по времени, поэтому это безопасные конструктивные оценки.
    """
    val = word.get(field, 0.0)
    if val and val > 0.0:
        # Защита от артефактов Whisper: end слишком далеко от start
        if field == "end":
            word_start = word.get("start", 0.0)
            if word_start > 0 and val - word_start > MAX_WORD_DURATION:
                return round(word_start + MAX_WORD_DURATION, 2)
        return val
    # Fallback: противоположное поле соседа как safe bound
    fallback_field = "start" if field == "end" else "end"
    direction = -1 if field == "start" else 1
    for offset in range(1, 20):
        ni = idx + direction * offset
        if 0 <= ni < len(words):
            nval = words[ni].get(fallback_field, 0.0)
            if nval and nval > 0.0:
                return nval
    return 0.0
```

Изменение: одна строка `fallback_field = ...` и подмена `field` на `fallback_field` внутри цикла.

**Step 4: Запустить smoke-тест — должен пройти**

```bash
python C:/Users/Alex/Videos/factory/.tmp_smoke_safe_time.py
```

Ожидаемое: оба кейса 7 и 8 выводят ✓.

**Step 5: Прогнать также старый smoke-тест из Task 2 — все 6 кейсов должны пройти**

Кейсы 1-6 не затрагивают пустые таймы, не должны измениться.

**Step 6: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "fix(match_timecodes): _safe_time fallback из противоположного поля соседа"
```

---

## Task 4: Регрессия на термосумках

**Files:**
- Modify (пере-сгенерируется): `projects/2026-03-thermobags/script/candidates.json`

**Step 1: Прогнать search**

```bash
python _scripts/match_timecodes.py search projects/2026-03-thermobags
```

Ожидаемое:
- Команда отрабатывает без ошибок.
- Печатает прогресс по строкам.

**Step 2: Проверить отсутствие оверлапов в candidates.json**

```bash
python -c "
import json
c = json.load(open('projects/2026-03-thermobags/script/candidates.json', encoding='utf-8'))
overlaps = []
for row in c.get('rows', []):
    parts = row.get('parts') or []
    for i in range(len(parts) - 1):
        for ca in parts[i].get('candidates', []):
            for cb in parts[i+1].get('candidates', []):
                if ca.get('file') != cb.get('file'):
                    continue
                if ca['end'] > cb['start'] and ca['start'] <= cb['start']:
                    overlaps.append((row.get('row_idx'), ca['file'], ca['end'], cb['start'], ca['end']-cb['start']))
print(f'Найдено оверлапов: {len(overlaps)}')
for o in overlaps:
    print(f'  row={o[0]} file={o[1]} A.end={o[2]:.2f} B.start={o[3]:.2f} overlap={o[4]:.2f}s')
"
```

Ожидаемое:
```
Найдено оверлапов: 0
```

Если остались оверлапы:
- На rows 51/81/90 — фикс не сработал, ищи баг в `_dedupe_split_overlaps` (проверь Step 4 в Task 2).
- На других строках — out-of-order (E3) пропустил легитимный кейс. Это допустимо для нелинейных цитат, но проверь — может, фильтр `cb.words_start >= ca.words_start` слишком строгий. Если на новой строке оверлап реально в source-chronological порядке, копай.

**Step 3: Структура row 80 не сломана**

```bash
python -c "
import json
c = json.load(open('projects/2026-03-thermobags/script/candidates.json', encoding='utf-8'))
for row in c.get('rows', []):
    if row.get('row_idx') == 80:
        print(f\"row 80: status={row.get('status')} mode={row.get('mode')} parts={len(row.get('parts', []))}\")
        for i, p in enumerate(row.get('parts', [])):
            print(f'  part {i}: {len(p.get(\"candidates\", []))} cand(s)')
"
```

Ожидаемое: row 80 имеет такую же структуру что и до фикса (число parts и кандидатов в каждом не изменилось — мы только клипим word-индексы при оверлапе, а не дропаем кандидатов).

**Step 4: Прогнать `/match-timecodes` (агентная верификация)**

```
/match-timecodes projects/2026-03-thermobags
```

Это создаёт/обновляет `projects/2026-03-thermobags/script/verified.json`. Скилл интерактивный — агент пройдёт по строкам с `multiple`/`multi_part`/`partial` статусами.

**Step 5: Проверить отсутствие оверлапов в verified.json**

```bash
python -c "
import json
v = json.load(open('projects/2026-03-thermobags/script/verified.json', encoding='utf-8'))
overlaps = []
for row in v.get('rows', []):
    parts = row.get('chosen_parts') or []
    by_file = {}
    for p in parts:
        f = p.get('file')
        if not f: continue
        by_file.setdefault(f, []).append(p)
    for f, ps in by_file.items():
        if len(ps) < 2: continue
        ps_sorted = sorted(ps, key=lambda q: q['start'])
        for i in range(len(ps_sorted) - 1):
            a, b = ps_sorted[i], ps_sorted[i+1]
            if b['start'] < a['end']:
                overlaps.append((row.get('row_idx'), f, a['end']-b['start']))
print(f'Найдено оверлапов в verified.json: {len(overlaps)}')
for o in overlaps:
    print(f'  row={o[0]} file={o[1]} overlap={o[2]:.2f}s')
"
```

Ожидаемое:
```
Найдено оверлапов в verified.json: 0
```

**Step 6: Прогнать snap и проверить CSV**

```bash
python _scripts/match_timecodes.py snap projects/2026-03-thermobags
```

Затем проверить, что в `script.csv` rows 51, 81, 90 нет оверлапа word-границ внутри `||`:

```bash
python -c "
import csv, re
TC = re.compile(r'(\S+\.\S+):\s*(\d+):(\d+\.\d+)\s+—\s+(\d+):(\d+\.\d+)')
def to_sec(m, s): return int(m) * 60 + float(s)
with open('projects/2026-03-thermobags/script/script.csv', encoding='utf-8') as f:
    rdr = csv.reader(f)
    next(rdr)
    for ridx, row in enumerate(rdr, start=2):
        if ridx not in (51, 81, 90):
            continue
        for col_idx in (1, 3):
            if col_idx >= len(row) or '||' not in row[col_idx]:
                continue
            parts_raw = row[col_idx].split('||')
            parts = []
            for p in parts_raw:
                m = TC.search(p)
                if m:
                    parts.append((m.group(1), to_sec(m.group(2), m.group(3)), to_sec(m.group(4), m.group(5))))
            for i in range(len(parts) - 1):
                a, b = parts[i], parts[i+1]
                if a[0] == b[0] and b[1] < a[2]:
                    print(f'row={ridx} col={col_idx} overlap={a[2]-b[1]:.2f}s')
                    break
            else:
                continue
print('done')
"
```

Ожидаемое: только `done` без overlap-строк.

**Step 7: Commit изменений в проекте**

⚠ `projects/` в `.gitignore` — артефакты не трекаются. Шаг **пропускается**: пере-сгенерированные `candidates.json`, `verified.json`, `script.csv` остаются локально. Если в будущем потребуется фиксировать конкретное состояние — отдельная задача про снятие/выборочное вкладывание из ignore.

---

## Task 5: Регрессия на других проектах с `||`

**Files:**
- Read/modify: `projects/*/script/candidates.json` для проектов с составными цитатами

**Step 1: Найти проекты с `||`**

```bash
grep -l " || " projects/*/script/script.csv 2>/dev/null
```

**Step 2: Для каждого проекта прогнать search и проверить**

```bash
for proj in $(grep -l " || " projects/*/script/script.csv 2>/dev/null); do
    pdir=$(dirname $(dirname "$proj"))
    echo "=== $pdir ==="
    python _scripts/match_timecodes.py search "$pdir"
    python -c "
import json, sys
c = json.load(open('$pdir/script/candidates.json', encoding='utf-8'))
ovs = 0
for row in c.get('rows', []):
    parts = row.get('parts') or []
    for i in range(len(parts) - 1):
        for ca in parts[i].get('candidates', []):
            for cb in parts[i+1].get('candidates', []):
                if ca.get('file') != cb.get('file'): continue
                if ca['end'] > cb['start'] and ca['start'] <= cb['start']:
                    ovs += 1
print(f'  оверлапов: {ovs}')
"
done
```

Ожидаемое: для всех проектов `оверлапов: 0`.

**Step 3: Сравнить candidates.json до/после**

```bash
git diff --stat projects/*/script/candidates.json
```

Если есть проекты, где `candidates.json` изменился — это значит фикс там что-то клипнул. Просмотреть конкретные изменения:

```bash
git diff projects/<project_name>/script/candidates.json | head -100
```

Изменения должны быть только в полях `start`/`end` некоторых кандидатов (на ~50–200мс) и наличие новых полей `words_start`/`words_end` во всех. Никаких удалённых кандидатов или сломанной структуры.

**Step 4: Закоммитить изменения, если есть**

```bash
git add projects/*/script/candidates.json
git commit -m "chore: пересобрать candidates после фикса корня оверлапов"
```

Если изменений нет — пропустить.

**Step 5: Если в проекте есть готовый verified.json и assembly/ — опционально пересобрать**

Не блокер. Если хочется полной регрессии — для проектов с `verified.json` и `assembly/`:

```bash
python _scripts/match_timecodes.py snap projects/<project_name>
python _scripts/build_xml.py projects/<project_name>
```

Это валидирует, что новые таймкоды парсятся корректно. Полные глазами проверки в DaVinci — не часть этой таски.

---

## Task 6: Финальная проверка дизайна

**Step 1: Прочитать дизайн-док**

`docs/plans/2026-04-28-verified-overlap-cause-fix-design.md`

**Step 2: Сверить с реализацией**

- ✅ `_dedupe_split_overlaps` пробрасывает word-индексы и клипит по середине
- ✅ Граничное слово выкидывается из обоих при 1-word оверлапе
- ✅ Out-of-order соседи пропускаются (E3)
- ✅ Защита от схлопывания (E4)
- ✅ Whole-mode не трогается (вызов только в split-ветке)
- ✅ Дедуп идёт ДО `merge_adjacent_parts`
- ✅ `words_start`/`words_end` остаются в `candidates.json` для диагностики

**Step 3: Обновить memory**

Обновить `project_verified_json_overlap_fix.md` — отметить, что задача закрыта, со ссылкой на коммит фикса. Или удалить файл и убрать ссылку из `MEMORY.md`, если задача закрыта полностью.

```bash
# Проверить актуальное состояние memory
ls C:/Users/Alex/.claude/projects/C--Users-Alex-Videos-factory/memory/project_verified_json_overlap_fix.md
```

Если файл существует — обновить его статус на «закрыта», добавить дату и хеш коммита Task 3.

---

## Тестирование (общая стратегия)

Юнит-тестов нет, но есть три уровня верификации:

1. **Smoke-тесты `_dedupe_split_overlaps`** через `python -c` — Task 2 Step 4. 6 кейсов покрывают все edge cases дизайна (E1–E6).
2. **Регрессия на baseline** (термосумки, известные оверлапы 51/81/90) — Task 4. После фикса оверлапов 0 в `candidates.json` и `verified.json`. row 80 (нелинейная) не ломается.
3. **Регрессия на других проектах с `||`** — Task 5. Не сломали ли существующие single-cand цепочки в других проектах.

Если в будущем появится `pytest` инфраструктура — 6 кейсов из Task 2 Step 1 переносятся в `tests/test_match_timecodes.py` практически 1-в-1.

## Откат

Если что-то ломается — `git revert` коммитов из Task 2 + Task 3. `candidates.json` пере-генерируется из `match_timecodes.py search`, не входит в bisect surface.
