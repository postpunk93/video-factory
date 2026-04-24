# Cutting Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Добавить поддержку составных цитат героя (склейка из нескольких фрагментов) и очистку интервью от оговорок через профиль `hero` в `cut_pauses.py`.

**Architecture:** Два независимых блока. Блок A расширяет `cut_pauses.py` новыми паттернами и профилями. Блок B добавляет `parts[]` в `match_timecodes.py`, новый формат таймкодов в CSV (`||`-разделитель), и рендер N клипов впритык в `build_xml.py`.

**Tech Stack:** Python 3.12, `faster-whisper` (уже используется в `cut_pauses.py`), `ffmpeg`, стандартная `pathlib`/`csv`/`json`/`xml.etree`.

**Design doc:** `docs/plans/2026-04-23-cutting-improvements-design.md`

**Testing approach:** В проекте нет test framework. Используем ручные проверки на реальных проектах (`projects/tulips`, `projects/2026-03-vendingi`) + синтетические fixture-файлы в `_scripts/tests_manual/`. Каждая задача завершается командой запуска и ожидаемым наблюдаемым результатом.

**Commit discipline:** Коммитим после каждой задачи. Git branch: работаем на `master`.

---

## Блок A: `cut_pauses.py` — профиль `hero`

### Task A1: добавить константы паттернов

**Files:**
- Modify: `_scripts/cut_pauses.py` (секция констант в начале файла, после `FILLER_WORDS`)

**Step 1: добавить константы**

В `_scripts/cut_pauses.py` добавить `import re` в блок импортов. Исправить `FILLER_WORDS` — убрать оттуда `"эм"` и `"ам"` (они звуки, не слова-паразиты, и корректно ловятся через `INTERJECTIONS`). После `FILLER_WORDS` добавить:

```python
# Междометия и звуки — НЕ русские слова, точно оговорки
INTERJECTIONS = {
    "э", "эээ", "ээ", "ммм", "мм", "эм", "ам",
    "ох", "эх", "хм", "ой",
}

# Заикания вида "я-я", "я-я-я", "к-к-как" — первая буква повторяется через дефис
STUTTER_RE = re.compile(r"^([а-яёa-z])(-\1)+(-[а-яёa-z]+)?$")

GAP_BETWEEN_SEGMENTS = 0.15  # уже есть, оставить как было
```

**Step 2: проверить, что файл парсится**

Run: `python -c "import _scripts.cut_pauses"` (или открыть файл, если модуль не импортируется напрямую из-за shebang)
Expected: без ошибок синтаксиса.

Или просто: `python _scripts/cut_pauses.py --help`
Expected: help-сообщение выводится без ошибок.

**Step 3: Commit**

```bash
git add _scripts/cut_pauses.py
git commit -m "feat(cut_pauses): добавить константы INTERJECTIONS и STUTTER_RE"
```

---

### Task A2: функция-классификатор слова

**Files:**
- Modify: `_scripts/cut_pauses.py` (добавить функцию `should_cut_word`)

**Step 1: добавить функцию `should_cut_word`**

Добавить до обработки сегментов (там, где сейчас используется `FILLER_WORDS`):

```python
import re

_EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$")


def normalize_word(word: str) -> str:
    """Нижний регистр + убрать пунктуацию по краям."""
    return _EDGE_PUNCT_RE.sub("", word.lower())


def should_cut_word(word_text: str, profile: str) -> str | None:
    """Определяет, нужно ли вырезать слово. Возвращает причину (str) или None.

    profile: 'slava' — агрессивный, вырезает FILLER_WORDS + общие паттерны.
             'hero'  — мягкий, только междометия/заикания (FILLER_WORDS не трогаем).
    """
    norm = normalize_word(word_text)
    if not norm:
        return None

    # Заикания — оба профиля
    if STUTTER_RE.match(norm):
        return "stutter"

    # Междометия — оба профиля
    if norm in INTERJECTIONS:
        return "interjection"

    # Слова-паразиты — только slava
    if profile == "slava" and norm in FILLER_WORDS:
        return "filler"

    return None
```

**Step 2: запустить линт/синтаксис-чек**

Run: `python _scripts/cut_pauses.py --help`
Expected: help выводится без ошибок, никакой новой функциональности не активировано.

**Step 3: Commit**

```bash
git add _scripts/cut_pauses.py
git commit -m "feat(cut_pauses): добавить should_cut_word и normalize_word"
```

---

### Task A3: детекция повторов подряд

**Files:**
- Modify: `_scripts/cut_pauses.py` (добавить функцию `mark_repeat_duplicates`)

**Step 1: добавить функцию**

```python
def mark_repeat_duplicates(words: list[dict], max_gap: float = 1.5) -> list[bool]:
    """Возвращает маску того же размера: True — слово нужно вырезать (повтор).

    Правило: если токен[i] == токен[i-1] (нормализованно) и start[i] - end[i-1] < max_gap,
    то вырезаем word[i-1] (оставляем последний повтор). Работает каскадно на сериях 3+.
    """
    if len(words) < 2:
        return [False] * len(words)

    mask = [False] * len(words)
    # Проходим с конца: i-й остаётся, предыдущие совпадающие режем
    for i in range(len(words) - 1, 0, -1):
        prev = i - 1
        if mask[i]:  # сам уже вырезан — не якорь
            continue
        while prev >= 0:
            cur_norm = normalize_word(words[i].get("word", ""))
            prev_norm = normalize_word(words[prev].get("word", ""))
            if not cur_norm or not prev_norm or cur_norm != prev_norm:
                break
            gap = words[i].get("start", 0) - words[prev].get("end", 0)
            if gap > max_gap or gap < 0:
                break
            mask[prev] = True
            # anchor для следующей итерации не меняем — сравниваем с тем же i
            i = prev  # но продолжаем свёртку влево
            prev = i - 1
    return mask
```

**Step 2: быстрая проверка вручную**

Создать одноразовый тестовый скрипт (не коммитим):

```bash
python -c "
from _scripts.cut_pauses import mark_repeat_duplicates, normalize_word
words = [
    {'word': 'я',   'start': 0.0, 'end': 0.2},
    {'word': 'я',   'start': 0.3, 'end': 0.5},
    {'word': 'я',   'start': 0.6, 'end': 0.8},
    {'word': 'хотел','start': 0.9, 'end': 1.3},
    {'word': 'сказать','start': 1.4, 'end': 1.9},
]
print(mark_repeat_duplicates(words))
"
```
Expected: `[True, True, False, False, False]` — первые два «я» вырезаны, третий остался.

**Step 3: Commit**

```bash
git add _scripts/cut_pauses.py
git commit -m "feat(cut_pauses): детекция повторов подряд"
```

---

### Task A4: добавить флаг `--profile` и интегрировать в main-цикл

**Files:**
- Modify: `_scripts/cut_pauses.py` (функция `parse_args`, основной цикл обработки)

**Step 1: найти, где сейчас фильтруются слова**

В `_scripts/cut_pauses.py` найти место, где обходятся word-level результаты whisper и решается, оставить ли слово. Сейчас там используется `FILLER_WORDS`. Это внутри функции, формирующей сегменты из транскрипта.

**Step 2: добавить флаг `--profile`**

В `parse_args`:

```python
parser.add_argument(
    "--profile", choices=["slava", "hero"], default="slava",
    help="Профиль чистки: slava (агрессивный + FILLER_WORDS) или hero (мягкий, только оговорки)"
)
```

**Step 3: заменить логику фильтрации**

Там, где была проверка `if word.lower() in FILLER_WORDS: continue` (или аналогичная) — заменить на использование `should_cut_word(word_text, args.profile)` + применить маску `mark_repeat_duplicates`.

Pseudocode:

```python
# до основного цикла:
repeat_mask = mark_repeat_duplicates(all_words)

for i, w in enumerate(all_words):
    if repeat_mask[i]:
        continue  # повтор — вырезаем
    reason = should_cut_word(w.get("word", ""), args.profile)
    if reason is not None:
        continue  # вырезаем
    # ... существующая логика: добавить к текущему сегменту
```

**Точный патч зависит от текущей структуры.** Вариант: новую логику завернуть в helper `filter_words(words, profile)`, возвращающий `list[dict]` с оставшимися словами, и вызвать его один раз до основного цикла.

**Step 4: проверить, что обработка работает на реальном файле**

Run:
```bash
python _scripts/cut_pauses.py projects/tulips/raw/voiceover/1773574086.543356.mov --profile slava --output /tmp/tulips_slava.mov
```
Expected: файл обрабатывается без ошибок, `/tmp/tulips_slava.mov` создан, длительность примерно совпадает со старой `tulips/cuts/voiceover/1773574086.543356_clean.mov` (если есть) или с ожидаемой.

**Step 5: Commit**

```bash
git add _scripts/cut_pauses.py
git commit -m "feat(cut_pauses): флаг --profile (slava|hero) + интеграция паттернов"
```

---

### Task A5: проверить профиль `hero` на реальном интервью

**Files:** тестовый прогон, код не меняем.

**Step 1: запустить на `vendingi`**

```bash
python _scripts/cut_pauses.py projects/2026-03-vendingi/raw/interviews/вендинг1.m4a --profile hero --output /tmp/hero_test.m4a --save-transcript
```

**Step 2: проверить длительность**

```bash
ffprobe -v quiet -show_entries format=duration -of default=nw=1:nk=1 projects/2026-03-vendingi/raw/interviews/вендинг1.m4a
ffprobe -v quiet -show_entries format=duration -of default=nw=1:nk=1 /tmp/hero_test.m4a
```
Expected: чистая версия на 3–15% короче исходника.

**Step 3: прослушать 2-3 минуты**

Открыть `/tmp/hero_test.m4a` в плеере. Проверить:
- смысл речи сохранён
- `ну`, `типа`, `короче`, `как бы` **не вырезаны**
- явные «эм», «эээ», повторы «я-я-я» — вырезаны
- склейки не звучат рвано

**Step 4: зафиксировать наблюдения**

Если всё ок — ничего не коммитим (код не менялся). Если нужно крутить пороги — вернуться в A1 и скорректировать `INTERJECTIONS`/`STUTTER_RE`/`max_gap`, закоммитить отдельно.

---

## Блок B: составные цитаты

### Task B1: fuzzy whole-match (Smith-Waterman по словам)

**Files:**
- Modify: `_scripts/match_timecodes.py` (добавить функцию `fuzzy_whole_match`)

**Step 1: добавить алгоритм**

Добавить перед `find_candidates`:

```python
def fuzzy_whole_match(phrase: str, transcripts: dict, min_score: float = 0.85):
    """Smith-Waterman по словам. Возвращает лучший part (dict) или None.

    Возвращаемый part: {file, start, end, score, words_matched, total_words}
    Score = words_matched / total_words_in_phrase.
    """
    pwords = normalize(phrase).split()
    if len(pwords) < 3:
        return None

    best = None

    for filename, tdata in transcripts.items():
        words = tdata["words"]
        twords = [normalize(w.get("word", "")) for w in words]

        # Smith-Waterman: матрица score[i][j]
        n, m = len(pwords), len(twords)
        # Для памяти: храним только 2 строки. Но нам нужна также позиция начала — храним полный traceback.
        # Упрощённая реализация: линейное окно поиска.

        # Для простоты — скользящее окно длиной len(pwords) с допуском пропусков.
        # Точный SW здесь избыточен; используем longest-common-subsequence в окне.

        window_len = int(len(pwords) * 1.3) + 5  # окно чуть больше чем фраза
        for start_idx in range(0, max(1, m - window_len + 1)):
            end_idx = min(m, start_idx + window_len)
            window = twords[start_idx:end_idx]

            # LCS между pwords и window
            lcs_len = _lcs_length(pwords, window)
            score = lcs_len / len(pwords)

            if score >= min_score and (best is None or score > best["score"]):
                start_t = _safe_time(words[start_idx], "start", words, start_idx)
                end_t = _safe_time(words[end_idx - 1], "end", words, end_idx - 1)
                best = {
                    "file": filename,
                    "start": round(start_t, 2),
                    "end": round(end_t, 2),
                    "score": round(score, 3),
                    "words_matched": lcs_len,
                    "total_words": len(pwords),
                }
    return best


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Длина LCS двух списков слов."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[m]
```

**Step 2: быстрая проверка**

```bash
python -c "
import sys
sys.path.insert(0, '_scripts')
from match_timecodes import fuzzy_whole_match, load_transcripts
from pathlib import Path
tr = load_transcripts(Path('projects/tulips'))
# Берём цитату, которая есть целиком
phrase = 'У нас проблемы начинаются самые большие в январе'
print(fuzzy_whole_match(phrase, tr))
"
```
Expected: dict с `file='Тюльпаны 2.mp4'` (или `_clean`), корректный start/end, score ≥ 0.85.

**Step 3: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): fuzzy whole-match для одиночных цитат"
```

---

### Task B2: split by sentences + merge adjacent

**Files:**
- Modify: `_scripts/match_timecodes.py` (добавить `split_sentences`, `merge_adjacent_parts`, `find_quote_parts`)

**Step 1: добавить три функции**

```python
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Делит текст по [.!?]. Пустые/тривиальные (<3 слов) игнорируются."""
    parts = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return [p for p in parts if len(p.split()) >= 3]


def merge_adjacent_parts(parts: list[dict], max_gap: float = 3.0) -> list[dict]:
    """Склеивает соседние parts, которые в одном файле и разрыв < max_gap сек."""
    if len(parts) < 2:
        return parts
    merged = [parts[0]]
    for p in parts[1:]:
        last = merged[-1]
        if (p["file"] == last["file"]
                and 0 <= p["start"] - last["end"] < max_gap):
            merged[-1] = {
                "file": last["file"],
                "start": last["start"],
                "end": p["end"],
                "text": last["text"] + " " + p["text"],
            }
        else:
            merged.append(p)
    return merged


def find_quote_parts(phrase: str, transcripts: dict) -> dict:
    """Главная функция поиска. Возвращает:
    {
        "parts": [{file, start, end, text, candidates}],
        "unmatched": [str],
        "mode": "whole" | "split",
    }
    Для whole-match parts содержит один элемент со списком candidates длины 1.
    Для split-match каждый part имеет только свои candidates.
    """
    whole = fuzzy_whole_match(phrase, transcripts)
    if whole is not None:
        return {
            "parts": [{
                "text": phrase,
                "candidates": [{
                    "file": whole["file"],
                    "start": whole["start"],
                    "end": whole["end"],
                }],
            }],
            "unmatched": [],
            "mode": "whole",
        }

    sentences = split_sentences(phrase)
    if not sentences:
        # Короткая фраза — один "части" с обычным кандидатским поиском
        cands = find_candidates(phrase, transcripts)
        return {
            "parts": [{
                "text": phrase,
                "candidates": [
                    {"file": c["file"], "start": c["start"], "end": c["end"]}
                    for c in cands
                ],
            }],
            "unmatched": [],
            "mode": "split",
        }

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

    # Merge adjacent: только для частей с единственным кандидатом.
    single_cand_parts = [
        {"file": p["candidates"][0]["file"],
         "start": p["candidates"][0]["start"],
         "end": p["candidates"][0]["end"],
         "text": p["text"]}
        for p in parts_out if len(p["candidates"]) == 1
    ]
    merged = merge_adjacent_parts(single_cand_parts)

    # Сливаем обратно: заменяем одиночно-кандидатные подряд идущие на слитые
    # Простая реализация: если все parts_out имеют 1 кандидата — возвращаем merged.
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

**Step 2: ручная проверка на синтетической цитате**

Создать тестовый CSV (`/tmp/test_split.csv`) с одной составной строкой, закинуть в существующий проект (`projects/tulips/script/script.csv` бекапим, заменяем):

```bash
cp projects/tulips/script/script.csv projects/tulips/script/script.csv.bak
```

Затем в CSV одну из строк героя вручную заменить на составную цитату (S1 из одного файла, S2 из другого). Прогнать:

```bash
python _scripts/match_timecodes.py search projects/tulips
```
Expected: в `candidates.json` эта строка имеет `mode: "split"`, `parts[]` длины 2, каждая с правильным файлом.

**Step 3: восстановить CSV**

```bash
cp projects/tulips/script/script.csv.bak projects/tulips/script/script.csv
rm projects/tulips/script/script.csv.bak
```

**Step 4: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): split by sentences + merge adjacent parts"
```

---

### Task B3: интегрировать `find_quote_parts` в `cmd_search`

**Files:**
- Modify: `_scripts/match_timecodes.py` (функция `cmd_search`, формат `candidates.json`)

**Step 1: изменить `cmd_search`**

Заменить блок, где сейчас вызывается `find_candidates(...)` и формируется `rows_out`:

```python
result = find_quote_parts(line["text"], filtered)
parts = result["parts"]
unmatched = result["unmatched"]

if not parts and unmatched:
    # Все предложения провалились — это not_found, а не partial.
    status = "not_found"
    stats["not_found"] += 1
elif unmatched:
    status = "partial"
    stats["partial"] += 1
elif len(parts) > 1:
    status = "multi_part"
    stats["multi_part"] += 1
elif len(parts) == 1 and len(parts[0]["candidates"]) == 1:
    status = "single"
    stats["single"] += 1
elif len(parts) == 1 and len(parts[0]["candidates"]) > 1:
    status = "multiple"
    stats["multiple"] += 1
else:
    status = "not_found"
    stats["not_found"] += 1

# Вывод
if status == "single":
    c = parts[0]["candidates"][0]
    print(f"  ✓ Строка {line['row_idx']}: {fmt_tc(c['start'])} -> {fmt_tc(c['end'])} — {line['text'][:60]}")
elif status == "multi_part":
    print(f"  ≈ Строка {line['row_idx']}: {len(parts)} частей — {line['text'][:60]}")
elif status == "partial":
    print(f"  ⚠ Строка {line['row_idx']}: {len(parts)} найдено, {len(unmatched)} нет — {line['text'][:60]}")
elif status == "multiple":
    locs = ", ".join(fmt_tc(c["start"]) for c in parts[0]["candidates"])
    print(f"  ? Строка {line['row_idx']}: {len(parts[0]['candidates'])} кандидатов [{locs}] — {line['text'][:60]}")
else:
    print(f"  ✗ Строка {line['row_idx']}: НЕ НАЙДЕНО — {line['text'][:60]}")

rows_out.append({
    "row_idx": line["row_idx"],
    "speaker": speaker,
    "col": line["col"],
    "text": line["text"],
    "parts": parts,
    "unmatched": unmatched,
    "mode": result["mode"],
    "status": status,
})
```

Также поправить инициализацию `stats` — добавить ключи `multi_part`, `partial`.

**Step 2: обновить вывод статистики**

В конце `cmd_search`:

```python
print(f"\n=== Статистика ===")
print(f"  Single:     {stats['single']}")
print(f"  Multiple:   {stats['multiple']}")
print(f"  Multi-part: {stats.get('multi_part', 0)}")
print(f"  Partial:    {stats.get('partial', 0)}")
print(f"  Not found:  {stats['not_found']}")
```

**Step 3: проверить регрессию**

```bash
cp projects/tulips/script/candidates.json /tmp/candidates_before.json  # если есть
python _scripts/match_timecodes.py search projects/tulips
```
Expected: работает без ошибок. Строки, которые раньше были `single`, остались такими же (whole-match сработал). `parts[0]["candidates"][0]` должен совпасть по файлу и таймкодам с предыдущим значением.

**Step 4: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): интеграция find_quote_parts в cmd_search"
```

---

### Task B4: обновить skill `/match-timecodes` (документация)

**Files:**
- Modify: файл skill (обычно `.claude/skills/match-timecodes/SKILL.md` или аналогичный)

**Step 1: найти файл skill**

```bash
find .claude ~/.claude -name "*match-timecodes*" 2>/dev/null | head -5
```
Ожидание: путь найден (возможно в `.claude/skills/match-timecodes/SKILL.md` или `~/.claude/skills/...`).

Если файла нет в репо — skill живёт глобально. Тогда документируем новый формат в `CLAUDE.md` раздел `/match-timecodes`.

**Step 2: описать новый формат `candidates.json`**

В skill-документации добавить:

```markdown
## Формат candidates.json

Каждая строка `rows[i]` содержит:
- `status`: single | multiple | multi_part | partial | not_found
- `parts`: список частей цитаты. Для одиночной — длина 1. Для составной — >1.
  Каждая часть: `{text, candidates: [{file, start, end}, ...]}`
- `unmatched`: список предложений, которые не удалось найти нигде.
- `mode`: "whole" (нашлось целиком) или "split" (по предложениям).

Задача агента:
1. Для `single` — убедиться что единственный кандидат в `parts[0].candidates[0]` верен.
2. Для `multiple` — выбрать правильный кандидат из `parts[0].candidates`.
3. Для `multi_part` — пройти по всем `parts[]`, для каждой либо подтвердить единственный
   кандидат, либо выбрать правильный из списка. Убедиться что порядок по времени осмыслен.
4. Для `partial` — разобраться с `unmatched`: возможно переформулировать поиск,
   посмотреть в другие транскрипты, или пометить как вручную подтверждаемую.
5. Для `not_found` — пометить в `verified.json` как пропуск, оставить комментарий.

Результат пишется в `verified.json` с полем `chosen_parts[]` (каждой части свой выбор).
```

**Step 3: Commit**

```bash
git add <skill-файл-или-CLAUDE.md>
git commit -m "docs(match-timecodes): документация формата parts[] и multi_part статуса"
```

---

### Task B5: `cmd_snap` — привязка частей к тишине + новый формат CSV

**Files:**
- Modify: `_scripts/match_timecodes.py` (функция `cmd_snap`)

**Step 1: адаптировать под новый формат `verified.json`**

Ожидаем что `verified.json` теперь имеет `chosen_parts[]` вместо `chosen`. Для обратной совместимости поддерживаем оба формата.

В `cmd_snap`:

```python
for row in verified["rows"]:
    chosen_parts = row.get("chosen_parts")
    if chosen_parts is None:
        # Старый формат: один chosen
        chosen = row.get("chosen")
        if not chosen or not chosen.get("file"):
            continue
        chosen_parts = [chosen]

    if not chosen_parts:
        continue

    # Собираем имена файлов для silence detect
    for p in chosen_parts:
        fname = p.get("file")
        if fname:
            files_needed.add(fname)
```

Вынести silence detect в цикле (уже есть).

**Step 2: snap каждой части**

```python
snapped_parts = []
for p in chosen_parts:
    fname = p["file"]
    silences = silence_cache.get(fname, [])
    ss, se = snap_to_silence(p["start"], p["end"], silences)
    snapped_parts.append((fname, ss, se))

# Сборка строки таймкода
tc_strs = [f"{fn}: {fmt_tc(s)} — {fmt_tc(e)}" for fn, s, e in snapped_parts]
tc_str = " || ".join(tc_strs)

# Запись в CSV
ridx = row["row_idx"]
tc_col = row.get("col", 1)
csv_idx = ridx - 1
if csv_idx < len(csv_rows):
    while len(csv_rows[csv_idx]) <= tc_col:
        csv_rows[csv_idx].append("")
    csv_rows[csv_idx][tc_col] = tc_str

print(f"  Строка {ridx}: {len(snapped_parts)} часть(и) -> {tc_str[:80]}")
```

**Step 3: проверить на синтетических данных**

Создать руками `/tmp/verified.json` c одной строкой, у которой `chosen_parts` длины 2 (разные файлы). Прогнать:

```bash
cp /tmp/verified.json projects/tulips/script/verified.json
python _scripts/match_timecodes.py snap projects/tulips
cat projects/tulips/script/script.csv | head -5
```
Expected: в CSV видим строку с `||`.

Откат: `git checkout projects/tulips/script/script.csv` и удалить тестовый verified.json.

**Step 4: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): snap по частям, формат CSV с разделителем ||"
```

---

### Task B6: `build_xml.py` — парсер `||` и рендер клипов впритык

**Files:**
- Modify: `_scripts/build_xml.py` (функция `parse_unified_tc`, главный цикл сборки)

**Step 1: обновить `parse_unified_tc`**

Переименовать в `parse_unified_tc_parts` (или расширить существующую) чтобы возвращала `list[tuple]`:

```python
def parse_unified_tc_parts(tc_str: str, filename_to_key: dict) -> list[tuple]:
    """Парсит строку таймкодов, возможно с разделителем ||.

    Возвращает список (file_key, start_sec, end_sec). Пустой если не парсится.
    """
    if not tc_str or not tc_str.strip():
        return []
    segments = [s.strip() for s in tc_str.split("||") if s.strip()]
    parts = []
    for seg in segments:
        one = parse_unified_tc(seg, filename_to_key)  # существующая логика для одного
        if one is None:
            print(f"  WARN: не парсится часть таймкода: {seg}")
            return []  # вся строка невалидна
        parts.append(one)
    return parts
```

Существующая `parse_unified_tc` остаётся, парсит один сегмент.

**Step 2: адаптировать сборку клипов**

В главном цикле сборки XML (где сейчас формируется один `clip` на строку):

```python
# Было:
# parsed = parse_unified_tc(tc_str, filename_to_key)
# if parsed is None: continue
# file_key, src_start, src_end = parsed
# ... создание одного clip

# Стало:
parts = parse_unified_tc_parts(tc_str, filename_to_key)
if not parts:
    continue

# Все части идут впритык на таймлайне.
# seq_cursor_for_row — текущая позиция в секундах; для частей второй, третьей и т.д.
# она наращивается на длительность каждой предыдущей части.
# Это влияет только на расчёт seq_start/seq_end каждой части.

row_seq_start = ...  # как раньше вычислялось для строки
cursor = row_seq_start
for (file_key, src_start, src_end) in parts:
    part_duration = src_end - src_start
    clip = {
        "file_key": file_key,
        "src_start": src_start,
        "src_end": src_end,
        "seq_start": cursor,
        "seq_end": cursor + part_duration,
        "track": "hero" if speaker == "hero" else "slava",
        "name": row_name,  # или row_name + f" ({i+1}/{len(parts)})"
    }
    clips.append(clip)
    cursor += part_duration
```

**Важно:** где вычисляется `row_seq_start` — это существующая логика, не менять её смысл. Следующая строка сценария должна начинаться в `cursor` после всех частей этой строки.

**Step 3: регрессия на tulips**

```bash
python _scripts/build_xml.py projects/tulips
diff projects/tulips/assembly/tulips_rough_cut.xml /tmp/tulips_rough_cut_before.xml
```
Expected: файл байт-в-байт такой же как до изменений (потому что все строки — single part). Если есть различия, они должны быть только там, где есть `||`.

Для получения «до» запустить на предыдущем коммите в стеше или параллельно до изменения. Если нельзя — сравнить вручную длительность секвенции и количество клипов.

**Step 4: проверка на составной строке**

Временно в `projects/tulips/script/script.csv` подменить одну строку на формат с `||`:

```
...,,"Составная цитата из двух частей.","file1.mp4: 01:00.00 — 01:03.00 || file2.mp4: 02:00.00 — 02:02.00"
```

Прогнать `build_xml.py`. Открыть результирующий XML, найти эту строку. Expected: 2 `clipitem` на V2, `start[2]` равен `end[1]`, общая длительность 5 сек во фреймах.

Откатить:
```bash
git checkout projects/tulips/script/script.csv
```

**Step 5: Commit**

```bash
git add _scripts/build_xml.py
git commit -m "feat(build_xml): парсинг || и рендер клипов впритык на V2"
```

---

### Task B7: E2E проверка на реальном проекте

**Files:** код не меняем.

**Step 1: выбрать проект**

`projects/2026-04-kozha` или любой актуальный с готовым сценарием.

**Step 2: прогнать пайплайн**

```bash
# 0. Preclean интервью (блок A)
python _scripts/cut_pauses.py projects/2026-04-kozha/raw/interviews --profile hero --output projects/2026-04-kozha/cuts/interviews

# 1. Транскрибация чистых версий (если надо)
python _scripts/transcribe.py projects/2026-04-kozha/cuts/interviews --speakers 2 --json --output projects/2026-04-kozha/transcripts

# 2. Поиск таймкодов
python _scripts/match_timecodes.py search projects/2026-04-kozha

# 3. Агентная верификация через /match-timecodes (вручную)

# 4. Snap
python _scripts/match_timecodes.py snap projects/2026-04-kozha

# 5. XML
python _scripts/build_xml.py projects/2026-04-kozha --davinci
```

**Step 3: проверить результат**

- Открыть `.fcpxml` в DaVinci Resolve.
- Убедиться что клипы на V2 (герой) стоят впритык для составных строк.
- Смотреть 2-3 составные строки вручную — совпадают ли части по смыслу с текстом сценария.

**Step 4: если всё ок — отметить в CLAUDE.md**

Обновить раздел `cut_pauses.py` описанием флага `--profile`, раздел `build_xml.py` — упоминанием `||` в таймкодах.

**Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: описать --profile и формат составных таймкодов в CLAUDE.md"
```

---

## Чеклист готовности

- [ ] A1-A5: `cut_pauses.py` с профилем hero протестирован на vendingi.
- [ ] B1: fuzzy whole-match работает на одиночных цитатах tulips.
- [ ] B2: split by sentences + merge adjacent.
- [ ] B3: `cmd_search` выдаёт `parts[]`, регрессия не сломана.
- [ ] B4: skill `/match-timecodes` документирован.
- [ ] B5: `cmd_snap` пишет `||` в CSV для multi-part.
- [ ] B6: `build_xml.py` парсит `||`, клипы впритык.
- [ ] B7: E2E на реальном проекте, FCPXML открывается в DaVinci.

## Риски и примечания

- Файлы после cut_pauses получают суффикс `_clean`, но match_timecodes и build_xml опираются на имена файлов из `raw/`. Проверить: после прогона A транскрипты могут называться `*_clean.transcript.json`, а в CSV-сценарии автор указывает `file.mp4`. Решение: `_resolve_file_key` в `build_xml.py` уже делает fuzzy-резолв по stem — надо убедиться, что оно матчит `file.mp4` с `file_clean.mp4`. Если нет — расширить резолв, либо требовать чтобы в CSV писали `file_clean.mp4`.
- fuzzy whole-match может ложно срабатывать на одинаковых по смыслу кусках из разных интервью. Митигация — высокий порог 0.85. При первых ложных срабатываниях на реальных данных поднять до 0.90.
- Smith-Waterman заменён на LCS в окне для простоты. Если качество упадёт — переписать на честный SW с gap penalty.
