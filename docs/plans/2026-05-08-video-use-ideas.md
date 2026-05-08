# video-use ideas Implementation Plan (этап B)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Имплементировать этап B из дизайна `2026-05-08-video-use-ideas-design.md`:
(1) `match_timecodes.py pack` — phrase-level packed транскрипты;
(2) `match_timecodes.py validate` — детектор word-overlap'ов в `verified.json`
+ within-word boundary checker. Этап A (timeline_view) — отдельный план потом.

**Architecture:** Две новые подкоманды в существующем `_scripts/match_timecodes.py`,
без новых runtime-зависимостей. Тесты на `unittest` из stdlib (в проекте нет
test framework — внедряем минимально). Validator вызывается из `cmd_snap` как
preflight: оверлапы блокируют snap, within-word — только warning.

**Tech Stack:** Python 3 stdlib (json, re, csv, pathlib, unittest). Уже
установлено: WhisperX (для генерации `*.transcript.json`), ffmpeg/ffprobe (для
`cmd_snap`). Никаких новых deps.

**Дизайн-док:** `docs/plans/2026-05-08-video-use-ideas-design.md`

---

## Структура

- Tasks 1–4: pack-формат
- Tasks 5–9: overlap-validator (две проблемы) + JSON output + интеграция в cmd_snap
- Tasks 10–11: E2E проверка + документация

Каждая задача — write test → run fail → implement → run pass → commit.

---

### Task 1: Pack — failing test для phrase grouping

**Files:**
- Create: `tests/__init__.py` (пустой)
- Create: `tests/test_pack.py`

**Step 1: Создать пустой `tests/__init__.py`**

```bash
mkdir -p tests
echo "" > tests/__init__.py
```

**Step 2: Написать failing test**

Создать `tests/test_pack.py`:

```python
"""Тесты pack-формата (этап B1 video-use ideas)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_scripts"))

from match_timecodes import pack_words_into_phrases  # noqa: E402


class TestPackWordsIntoPhrases(unittest.TestCase):
    def test_break_on_silence_threshold(self):
        """Разрыв на паузе >= silence_threshold."""
        words = [
            {"word": "первое", "start": 0.0, "end": 0.5},
            {"word": "слово", "start": 0.55, "end": 1.0},
            # пауза 0.6s >= 0.5s → разрыв
            {"word": "второе", "start": 1.6, "end": 2.0},
            {"word": "предложение", "start": 2.05, "end": 2.6},
        ]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 2)
        self.assertEqual(phrases[0]["text"], "первое слово")
        self.assertEqual(phrases[0]["start"], 0.0)
        self.assertEqual(phrases[0]["end"], 1.0)
        self.assertEqual(phrases[1]["text"], "второе предложение")

    def test_no_break_on_short_pause(self):
        """Пауза < threshold не разрывает."""
        words = [
            {"word": "одна", "start": 0.0, "end": 0.5},
            {"word": "фраза", "start": 0.7, "end": 1.0},  # пауза 0.2s < 0.5s
        ]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 1)
        self.assertEqual(phrases[0]["text"], "одна фраза")

    def test_break_on_speaker_change(self):
        """Смена speaker → разрыв даже без паузы."""
        words = [
            {"word": "первый", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"},
            {"word": "спикер", "start": 0.55, "end": 1.0, "speaker": "SPEAKER_00"},
            {"word": "второй", "start": 1.05, "end": 1.5, "speaker": "SPEAKER_01"},
        ]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 2)
        self.assertEqual(phrases[0]["speaker"], "SPEAKER_00")
        self.assertEqual(phrases[1]["speaker"], "SPEAKER_01")

    def test_no_speaker_field(self):
        """Если в словах нет speaker — поле в выводе None."""
        words = [{"word": "слово", "start": 0.0, "end": 0.5}]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertIsNone(phrases[0].get("speaker"))

    def test_empty_words(self):
        """Пустой вход → пустой выход."""
        self.assertEqual(pack_words_into_phrases([], silence_threshold=0.5), [])


if __name__ == "__main__":
    unittest.main()
```

**Step 3: Run test — должен упасть на импорте**

Run: `python -m unittest tests.test_pack -v`
Expected: ImportError, потому что `pack_words_into_phrases` ещё не существует.

**Step 4: Commit failing test**

```bash
git add tests/__init__.py tests/test_pack.py
git commit -m "test: failing tests для pack_words_into_phrases (B1)"
```

---

### Task 2: Pack — implement `pack_words_into_phrases`

**Files:**
- Modify: `_scripts/match_timecodes.py` — добавить функцию рядом с существующими
  утилитами (после `fmt_tc`, перед `build_text_index`).

**Step 1: Добавить функцию в `match_timecodes.py`**

После функции `fmt_tc` (примерно строка 44) добавить:

```python
# ─── Pack-формат (этап B1: video-use ideas) ────────────────────────────────

def pack_words_into_phrases(words: list[dict], silence_threshold: float = 0.5) -> list[dict]:
    """Группирует word-level entries во фразы.

    Разрыв на:
      - паузе >= silence_threshold между концом предыдущего слова и началом текущего,
      - смене speaker (если поле speaker присутствует).

    Args:
        words: список dict'ов с полями word, start, end и опционально speaker.
        silence_threshold: порог паузы в секундах для разрыва фразы.

    Returns:
        Список фраз: {start, end, text, speaker}. speaker=None если поля нет.
    """
    phrases: list[dict] = []
    cur_words: list[dict] = []
    cur_start: float | None = None
    cur_speaker: str | None = None
    prev_end: float | None = None

    def flush() -> None:
        nonlocal cur_words, cur_start, cur_speaker
        if not cur_words:
            return
        text = " ".join((w.get("word") or "").strip() for w in cur_words if (w.get("word") or "").strip())
        end_t = cur_words[-1].get("end", cur_start or 0.0)
        phrases.append({
            "start": cur_start,
            "end": end_t,
            "text": text,
            "speaker": cur_speaker,
        })
        cur_words = []
        cur_start = None
        cur_speaker = None

    for w in words:
        start = w.get("start")
        if start is None:
            continue
        speaker = w.get("speaker")

        if cur_speaker is not None and speaker is not None and speaker != cur_speaker:
            flush()
        elif prev_end is not None and start - prev_end >= silence_threshold:
            flush()

        if cur_start is None:
            cur_start = start
            cur_speaker = speaker
        cur_words.append(w)
        prev_end = w.get("end", start)

    flush()
    return phrases
```

**Step 2: Run test — должен пройти**

Run: `python -m unittest tests.test_pack -v`
Expected: 5 tests OK.

**Step 3: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): pack_words_into_phrases (B1)"
```

---

### Task 3: Pack — CLI команда + рендер markdown

**Files:**
- Modify: `_scripts/match_timecodes.py` — новая функция `cmd_pack` + регистрация
  подкоманды в `main()`.

**Step 1: Добавить failing test для рендера**

В `tests/test_pack.py` добавить второй test class:

```python
class TestRenderPackedMarkdown(unittest.TestCase):
    def test_format_with_speaker(self):
        from match_timecodes import render_packed_markdown
        phrases = [
            {"start": 1.5, "end": 3.7, "text": "пример фразы", "speaker": "SPEAKER_00"},
        ]
        md = render_packed_markdown(phrases)
        self.assertIn("[00:01.50-00:03.70] S00 пример фразы", md)

    def test_format_without_speaker(self):
        from match_timecodes import render_packed_markdown
        phrases = [
            {"start": 0.0, "end": 1.0, "text": "без спикера", "speaker": None},
        ]
        md = render_packed_markdown(phrases)
        self.assertIn("[00:00.00-00:01.00] без спикера", md)
        self.assertNotIn(" S", md.replace(":", ""))  # никаких speaker-тегов
```

**Step 2: Run test — должен упасть**

Run: `python -m unittest tests.test_pack -v`
Expected: ImportError для `render_packed_markdown`.

**Step 3: Implement `render_packed_markdown` и `cmd_pack`**

В `_scripts/match_timecodes.py` после `pack_words_into_phrases` добавить:

```python
def render_packed_markdown(phrases: list[dict]) -> str:
    """Рендерит фразы в markdown-строки `[MM:SS.ss-MM:SS.ss] [Sxx] текст`."""
    lines: list[str] = []
    for p in phrases:
        spk = p.get("speaker")
        if spk:
            spk_short = str(spk).replace("SPEAKER_", "S")
            tag = f" {spk_short}"
        else:
            tag = ""
        lines.append(f"[{fmt_tc(p['start'])}-{fmt_tc(p['end'])}]{tag} {p['text']}")
    return "\n".join(lines)
```

И новая команда (после `cmd_compact`, примерно строка 972):

```python
def cmd_pack(project_dir: Path, silence_threshold: float = 0.5) -> None:
    """Создаёт packed.md / *.packed.txt — фразовое представление транскриптов."""
    print(f"=== Pack транскриптов: {project_dir.name} ===\n")

    tr_dir = project_dir / "transcripts"
    if not tr_dir.exists():
        print(f"Ошибка: не найдена папка {tr_dir}", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(tr_dir.glob("*.transcript.json"))
    if not json_files:
        print(f"Ошибка: нет *.transcript.json в {tr_dir}", file=sys.stderr)
        sys.exit(1)

    all_blocks: list[str] = []
    for jp in json_files:
        with open(jp, "r", encoding="utf-8") as f:
            data = json.load(f)
        words = []
        for seg in data.get("segments", []):
            words.extend(seg.get("words", []))
        phrases = pack_words_into_phrases(words, silence_threshold=silence_threshold)
        md = render_packed_markdown(phrases)

        per_file_path = tr_dir / jp.name.replace(".transcript.json", ".packed.txt")
        with open(per_file_path, "w", encoding="utf-8") as f:
            f.write(md + "\n")

        header = f"## {jp.name.replace('.transcript.json', '')}  ({len(phrases)} фраз)"
        all_blocks.append(header + "\n\n" + md + "\n")
        print(f"  {per_file_path.name}: {len(phrases)} фраз")

    index_path = tr_dir / "packed.md"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(f"# Packed транскрипты\n\n")
        f.write(f"Фразы, разрыв на тишине ≥ {silence_threshold:.1f}s или смене спикера.\n\n")
        f.write("\n".join(all_blocks))
    print(f"\nИндекс: {index_path}")
```

В `main()` добавить регистрацию подкоманды (рядом с `p_compact`):

```python
    p_pack = subparsers.add_parser("pack", help="B1: pack-формат транскриптов (фразы + [start-end])")
    p_pack.add_argument("project_dir", type=Path, help="Путь к папке проекта")
    p_pack.add_argument("--silence-threshold", type=float, default=0.5,
                        help="Порог паузы для разрыва фразы (default: 0.5s)")
```

И в диспетчер команд:

```python
    elif args.command == "pack":
        cmd_pack(project_dir, silence_threshold=args.silence_threshold)
```

**Step 4: Run test — должен пройти**

Run: `python -m unittest tests.test_pack -v`
Expected: 7 tests OK (5 старых + 2 новых).

**Step 5: Smoke-test на реальном проекте**

Run: `python _scripts/match_timecodes.py pack projects/2026-03-thermobags`
Expected: создаются `transcripts/*.packed.txt` и `transcripts/packed.md`.
Глазами проверить, что фразы выглядят разумно (не по одному слову на строку,
не одной гигантской фразой на весь файл).

**Step 6: Commit**

```bash
git add _scripts/match_timecodes.py tests/test_pack.py
git commit -m "feat(match_timecodes): команда pack — фразовое представление (B1)"
```

---

### Task 4: Validate — failing test для overlap detection

**Files:**
- Create: `tests/test_validate.py`

**Step 1: Написать failing test**

```python
"""Тесты overlap-validator (этап B2 video-use ideas)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_scripts"))

from match_timecodes import detect_overlaps  # noqa: E402


class TestDetectOverlaps(unittest.TestCase):
    def test_overlap_in_same_file(self):
        """Два парта в одной строке с одним file и пересечением — конфликт."""
        rows = [{
            "row_idx": 51,
            "chosen_parts": [
                {"file": "a.mov", "start": 100.0, "end": 110.0},
                {"file": "a.mov", "start": 109.0, "end": 115.0},
            ],
        }]
        overlaps = detect_overlaps(rows, min_overlap_ms=50)
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0]["row_idx"], 51)
        self.assertEqual(overlaps[0]["file"], "a.mov")
        self.assertAlmostEqual(overlaps[0]["intersection_s"], 1.0, places=2)

    def test_no_overlap_different_files(self):
        """Парты в разных файлах не оверлапятся, даже если по времени совпадают."""
        rows = [{
            "row_idx": 1,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 5.0},
                {"file": "b.mov", "start": 0.0, "end": 5.0},
            ],
        }]
        self.assertEqual(detect_overlaps(rows, min_overlap_ms=50), [])

    def test_below_min_overlap_threshold(self):
        """Оверлап < min_overlap_ms — игнорим (артефакт Whisper)."""
        rows = [{
            "row_idx": 2,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 5.020},
                {"file": "a.mov", "start": 5.000, "end": 10.0},  # 20ms оверлап
            ],
        }]
        self.assertEqual(detect_overlaps(rows, min_overlap_ms=50), [])

    def test_three_overlapping_parts(self):
        """N>2 пересекающихся партов — все пары репортятся."""
        rows = [{
            "row_idx": 80,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 2.0},
                {"file": "a.mov", "start": 1.0, "end": 3.0},
                {"file": "a.mov", "start": 2.5, "end": 4.0},
            ],
        }]
        overlaps = detect_overlaps(rows, min_overlap_ms=50)
        # пары (0,1), (1,2) — пересекаются; (0,2) — нет (2.0 vs 2.5)
        self.assertEqual(len(overlaps), 2)

    def test_clean_data(self):
        """Корректные данные — пустой список."""
        rows = [{
            "row_idx": 1,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 5.0},
                {"file": "a.mov", "start": 6.0, "end": 10.0},
            ],
        }]
        self.assertEqual(detect_overlaps(rows, min_overlap_ms=50), [])


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test — должен упасть**

Run: `python -m unittest tests.test_validate -v`
Expected: ImportError для `detect_overlaps`.

**Step 3: Commit failing test**

```bash
git add tests/test_validate.py
git commit -m "test: failing tests для detect_overlaps (B2)"
```

---

### Task 5: Validate — implement `detect_overlaps`

**Files:**
- Modify: `_scripts/match_timecodes.py` — добавить функцию рядом с другими
  validation-утилитами (после `_dedupe_split_overlaps`, около строки ~385).

**Step 1: Добавить функцию**

После `_dedupe_split_overlaps` (конец секции split-mode) добавить:

```python
# ─── Validation (этап B2: video-use ideas) ─────────────────────────────────

def detect_overlaps(rows: list[dict], min_overlap_ms: int = 50) -> list[dict]:
    """Детектирует word-overlap'ы внутри одной строки verified.json.

    Для каждой пары партов (i, j) с одинаковым file: если
    [start_i, end_i] пересекается с [start_j, end_j] более чем на
    min_overlap_ms — это конфликт (агент-верификатор выбрал перекрывающиеся
    диапазоны, на таймлайне даст повтор аудио).

    Args:
        rows: список строк verified.json. Каждая row: {row_idx, chosen_parts}.
        min_overlap_ms: порог минимального оверлапа (артефакты Whisper).

    Returns:
        Список конфликтов: {row_idx, file, part_a, part_b, intersection_s}.
    """
    min_overlap_s = min_overlap_ms / 1000.0
    out: list[dict] = []
    for row in rows:
        parts = row.get("chosen_parts") or []
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                a, b = parts[i], parts[j]
                if a.get("file") != b.get("file"):
                    continue
                lo = max(a["start"], b["start"])
                hi = min(a["end"], b["end"])
                inter = hi - lo
                if inter > min_overlap_s:
                    out.append({
                        "row_idx": row["row_idx"],
                        "file": a.get("file"),
                        "part_a": i,
                        "part_b": j,
                        "intersection_s": round(inter, 3),
                    })
    return out
```

**Step 2: Run test — должен пройти**

Run: `python -m unittest tests.test_validate -v`
Expected: 5 tests OK.

**Step 3: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): detect_overlaps (B2)"
```

---

### Task 6: Validate — failing test для within-word boundary

**Files:**
- Modify: `tests/test_validate.py` — добавить второй test class.

**Step 1: Добавить failing test**

В `tests/test_validate.py` добавить:

```python
class TestDetectWithinWord(unittest.TestCase):
    def _words(self):
        # Транскрипт: 3 слова с известными границами
        return [
            {"word": "первое", "start": 0.0, "end": 0.5},
            {"word": "второе", "start": 0.7, "end": 1.2},
            {"word": "третье", "start": 1.5, "end": 2.0},
        ]

    def test_part_end_inside_word(self):
        """end парта попадает в середину слова → конфликт."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 22,
            "chosen_parts": [{"file": "a.mov", "start": 0.0, "end": 0.9}],
        }]
        transcripts = {"a.mov": self._words()}
        flags = detect_within_word(rows, transcripts, word_tol_ms=50)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["edge"], "end")
        self.assertEqual(flags[0]["word"], "второе")

    def test_part_start_on_boundary(self):
        """start парта на границе слова (в пределах допуска) → ок."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 1,
            "chosen_parts": [{"file": "a.mov", "start": 0.03, "end": 0.5}],
        }]  # 30ms от 0.0 — внутри ±50ms допуска
        transcripts = {"a.mov": self._words()}
        self.assertEqual(detect_within_word(rows, transcripts, word_tol_ms=50), [])

    def test_part_in_silence(self):
        """Граница парта в паузе между словами → ок."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 1,
            "chosen_parts": [{"file": "a.mov", "start": 0.6, "end": 1.35}],
        }]  # обе границы в паузах
        transcripts = {"a.mov": self._words()}
        self.assertEqual(detect_within_word(rows, transcripts, word_tol_ms=50), [])

    def test_missing_transcript(self):
        """Нет транскрипта для file → пропускаем (не падаем)."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 1,
            "chosen_parts": [{"file": "missing.mov", "start": 0.0, "end": 5.0}],
        }]
        self.assertEqual(detect_within_word(rows, {}, word_tol_ms=50), [])
```

**Step 2: Run test — должен упасть**

Run: `python -m unittest tests.test_validate -v`
Expected: 4 новых теста — ImportError для `detect_within_word`.

**Step 3: Commit failing test**

```bash
git add tests/test_validate.py
git commit -m "test: failing tests для detect_within_word (B2)"
```

---

### Task 7: Validate — implement `detect_within_word`

**Files:**
- Modify: `_scripts/match_timecodes.py` — добавить после `detect_overlaps`.

**Step 1: Добавить функцию**

```python
def detect_within_word(rows: list[dict], transcripts: dict[str, list[dict]],
                       word_tol_ms: int = 50) -> list[dict]:
    """Детектирует попадание границы парта внутрь слова.

    Для каждого парта проверяет start и end: если значение лежит между
    word.start и word.end какого-то слова, и не близко к word.start или
    word.end в пределах word_tol_ms — это конфликт.

    Args:
        rows: строки verified.json (как в detect_overlaps).
        transcripts: dict[file_name, list[word_dict]] — слова из *.transcript.json.
        word_tol_ms: допуск «граница попала на word boundary».

    Returns:
        Список флагов: {row_idx, part_idx, edge, word, word_start, word_end, part_value}.
    """
    tol_s = word_tol_ms / 1000.0
    out: list[dict] = []

    for row in rows:
        parts = row.get("chosen_parts") or []
        for pidx, p in enumerate(parts):
            words = transcripts.get(p.get("file"))
            if not words:
                continue
            for edge in ("start", "end"):
                t = p.get(edge)
                if t is None:
                    continue
                for w in words:
                    ws, we = w.get("start"), w.get("end")
                    if ws is None or we is None:
                        continue
                    if not (ws < t < we):
                        continue
                    # внутри слова — проверяем близость к границам
                    if (t - ws) <= tol_s or (we - t) <= tol_s:
                        break  # достаточно близко, не флагаем
                    out.append({
                        "row_idx": row["row_idx"],
                        "part_idx": pidx,
                        "edge": edge,
                        "word": w.get("word"),
                        "word_start": ws,
                        "word_end": we,
                        "part_value": t,
                    })
                    break  # одно совпадение слова — выходим
    return out
```

**Step 2: Run test — должен пройти**

Run: `python -m unittest tests.test_validate -v`
Expected: 9 tests OK (5 + 4).

**Step 3: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): detect_within_word (B2)"
```

---

### Task 8: Validate — CLI команда + JSON отчёт

**Files:**
- Modify: `_scripts/match_timecodes.py` — добавить `cmd_validate` + регистрация
  подкоманды.

**Step 1: Добавить failing test для CLI orchestration**

В `tests/test_validate.py` добавить:

```python
class TestValidateOrchestration(unittest.TestCase):
    def test_load_transcripts_for_validation(self):
        """Хелпер _load_transcripts_for_validation: читает *.transcript.json
        и возвращает dict[file_basename, list[word]]."""
        from match_timecodes import _load_transcripts_for_validation
        # Используем реальный проект, если есть
        proj = Path(__file__).resolve().parent.parent / "projects" / "2026-03-thermobags"
        if not proj.exists():
            self.skipTest("нет projects/2026-03-thermobags для теста")
        transcripts = _load_transcripts_for_validation(proj)
        self.assertIsInstance(transcripts, dict)
        # Хотя бы один файл с непустым списком слов
        self.assertTrue(any(len(v) > 0 for v in transcripts.values()))
```

**Step 2: Run test — должен упасть**

Run: `python -m unittest tests.test_validate -v`
Expected: ImportError для `_load_transcripts_for_validation`.

**Step 3: Implement helper + cmd_validate**

В `_scripts/match_timecodes.py` после `detect_within_word`:

```python
def _load_transcripts_for_validation(project_dir: Path) -> dict[str, list[dict]]:
    """Грузит все *.transcript.json и возвращает dict[file_basename, words].

    Ключ — имя видеофайла как оно записано в verified.json (с расширением
    .mov/.mp4/...). Транскрипт файла "X.transcript.json" соответствует
    источнику "X.<ext>" — для матчинга используем stem без `.transcript`.
    """
    tr_dir = project_dir / "transcripts"
    out: dict[str, list[dict]] = {}
    if not tr_dir.exists():
        return out
    for jp in tr_dir.glob("*.transcript.json"):
        with open(jp, "r", encoding="utf-8") as f:
            data = json.load(f)
        words = []
        for seg in data.get("segments", []):
            words.extend(seg.get("words", []))
        # Маппим на оригинальные имена видеофайлов (с расширением).
        # verified.json содержит file как "X.mov" — ищем все возможные ext.
        stem = jp.name.replace(".transcript.json", "")
        for ext in (".mov", ".mp4", ".mkv", ".avi", ".MOV", ".MP4"):
            candidate = project_dir / "raw" / "voiceover" / f"{stem}{ext}"
            if not candidate.exists():
                candidate = project_dir / "raw" / "interviews" / f"{stem}{ext}"
            if candidate.exists():
                out[f"{stem}{ext}"] = words
                break
        else:
            # Фолбэк — кладём по голому stem (validate всё равно отработает,
            # если verified.json по какой-то причине без расширения).
            out[stem] = words
    return out


def cmd_validate(project_dir: Path, word_tol_ms: int = 50,
                 min_overlap_ms: int = 50) -> int:
    """B2: validate verified.json — детектит overlap'ы и within-word boundary.

    Returns: 0 если чисто, 1 если есть оверлапы (within-word — только warning).
    """
    print(f"=== Validate verified.json: {project_dir.name} ===\n")

    verified_path = project_dir / "script" / "verified.json"
    if not verified_path.exists():
        print(f"Ошибка: не найден {verified_path}", file=sys.stderr)
        return 1

    with open(verified_path, "r", encoding="utf-8") as f:
        verified = json.load(f)

    # Нормализуем строки: подмешиваем chosen_parts в формате detect_overlaps.
    rows = []
    for row in verified["rows"]:
        chosen = _get_chosen_parts(row)
        rows.append({
            "row_idx": row["row_idx"],
            "chosen_parts": chosen,
        })

    overlaps = detect_overlaps(rows, min_overlap_ms=min_overlap_ms)
    transcripts = _load_transcripts_for_validation(project_dir)
    within = detect_within_word(rows, transcripts, word_tol_ms=word_tol_ms)

    if overlaps:
        print(f"❌ Word-overlap'ы внутри строк ({len(overlaps)}):")
        for o in overlaps:
            print(f"  row {o['row_idx']:>3} {o['file']}: парты {o['part_a']}+{o['part_b']} "
                  f"пересекаются на {o['intersection_s']}s")
    else:
        print("✓ Оверлапов word-границ не найдено")

    if within:
        print(f"\n⚠ Within-word границы ({len(within)}):")
        for w in within:
            print(f"  row {w['row_idx']:>3} part {w['part_idx']} {w['edge']}={w['part_value']:.3f}s "
                  f"внутри слова '{w['word']}' ({w['word_start']:.3f}-{w['word_end']:.3f})")
    else:
        print("✓ Все границы партов на word boundary")

    report = {
        "overlaps": overlaps,
        "within_word": within,
        "thresholds": {"word_tol_ms": word_tol_ms, "min_overlap_ms": min_overlap_ms},
    }
    report_path = project_dir / "script" / "validation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nОтчёт: {report_path}")

    return 1 if overlaps else 0
```

В `main()` зарегистрировать команду:

```python
    p_validate = subparsers.add_parser("validate", help="B2: проверка verified.json на оверлапы и within-word")
    p_validate.add_argument("project_dir", type=Path, help="Путь к папке проекта")
    p_validate.add_argument("--word-tol-ms", type=int, default=50,
                            help="Допуск 'граница на word boundary' в мс (default: 50)")
    p_validate.add_argument("--min-overlap-ms", type=int, default=50,
                            help="Порог минимального оверлапа в мс (default: 50)")
```

И в диспетчер:

```python
    elif args.command == "validate":
        sys.exit(cmd_validate(project_dir, word_tol_ms=args.word_tol_ms,
                              min_overlap_ms=args.min_overlap_ms))
```

**Step 4: Run test — должен пройти**

Run: `python -m unittest tests.test_validate -v`
Expected: 10 tests OK (или skip — если в окружении нет thermobags-проекта).

**Step 5: Commit**

```bash
git add _scripts/match_timecodes.py tests/test_validate.py
git commit -m "feat(match_timecodes): команда validate + JSON-отчёт (B2)"
```

---

### Task 9: Wire validate в `cmd_snap` как preflight

**Files:**
- Modify: `_scripts/match_timecodes.py` — в начале `cmd_snap` (около строки
  828) вызвать validate и блокироваться на оверлапах.

**Step 1: Добавить preflight-блок в `cmd_snap`**

В `cmd_snap`, сразу после загрузки `verified.json` (после строки `verified = json.load(f)`),
вставить:

```python
    # Preflight (B2): не snap-нем, если в verified.json уже есть word-overlap'ы.
    # Иначе snap запишет в CSV сломанные строки, которые потом дадут повтор
    # аудио на таймлайне.
    rows_for_check = [{
        "row_idx": r["row_idx"],
        "chosen_parts": _get_chosen_parts(r),
    } for r in verified["rows"]]
    overlaps = detect_overlaps(rows_for_check, min_overlap_ms=50)
    if overlaps:
        print("❌ Snap отменён: в verified.json есть word-overlap'ы.")
        print("   Запусти: python _scripts/match_timecodes.py validate <project>")
        for o in overlaps:
            print(f"   row {o['row_idx']} {o['file']}: парты {o['part_a']}+{o['part_b']} "
                  f"пересечение {o['intersection_s']}s")
        sys.exit(1)
```

**Step 2: Smoke-test на чистом проекте**

Run: `python _scripts/match_timecodes.py snap projects/<любой-чистый-проект>`
Expected: snap проходит как раньше, никаких блоков.

**Step 3: Smoke-test на проекте с известными оверлапами**

Run: `python _scripts/match_timecodes.py snap projects/2026-03-thermobags`
Expected: блок с сообщением про строки 51, 81, 90 (или близкие — после
`_dedupe_split_overlaps` могут быть другие).

Если блок НЕ срабатывает на термосумках — значит `_dedupe_split_overlaps`
уже починил все оверлапы из split-mode. Это валидный результат: validator всё
равно нужен как safety net на будущее. Зафиксировать факт в комментарии к
коммиту.

**Step 4: Commit**

```bash
git add _scripts/match_timecodes.py
git commit -m "feat(match_timecodes): preflight-validate в cmd_snap (B2)"
```

---

### Task 10: E2E проверка на живом проекте

**Files:** только запуск, без изменений кода.

**Step 1: Validate на термосумках**

Run: `python _scripts/match_timecodes.py validate projects/2026-03-thermobags`
Expected: команда отрабатывает, пишет `script/validation_report.json`.

Проверить отчёт:
- если `overlaps` непустой — фикс работает, поймали ровно те кейсы из памяти
  (или их подмножество, если что-то уже починилось `_dedupe_split_overlaps`),
- если `overlaps` пустой и `within_word` тоже пустой — текущий код уже всё
  починил, validator просто формально подтверждает,
- если `within_word` непустой — это ценная новая находка, выписать в стдаут
  или в комментарий, обсудить отдельно.

**Step 2: Pack на термосумках**

Run: `python _scripts/match_timecodes.py pack projects/2026-03-thermobags`
Expected: `transcripts/packed.md` создан, фразы выглядят разумно.

Глазами проверить файл `transcripts/packed.md`: каждая фраза — несколько
слов, не одно слово на строку и не одной мегафразой на весь транскрипт. Если
выглядит разбито странно — поиграться с `--silence-threshold` (попробовать
0.4 и 0.6) и принять решение по дефолту.

**Step 3: Зафиксировать наблюдения**

Если результаты на термосумках отличаются от ожиданий — добавить заметку
в commit-сообщение или новую memory-запись (через основную сессию) с
конкретными числами.

**Step 4: Commit (если есть изменения, например, тюнинг порога)**

Если ничего не меняли — пропускаем коммит.

---

### Task 11: Обновить CLAUDE.md

**Files:**
- Modify: `C:\Users\Alex\Videos\factory\CLAUDE.md` — добавить две команды в
  секцию `match_timecodes.py`.

**Step 1: Добавить документацию команд**

В CLAUDE.md в блоке про `match_timecodes.py` (после строк про search/snap/compact)
добавить:

````markdown
```bash
python _scripts/match_timecodes.py pack <project_dir>     # B1: фразовый pack транскриптов
python _scripts/match_timecodes.py validate <project_dir> # B2: проверка verified.json на overlap'ы
```

`pack` создаёт `transcripts/{file}.packed.txt` (фразы с `[MM:SS.ss-MM:SS.ss]` и
опционально speaker-тегом) и общий `transcripts/packed.md`. Разрыв фразы — на
паузе ≥ 0.5s или смене speaker.

`validate` детектирует две проблемы в `verified.json`: (1) word-overlap внутри
одной строки (несколько партов с пересекающимися диапазонами) и (2) границы
партов внутри слов (а не на word boundary). Отчёт пишется в
`script/validation_report.json`. Exit code 1 если есть оверлапы.

`cmd_snap` теперь вызывает validate как preflight: при наличии оверлапов snap
блокируется (иначе запишет сломанный CSV).
````

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: pack + validate команды match_timecodes в CLAUDE.md"
```

---

## Done criteria

- 14+ unit-тестов (5 pack + 5 overlap + 4 within-word + ≥1 orchestration), все
  зелёные через `python -m unittest discover tests`.
- `match_timecodes.py pack <project>` создаёт `transcripts/packed.md`.
- `match_timecodes.py validate <project>` создаёт `validation_report.json`,
  exit 1 при оверлапах.
- `cmd_snap` блокируется на оверлапах с человекочитаемым сообщением.
- E2E на `projects/2026-03-thermobags` подтверждает или опровергает наличие
  открытой задачи `project_verified_json_overlap_fix.md` — в обоих случаях
  результат фиксируем в коммите/памяти.
- CLAUDE.md описывает обе новые команды.
- Зависимости проекта не растут.

## Не покрыто этим планом

- Этап A (timeline_view) — отдельный дизайн-док и план, **только** если после
  E2E на термосумках стало ясно, что `within_word` warning'и многочисленны
  и нечинимы переверификацией.
- Удаление `cut_pauses.py` — это отдельный refactor (нужно проверить, что в
  активных проектах он не используется + почистить упоминания в CLAUDE.md и
  скиллах). Не входит в скоуп этого плана.
- Замена WhisperX на ElevenLabs Scribe — отдельный разговор.
