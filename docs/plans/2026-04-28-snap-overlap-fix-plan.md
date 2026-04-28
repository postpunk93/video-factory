# Snap Overlap Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** После `match_timecodes.py snap` соседние части одной CSV-строки в одном файле не должны перекрываться по таймкодам.

**Architecture:** Передавать в `snap_to_silence` ограничения `min_start` / `max_end` из word-границ соседних частей в той же строке и том же файле. Word-границы берутся из `verified.json` (до snap).

**Tech Stack:** Python 3, stdlib only. Кодовая база `_scripts/match_timecodes.py`, без тестового фреймворка — верификация регрессией на реальных проектах.

**Дизайн:** `docs/plans/2026-04-28-snap-overlap-fix-design.md`

> **Историческая правка (2026-04-28):** Task 3 был уточнён по ходу регрессии. Изначальная редакция использовала скриптовый порядок соседей (`parts[:i]` / `parts[i+1:]`) и warning при пересечении word-границ. Регрессия на термосумках вскрыла ложные срабатывания на нелинейных репликах (одна реплика цитирует разные минуты одного файла в скриптовом порядке ≠ исходному). Финальная редакция — source-chronological поиск соседей, warning'и убраны как недостижимые. Канонический спек — обновлённый design doc; финальный код в коммите `180ba24`. Текст Task 3 ниже оставлен как исторический артефакт.

---

## Контекст для исполнителя

В проекте нет `pytest`/`unittest` инфраструктуры. Проверка делается:
1. Прогоном `match_timecodes.py snap` на готовом проекте `projects/2026-03-thermobags`
2. Сравнением CSV до/после на конкретных строках с известным оверлапом
3. Smoke-тестами функции `snap_to_silence` через `python -c` с синтетическими данными

`projects/2026-03-thermobags/script/script.csv` уже сгенерирован с багом — служит baseline. `verified.json` тот же используется для повторного snap.

Важно: `snap_to_silence` детектит тишину через `ffmpeg silencedetect` — кэш силенсов сохраняется в `silence_cache` внутри `cmd_snap`. Повторные запуски на том же проекте детектят тишину заново (~30 сек на термосумках).

---

## Task 1: Зафиксировать baseline

**Files:**
- Read: `projects/2026-03-thermobags/script/script.csv`

**Step 1: Сохранить таймкоды строк с известным оверлапом**

Из текущего CSV выписать в `/tmp/snap_baseline.txt` (или вывести в stdout) строки 22, 28, 51, 80, 81, 82, 90 — только колонку «Герой Таймкоды» (4-я колонка, индекс 3). Это нужно для последующего сравнения.

Известные оверлапы:
- Строка 22: `04:37.44 — 04:53.15 || 04:50.47 — 05:01.65` (оверлап 2.68с)
- Строка 28: `08:16.14 — 08:21.59 || 08:20.12 — 08:22.67` (оверлап 1.47с)
- Строка 51: тут оверлап в колонке Слава — `07:23.05 — 07:32.49 || 07:31.30 — 07:36.93` (оверлап 1.19с) — **это другая колонка**, индекс 1
- Строка 80: 5 частей в `термосумки 1.mp4` с почти идентичными границами (44:43.12 повторяется)
- Строка 81: индекс 1, оверлап 0.14с
- Строка 82: оверлап 0.04с
- Строка 90: оверлап 0.13с

**Step 2: Commit (опционально)**

Этот шаг ничего не меняет в репо — пропускаем коммит.

---

## Task 2: Расширить сигнатуру `snap_to_silence`

**Files:**
- Modify: `_scripts/match_timecodes.py:609-631`

**Step 1: Изменить сигнатуру и логику**

Заменить функцию целиком:

```python
def snap_to_silence(start: float, end: float, silences: list[dict],
                    window: float = 2.0,
                    min_start: float = 0.0,
                    max_end: float = float("inf")) -> tuple[float, float]:
    """Привязывает start к ближайшему silence_end до него, end — к ближайшему silence_start после.

    min_start / max_end — жёсткие ограничения: snapped_start не меньше min_start,
    snapped_end не больше max_end. Если в ограниченном окне нет подходящей тишины —
    fallback на оригинальный start / end (без snap)."""
    snapped_start = start
    snapped_end = end

    best_dist_start = window
    for s in silences:
        # silence_end до start (±0.1s допуск на перекрытие), не раньше min_start
        if s["end"] < min_start:
            continue
        dist = max(0, start - s["end"])
        if s["end"] <= start + 0.1 and dist < best_dist_start:
            best_dist_start = dist
            snapped_start = s["end"]

    best_dist_end = window
    for s in silences:
        # silence_start после end (±0.1s допуск на перекрытие), не позже max_end
        if s["start"] > max_end:
            continue
        dist = max(0, s["start"] - end)
        if s["start"] >= end - 0.1 and dist < best_dist_end:
            best_dist_end = dist
            snapped_end = s["start"]

    return round(snapped_start, 2), round(snapped_end, 2)
```

Ключевые отличия:
- Два новых параметра по умолчанию (обратно совместимо)
- В первом цикле `if s["end"] < min_start: continue` — отсекаем тишины, лежащие до соседа
- Во втором цикле `if s["start"] > max_end: continue` — отсекаем тишины, лежащие после соседа
- Если ни одна тишина не прошла фильтр — переменные `snapped_start` / `snapped_end` остаются равны входным `start` / `end` (fallback на word-boundary)

**Step 2: Smoke-тест функции**

```bash
cd C:/Users/Alex/Videos/factory
python -c "
import sys; sys.path.insert(0, '_scripts')
from match_timecodes import snap_to_silence

# Силенсы как в реальном кейсе: тишина после слова и до слова, но не между ними
silences = [
    {'start': 290.10, 'end': 290.47},  # тишина перед 'приходила'
    {'start': 293.15, 'end': 294.00},  # тишина после 'садилась за машину'
]

# Без ограничений — баг воспроизводится
ss, se = snap_to_silence(277.44, 291.23, silences)
print('Without bounds: P2 =', ss, '->', se)
ss, se = snap_to_silence(292.19, 300.58, silences)
print('Without bounds: P3 =', ss, '->', se)

# С ограничениями — оверлапа нет
ss, se = snap_to_silence(277.44, 291.23, silences, max_end=292.19)
print('With max_end=292.19: P2 =', ss, '->', se)
ss, se = snap_to_silence(292.19, 300.58, silences, min_start=291.23)
print('With min_start=291.23: P3 =', ss, '->', se)
"
```

Ожидаемый вывод:
```
Without bounds: P2 = 277.44 -> 293.15      ← баг
Without bounds: P3 = 290.47 -> 300.58      ← баг
With max_end=292.19: P2 = 277.44 -> 291.23  ← fallback на word-boundary
With min_start=291.23: P3 = 292.19 -> 300.58  ← fallback на word-boundary
```

Если silence находится ВНУТРИ ограниченного окна — он используется. Добавить второй прогон с тишиной в gap:

```bash
python -c "
import sys; sys.path.insert(0, '_scripts')
from match_timecodes import snap_to_silence

# Силенс точно в gap между словами
silences = [{'start': 291.30, 'end': 292.10}]

ss, se = snap_to_silence(277.44, 291.23, silences, max_end=292.19)
print('Silence in gap, P2 end:', se)  # ожидаем 291.30
ss, se = snap_to_silence(292.19, 300.58, silences, min_start=291.23)
print('Silence in gap, P3 start:', ss)  # ожидаем 292.10
"
```

Ожидаемый вывод:
```
Silence in gap, P2 end: 291.3
Silence in gap, P3 start: 292.1
```

**Step 3: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): min_start/max_end в snap_to_silence"
```

---

## Task 3: Считать соседей в `cmd_snap`

**Files:**
- Modify: `_scripts/match_timecodes.py:805-818` (внутри `cmd_snap`, секция «Привязываем таймкоды»)

**Step 1: Заменить snap-цикл с учётом соседей**

Найти блок:

```python
    # Привязываем таймкоды
    for row in verified["rows"]:
        parts = _get_chosen_parts(row)
        if not parts:
            continue

        snapped_parts: list[tuple[str, float, float]] = []
        for p in parts:
            fname = p.get("file")
            if not fname:
                continue
            silences = silence_cache.get(fname, [])
            ss, se = snap_to_silence(p["start"], p["end"], silences)
            snapped_parts.append((fname, ss, se))
```

Заменить на:

```python
    # Привязываем таймкоды
    for row in verified["rows"]:
        parts = _get_chosen_parts(row)
        if not parts:
            continue

        snapped_parts: list[tuple[str, float, float]] = []
        for i, p in enumerate(parts):
            fname = p.get("file")
            if not fname:
                continue

            # Ближайший предыдущий парт в том же файле (внутри строки)
            prev = next((q for q in reversed(parts[:i]) if q.get("file") == fname), None)
            # Ближайший следующий парт в том же файле (внутри строки)
            nxt = next((q for q in parts[i+1:] if q.get("file") == fname), None)

            min_start = prev["end"] if prev else 0.0
            max_end = nxt["start"] if nxt else float("inf")

            # Защита от уже пересекающихся word-границ в verified.json
            if min_start > p["start"]:
                print(f"  Внимание: строка {row['row_idx']} — word-границы соседних частей пересекаются "
                      f"(prev.end={min_start} > p.start={p['start']}), снимаем нижнее ограничение")
                min_start = 0.0
            if max_end < p["end"]:
                print(f"  Внимание: строка {row['row_idx']} — word-границы соседних частей пересекаются "
                      f"(nxt.start={max_end} < p.end={p['end']}), снимаем верхнее ограничение")
                max_end = float("inf")

            silences = silence_cache.get(fname, [])
            ss, se = snap_to_silence(p["start"], p["end"], silences,
                                     min_start=min_start, max_end=max_end)
            snapped_parts.append((fname, ss, se))
```

Ключевое:
- `parts[:i]` + `reversed` для поиска предыдущего соседа в том же файле
- `parts[i+1:]` для поиска следующего
- Если `prev`/`nxt` в другом файле — игнорируем (соседями не считаем)
- Защита от уже пересекающихся word-границ в `verified.json` (edge case из дизайна)

**Step 2: Verify (синтаксис)**

```bash
python -c "import sys; sys.path.insert(0, '_scripts'); import match_timecodes"
```

Ожидаемое: ничего не печатает (импорт успешный).

**Step 3: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "fix(match_timecodes): snap не пересекает соседнюю часть в той же строке"
```

---

## Task 4: Регрессия на термосумках

**Files:**
- Read: `projects/2026-03-thermobags/script/script.csv` (после прогона)

**Step 1: Прогнать snap**

```bash
python _scripts/match_timecodes.py snap projects/2026-03-thermobags
```

Ожидаемое:
- Команда отрабатывает без ошибок
- В выводе могут быть warning'и про edge case (если в `verified.json` есть пересечения word-границ — на термосумках, вероятно, нет)
- На экране печатается `Строка N: K часть(и) — ...` для каждой строки с `chosen_parts`

**Step 2: Проверить отсутствие оверлапов**

Просмотреть строки 22, 28, 51, 80, 81, 82, 90 в `projects/2026-03-thermobags/script/script.csv`. Для каждой пары соседних частей в **одном файле** в одной строке убедиться, что `end[i] ≤ start[i+1]`.

Конкретно для строки 22: было `04:37.44 — 04:53.15 || 04:50.47 — 05:01.65`. Должно стать что-то вроде `04:37.44 — 04:51.23 || 04:52.19 — ...` (точные значения зависят от того, есть ли silence в gap; если нет — fallback на word-boundary).

Можно использовать grep для быстрой проверки:

```bash
grep -n "04:37.44\|04:50.47" projects/2026-03-thermobags/script/script.csv
```

**Step 3: Commit изменений в CSV**

```bash
git add projects/2026-03-thermobags/script/script.csv
git commit -m "chore(thermobags): пересобрать таймкоды после фикса snap-оверлапов"
```

---

## Task 5: Регрессия на других проектах с `||`

**Files:**
- Read/modify: `projects/tulips/script/script.csv`, `projects/2026-04-kozha/script/script.csv`, `projects/2026-04-ustritsy/script/script.csv`, `projects/2026-03-vendingi/script/script.csv` (если есть)

**Step 1: Найти проекты с составными цитатами**

```bash
grep -l " || " projects/*/script/script.csv
```

**Step 2: Для каждого проекта с `||` прогнать snap**

```bash
python _scripts/match_timecodes.py snap projects/<project_name>
```

Сравнить CSV до/после через `git diff projects/<project_name>/script/script.csv`. Изменения должны быть только в строках с `||` (составными цитатами). Одиночные парты (без `||`) не должны измениться.

**Step 3: Если есть изменения — закоммитить**

```bash
git add projects/<project_name>/script/script.csv
git commit -m "chore(<project>): пересобрать таймкоды после фикса snap-оверлапов"
```

Если изменений нет — пропустить.

**Step 4: Если в проекте есть assembly/ — пересобрать XML**

```bash
python _scripts/build_xml.py projects/<project_name>
```

(Опционально, не блокер.) Это валидирует, что новые таймкоды парсятся корректно.

---

## Task 6: Финальная проверка дизайна

**Step 1: Прочитать дизайн-док**

`docs/plans/2026-04-28-snap-overlap-fix-design.md`

**Step 2: Сверить с реализацией**

- ✅ `snap_to_silence` принимает `min_start` и `max_end`
- ✅ Fallback на word-boundary при отсутствии тишины в окне
- ✅ Соседи только в том же файле и той же строке
- ✅ Между CSV-строками — без ограничений
- ✅ Warning при уже пересекающихся word-границах в `verified.json`

**Step 3: Если в реализации есть отклонения от дизайна — обновить дизайн или код**

---

## Тестирование (общая стратегия)

Юнит-тестов нет, но есть три уровня верификации:

1. **Smoke-тесты `snap_to_silence`** через `python -c` — Task 2 Step 2
2. **Регрессия на baseline-проекте** (термосумки, известные оверлапы) — Task 4
3. **Регрессия на других проектах** (не сломали одиночные парты) — Task 5

Если в будущем появится `pytest` инфраструктура — три кейса из Task 2 Step 2 переносятся в `tests/test_match_timecodes.py` практически 1-в-1.
