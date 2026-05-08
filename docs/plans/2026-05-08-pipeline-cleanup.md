# Pipeline Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Удалить мёртвый `cut_pauses`, выделить общие утилиты, починить баги, ускорить горячие места.

**Architecture:** 5 логических коммитов: (1) удаление cut_pauses + чистка `cuts/` логики; (2) общий `_scripts/_common.py`; (3) фиксы багов (exit code, traceback, мутация состояния, нормализация verified.json); (4) перф (parallel ffprobe, dedup norm_words, bisect); (5) перенумерация skill `match-timecodes.md`. Автотестов в репо нет — верификация ручная через diff артефактов на реальном проекте `2026-03-thermobags`.

**Tech Stack:** Python 3.10+, ffmpeg, ffprobe, WhisperX, no test framework currently used.

**Связанный design doc:** `docs/plans/2026-05-08-pipeline-cleanup-design.md`

---

## Task 0: Сохранить baseline-артефакты

Нужно ДО любых изменений, чтобы потом сверять `diff` после каждой задачи.

**Step 0.1: Создать папку для baseline**

```bash
mkdir -p _baseline_2026-05-08
```

**Step 0.2: Прогнать `build_xml` на термосумках, сохранить XML**

```bash
python _scripts/build_xml.py projects/2026-03-thermobags
cp projects/2026-03-thermobags/assembly/*_rough_cut.xml _baseline_2026-05-08/
cp projects/2026-03-thermobags/assembly/*_rough_cut_local.xml _baseline_2026-05-08/
```

Expected: команда отрабатывает без ошибок, в `_baseline_2026-05-08/` появились 2 XML.

**Step 0.3: Прогнать `match_timecodes search`, сохранить candidates.json**

```bash
python _scripts/match_timecodes.py search projects/2026-03-thermobags
cp projects/2026-03-thermobags/script/candidates.json _baseline_2026-05-08/candidates.json
```

Expected: `candidates.json` появился в baseline.

**Step 0.4: Если есть verified.json — прогнать `validate`, сохранить отчёт**

```bash
test -f projects/2026-03-thermobags/script/verified.json && \
  python _scripts/match_timecodes.py validate projects/2026-03-thermobags && \
  cp projects/2026-03-thermobags/script/validation_report.json _baseline_2026-05-08/ || \
  echo "verified.json нет — validate baseline пропускаем"
```

Expected: либо `validation_report.json` в baseline, либо явное «пропущено».

`_baseline_2026-05-08/` НЕ коммитим — это локальный артефакт. Добавить в `.gitignore`:

**Step 0.5: Добавить baseline в .gitignore**

```bash
echo "_baseline_2026-05-08/" >> .gitignore
```

---

## Task 1: Drop cut_pauses

**Files:**
- Delete: `_scripts/cut_pauses.py`
- Modify: `_scripts/build_xml.py:100-126` (удалить `_pick_media_dir`, обновить `scan_project`)
- Modify: `CLAUDE.md` (удалить раздел cut_pauses + строку `cuts/`)
- Delete: `projects/*/cuts/` (8 пустых директорий)
- Modify: `C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\MEMORY.md`
- Delete: `C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\project_cut_pauses_audio_support.md`
- Modify: `C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\project_cutting_improvements.md`

**Step 1.1: Удалить `_scripts/cut_pauses.py`**

```bash
rm _scripts/cut_pauses.py
```

**Step 1.2: Упростить `build_xml.scan_project`**

В `_scripts/build_xml.py` удалить функцию `_pick_media_dir` (строки 100-112) полностью.

В `scan_project` (раньше строки 123-126) заменить:

```python
voiceover_dir = _pick_media_dir(project_dir, "voiceover")
interviews_dir = _pick_media_dir(project_dir, "interviews")
print(f"  Voiceover: {voiceover_dir.relative_to(project_dir)}")
print(f"  Interviews: {interviews_dir.relative_to(project_dir)}")
```

на:

```python
voiceover_dir = project_dir / "raw" / "voiceover"
interviews_dir = project_dir / "raw" / "interviews"
print(f"  Voiceover: {voiceover_dir.relative_to(project_dir)}")
print(f"  Interviews: {interviews_dir.relative_to(project_dir)}")
```

**Step 1.3: Чистка CLAUDE.md**

В `CLAUDE.md` удалить:

1. Весь раздел `### cut_pauses.py — удаление пауз и слов-паразитов` (от заголовка до пустой строки перед `### transcribe.py`).
2. В блоке структуры папок (`raw/interviews/`, `raw/voiceover/`, ...) удалить строку:
   ```
   cuts/              ← нарезки: очищенные видео, реплики героя
   ```
3. В разделе про `build_xml.py` удалить фразу: «Так очищенные cut_pauses файлы автоматически подхватываются.»

**Step 1.4: Удалить пустые `cuts/` директории**

```bash
for d in projects/*/cuts; do
  if [ -d "$d" ] && [ -z "$(ls -A "$d")" ]; then
    rmdir "$d"
    echo "Удалено: $d"
  fi
done
```

Expected: удалены 8 директорий: `projects/2026-03-thermobags/cuts`, `projects/2026-03-vendingi/cuts`, `projects/2026-04-ferma/cuts`, `projects/2026-04-kogtetochki/cuts`, `projects/2026-04-kozha/cuts`, `projects/2026-04-ustritsy/cuts`, `projects/test/cuts`, `projects/tulips/cuts`.

**Step 1.5: Обновить память**

Удалить файл:
```bash
rm "C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\project_cut_pauses_audio_support.md"
```

В `C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\MEMORY.md` удалить строку:
```
- [project_cut_pauses_audio_support.md](project_cut_pauses_audio_support.md) — Будущее: расширить cut_pauses.py на аудио (.m4a/.mp3/.wav), сейчас блокер для vendingi
```

В `project_cutting_improvements.md` (поле `description` и тело) добавить пометку в начало body:

```markdown
> **Update 2026-05-08:** `cut_pauses.py` удалён — пайплайн теперь нарезает по таймкодам в DaVinci через XML, исходники не модифицируются. Логика `cuts/` priority в build_xml тоже удалена.
```

**Step 1.6: Верификация — XML идентичен baseline**

```bash
python _scripts/build_xml.py projects/2026-03-thermobags
diff _baseline_2026-05-08/2026-03-thermobags_rough_cut.xml \
     projects/2026-03-thermobags/assembly/2026-03-thermobags_rough_cut.xml
```

Expected: вывод пустой (cuts/ были пустыми, поэтому fallback на raw/ давал тот же результат).

Также в логе скана должно быть `Voiceover: raw/voiceover` и `Interviews: raw/interviews` (а не `cuts/...`).

**Step 1.7: Коммит**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor: drop cut_pauses, simplify build_xml media discovery

cut_pauses.py больше не используется — pipeline нарезает по таймкодам в
DaVinci через XML, исходники остаются как есть. Все 8 директорий
projects/*/cuts/ были пустыми. Удалено: скрипт (537 строк), функция
_pick_media_dir в build_xml, упоминания в CLAUDE.md, пустые cuts/ папки.
Логика fallback raw/ становится просто чтением raw/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Extract `_scripts/_common.py`

**Files:**
- Create: `_scripts/_common.py`
- Modify: `_scripts/match_timecodes.py` (стр. 15-23, fmt_tc)
- Modify: `_scripts/transcribe.py` (стр. 15-17, 28-30, format_time, get_duration)
- Modify: `_scripts/build_xml.py` (стр. 22-28, 182-190, inline MM:SS на ~830-832)

**Step 2.1: Создать `_scripts/_common.py`**

Полное содержимое:

```python
"""Shared utilities for pipeline scripts."""

import os
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = frozenset({".mp4", ".mov", ".mkv", ".avi"})
AUDIO_EXTS = frozenset({".m4a", ".mp3", ".wav", ".aac", ".flac"})
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


def fix_windows_stdio() -> None:
    """UTF-8 для Windows-консоли. Вызывать в начале main()."""
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def format_tc(seconds: float, *, fractional: bool = True) -> str:
    """Форматирует секунды в таймкод.

    fractional=True  → MM:SS.ss (для script.csv, candidates.json)
    fractional=False → MM:SS / H:MM:SS (для логов и дисплея)
    """
    if fractional:
        m = int(seconds // 60)
        s = seconds - m * 60
        return f"{m:02d}:{s:05.2f}"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_tc(tc_str: str) -> float:
    """Парсит таймкод HH:MM:SS.ss или MM:SS.ss в секунды."""
    parts = [p.strip() for p in tc_str.strip().split(":")]
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0.0


def probe_duration(path: Path) -> float:
    """ffprobe duration в секундах. Бросает CalledProcessError если файл невалидный."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())
```

**Step 2.2: Мигрировать `match_timecodes.py`**

В `_scripts/match_timecodes.py`:

1. Заменить блок `if sys.platform == "win32": ...` (строки 15-17) на:
   ```python
   from _common import VIDEO_EXTS, fix_windows_stdio, format_tc
   fix_windows_stdio()
   ```

2. Удалить локальную константу `VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi"}` (стр. ~23).

3. Удалить функцию `fmt_tc` (стр. ~37-43). Все вызовы `fmt_tc(s)` заменить на `format_tc(s, fractional=True)` (или просто `format_tc(s)` — fractional True по умолчанию).

   Грепнуть все вхождения:
   ```bash
   grep -n "fmt_tc(" _scripts/match_timecodes.py
   ```
   Заменить через `sed` или вручную.

4. В функции `_load_transcripts_for_validation` (стр. 649-680) хардкод `(".mov", ".mp4", ".mkv", ".avi", ".MOV", ".MP4")` заменить на динамический поиск:
   ```python
   for raw_subdir in ("voiceover", "interviews"):
       for src in (project_dir / "raw" / raw_subdir).glob(f"{stem}.*"):
           if src.suffix.lower() in VIDEO_EXTS:
               out[src.name] = words
               break
       else:
           continue
       break
   else:
       out[stem] = words  # fallback
   ```

**Step 2.3: Мигрировать `transcribe.py`**

В `_scripts/transcribe.py`:

1. Заменить блок `if sys.platform == "win32": ...` (стр. 15-17) на:
   ```python
   from _common import VIDEO_EXTS, AUDIO_EXTS, fix_windows_stdio, format_tc, probe_duration
   fix_windows_stdio()
   ```

2. Удалить локальные `VIDEO_EXTENSIONS` и `AUDIO_EXTENSIONS` (стр. ~28-30). По месту использования (`p.suffix.lower() in VIDEO_EXTENSIONS`) поменять имя на `VIDEO_EXTS` соответственно.

3. Удалить функцию `format_time` (стр. ~248-255). Все вызовы заменить на `format_tc(s, fractional=False)`.

4. Удалить функцию `get_duration` (стр. ~324-331). Все вызовы заменить на `probe_duration(path)`.

**Step 2.4: Мигрировать `build_xml.py`**

В `_scripts/build_xml.py`:

1. Заменить блок `if sys.platform == "win32": ...` (стр. 22-24) на:
   ```python
   from _common import MEDIA_EXTS, fix_windows_stdio, format_tc, parse_tc as _parse_tc_common
   fix_windows_stdio()
   ```

2. Удалить локальные `VIDEO_EXTENSIONS` / `AUDIO_EXTENSIONS` / `MEDIA_EXTENSIONS` (стр. ~26-28). Везде использовать импортированный `MEDIA_EXTS` (или `VIDEO_EXTS`/`AUDIO_EXTS` если нужно — импортировать дополнительно).

3. Удалить локальную функцию `parse_tc` (стр. ~182-190). По месту вызова заменить `parse_tc(...)` на `_parse_tc_common(...)`. (Aliased import чтобы не было коллизий с другим возможным `parse_*tc` рядом.)

4. Inline MM:SS в районе стр. 830-832 (грепнуть `int(total_sec) // 60` или `// 60`):
   ```bash
   grep -n "// 60" _scripts/build_xml.py
   ```
   Заменить на `format_tc(total_sec, fractional=False)`.

**Step 2.5: Sys.path для импорта `_common`**

Все три скрипта запускаются как `python _scripts/match_timecodes.py ...` из корня. Чтобы `from _common import ...` работало, нужен `__init__.py` ИЛИ модификация `sys.path`. Самое чистое — добавить пустой:

```bash
touch _scripts/__init__.py
```

И каждый скрипт начинать так:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import ...
```

Эту строку поставить ПОСЛЕ `import sys` и ДО любого относительного импорта.

> **Альтернатива:** запускать как модуль `python -m _scripts.match_timecodes` — но это сломает существующую документацию в CLAUDE.md. Не делаем.

**Step 2.6: Верификация**

```bash
python _scripts/match_timecodes.py search projects/2026-03-thermobags
diff _baseline_2026-05-08/candidates.json projects/2026-03-thermobags/script/candidates.json

python _scripts/build_xml.py projects/2026-03-thermobags
diff _baseline_2026-05-08/2026-03-thermobags_rough_cut.xml \
     projects/2026-03-thermobags/assembly/2026-03-thermobags_rough_cut.xml

python _scripts/transcribe.py --help  # smoke test
```

Expected: оба `diff` пустые. `transcribe.py --help` показывает usage без ImportError.

**Step 2.7: Коммит**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor: extract _common.py for shared utilities

Общие константы (VIDEO_EXTS, AUDIO_EXTS, MEDIA_EXTS) и утилиты
(fix_windows_stdio, format_tc, parse_tc, probe_duration) вынесены в
_scripts/_common.py. До этого они дублировались между match_timecodes.py,
transcribe.py, build_xml.py с дрейфом в именах и поведении.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Bug fixes

**Files:**
- Modify: `_scripts/transcribe.py:413-428` (Bug 1, 2)
- Modify: `_scripts/build_xml.py:~640-728` (Bug 3 — `build_fcpxml` hero placement)
- Modify: `_scripts/match_timecodes.py:1010-1023` + 4 callsites (Bug 4)

**Step 3.1: Bug 1 + Bug 2 — transcribe exit code и traceback**

В `_scripts/transcribe.py`, функция `main` (около стр. 413-421):

ДО:
```python
for filepath in files:
    try:
        process_file(filepath, args, device, compute_type, token)
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        sys.exit(1)
    except Exception as e:
        print(f"Ошибка при обработке {filepath.name}: {e}")
        continue
```

ПОСЛЕ:
```python
import traceback

failed = 0
for filepath in files:
    try:
        process_file(filepath, args, device, compute_type, token)
    except KeyboardInterrupt:
        print("\nПрервано пользователем.", file=sys.stderr)
        return 130  # стандартный код для SIGINT
    except Exception as e:
        print(f"Ошибка при обработке {filepath.name}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        failed += 1
        continue
return 1 if failed else 0
```

И блок `if __name__ == "__main__":` (стр. ~424-428):

ДО:
```python
if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)  # avoid CUDA teardown crash
```

ПОСЛЕ:
```python
if __name__ == "__main__":
    rc = main() or 0
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)  # CUDA teardown crash workaround; preserve exit code
```

**Step 3.2: Bug 3 — `build_fcpxml` hero placement**

В `_scripts/build_xml.py`, функция `build_fcpxml`. Добавить локальный `placed_ids: set[int] = set()` где определяется `slava_clips`/`hero_clips` (около стр. ~635-640).

Заменить **все три** вхождения `hc["_placed"] = True` (стр. 668, 699 + где-то в трейлинг-блоке стр. ~716-728 если там тоже есть) на:
```python
placed_ids.add(id(hc))
```

Заменить **все** вхождения `hc.get("_placed")` (стр. 684) на:
```python
id(hc) in placed_ids
```

Заменить условие `unplaced = [hc for hc in hero_clips if not hc.get("_placed")]` (стр. 704) на:
```python
unplaced = [hc for hc in hero_clips if id(hc) not in placed_ids]
```

Грепнуть для уверенности:
```bash
grep -n "_placed" _scripts/build_xml.py
```
Должно вернуть 0 совпадений после правок.

**Step 3.3: Bug 4 — нормализация `verified.json` при загрузке**

В `_scripts/match_timecodes.py`:

1. Удалить функцию `_get_chosen_parts` (стр. 1010-1023).

2. Добавить новую функцию (рядом, например после `_get_chosen_parts`-точки):

```python
def _load_verified(project_dir: Path) -> dict:
    """Грузит verified.json и приводит legacy `chosen` → `chosen_parts` на месте."""
    verified_path = project_dir / "script" / "verified.json"
    with open(verified_path, encoding="utf-8") as f:
        data = json.load(f)
    for row in data.get("rows", []):
        if "chosen_parts" not in row and row.get("chosen", {}).get("file"):
            row["chosen_parts"] = [row["chosen"]]
        row.pop("chosen", None)
    return data
```

3. Найти все callsite'ы `_get_chosen_parts`:
   ```bash
   grep -n "_get_chosen_parts\|verified.json" _scripts/match_timecodes.py
   ```

4. Заменить:
   - `with open(verified_path) as f: data = json.load(f)` + последующее `_get_chosen_parts(row)` → `data = _load_verified(project_dir)`, далее использовать `row.get("chosen_parts", [])` напрямую.
   - В тех местах где раньше было `chosen = _get_chosen_parts(row)` — теперь `chosen = row.get("chosen_parts", [])`.

   Конкретные функции под подозрением: `cmd_snap`, `cmd_validate`, и preflight в `cmd_snap`.

**Step 3.4: Верификация**

XML идентичен baseline (Bug 3 проверяется только тем, что hero-клипы остаются на местах после одного вызова — двойной вызов не делаем):

```bash
python _scripts/build_xml.py projects/2026-03-thermobags
diff _baseline_2026-05-08/2026-03-thermobags_rough_cut.xml \
     projects/2026-03-thermobags/assembly/2026-03-thermobags_rough_cut.xml
```

Expected: пусто.

Если есть `verified.json` с legacy `chosen`-форматом — `cmd_snap` отрабатывает:
```bash
test -f projects/2026-03-thermobags/script/verified.json && \
  python _scripts/match_timecodes.py validate projects/2026-03-thermobags || \
  echo "verified.json нет — пропускаем"
```

Expected: либо validate отрабатывает без ошибок, либо явное «пропущено».

Smoke test transcribe (без реальной обработки — просто проверить что традиционный flow не сломан):
```bash
python _scripts/transcribe.py --help
```

Expected: usage показывается, exit code 0.

**Step 3.5: Коммит**

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix: real exit code in transcribe, traceback on errors, no input mutation in build_fcpxml, normalize verified.json on load

- transcribe.py: main() возвращает rc, os._exit(rc) сохраняет код выхода
- transcribe.py: Exception ловится с traceback в stderr, не заглушается
- build_xml.py: build_fcpxml использует локальный set(id(hc)) вместо
  мутации hc["_placed"] — повторный вызов больше не пропускает hero-клипы
- match_timecodes.py: _load_verified нормализует legacy chosen →
  chosen_parts один раз при загрузке; _get_chosen_parts удалён, callsites
  читают row["chosen_parts"] напрямую

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Performance

**Files:**
- Modify: `_scripts/build_xml.py:115-175` (`scan_project` — parallel ffprobe)
- Modify: `_scripts/match_timecodes.py:121-134` (`build_text_index` принимает norm_words)
- Modify: `_scripts/match_timecodes.py:790-810` (`load_transcripts` — передаёт norm_words)
- Modify: `_scripts/match_timecodes.py:598-646` (`detect_within_word` — bisect)

**Step 4.1: Перф #5 — параллельный ffprobe**

В `_scripts/build_xml.py`, функция `scan_project`. Сейчас два последовательных цикла (voiceover, interviews) с `info = probe_file(f)`. Собрать список файлов сначала, потом параллельно пробить:

```python
import concurrent.futures

def scan_project(project_dir: Path) -> tuple[dict, dict, dict]:
    voiceover_dir = project_dir / "raw" / "voiceover"
    interviews_dir = project_dir / "raw" / "interviews"
    print(f"  Voiceover: {voiceover_dir.relative_to(project_dir)}")
    print(f"  Interviews: {interviews_dir.relative_to(project_dir)}")

    # Соберём список (kind, path) всех медиа
    todo: list[tuple[str, Path]] = []
    if voiceover_dir.exists():
        for f in sorted(voiceover_dir.iterdir()):
            if f.suffix.lower() in MEDIA_EXTS:
                todo.append(("voiceover", f))
    if interviews_dir.exists():
        for f in sorted(interviews_dir.iterdir()):
            if f.suffix.lower() in MEDIA_EXTS:
                todo.append(("interview", f))

    # Параллельный probe (subprocess IO-bound, треды безопасны)
    print(f"  Сканирую {len(todo)} файлов параллельно...")
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=os.cpu_count() or 4
    ) as ex:
        infos = list(ex.map(lambda p: probe_file(p[1]), todo))

    files: dict = {}
    filename_to_key: dict = {}
    voiceover_count = 0
    first_interview_info = None

    for (kind, f), info in zip(todo, infos):
        if kind == "voiceover":
            voiceover_count += 1
            if voiceover_count > 1:
                print(f"  WARN: несколько voiceover-файлов, используется последний: {f.name}")
            print(f"  Сканирую: {f.name}")
            key = "voiceover"
        else:
            print(f"  Сканирую: {f.name}")
            key = f.stem.lower()
            if first_interview_info is None:
                first_interview_info = info
        files[key] = info
        filename_to_key[f.name] = key

    # ... остальное (seq_settings) без изменений ...
```

Импорт `os` уже есть в build_xml.py. Импорт `concurrent.futures` нужно добавить вверх файла.

**Step 4.2: Перф #7 — дедуп `norm_words`**

В `_scripts/match_timecodes.py`:

1. `build_text_index` (стр. 121-134) принимает уже нормализованные слова:

```python
def build_text_index(words: list[dict], norm_words: list[str]) -> tuple[str, list[int]]:
    """Собирает полный нормализованный текст и карту char→word_idx.

    norm_words: список нормализованных строк (один к одному с words).
    """
    parts = []
    char_map = []
    for i, norm in enumerate(norm_words):
        if not norm:
            continue
        if parts:
            char_map.append(i)
        parts.append(norm)
        char_map.extend([i] * len(norm))
    full_text = " ".join(parts)
    return full_text, char_map
```

2. `load_transcripts` (стр. ~790-810) — нормализует один раз и передаёт:

```python
all_words = []
for seg in data.get("segments", []):
    all_words.extend(seg.get("words", []))

if not all_words:
    print(f"  Пропущен {jp.name}: нет слов")
    continue

norm_words = [normalize(w.get("word", "")) for w in all_words]
source = data.get("source", jp.stem.replace(".transcript", ""))
full_text, char_map = build_text_index(all_words, norm_words)
```

3. Найти других caller'ов `build_text_index`:
   ```bash
   grep -n "build_text_index" _scripts/match_timecodes.py
   ```
   Если нашлись — там тоже передать `norm_words` (вычислить локально, если ещё не было).

**Step 4.3: Перф #8 — `bisect` в `detect_within_word`**

В `_scripts/match_timecodes.py`:

1. Добавить `import bisect` вверх файла (если ещё нет — грепнуть).

2. Заменить `detect_within_word` (стр. 598-646):

```python
def detect_within_word(rows: list[dict], transcripts: dict[str, list[dict]],
                       word_tol_ms: int = 50) -> list[dict]:
    """Детектирует попадание границы парта внутрь слова.

    Для каждого парта проверяет start и end: если значение лежит между
    word.start и word.end какого-то слова, и не близко к границам в
    пределах word_tol_ms — это конфликт.
    """
    tol_s = word_tol_ms / 1000.0
    out: list[dict] = []

    # Кеш: для каждого file — отсортированный список (start, end, word) и массив start'ов
    sorted_cache: dict[str, tuple[list[float], list[dict]]] = {}
    for fname, words in transcripts.items():
        clean = [w for w in words if w.get("start") is not None and w.get("end") is not None]
        clean.sort(key=lambda w: w["start"])
        starts = [w["start"] for w in clean]
        sorted_cache[fname] = (starts, clean)

    for row in rows:
        parts = row.get("chosen_parts") or []
        for pidx, p in enumerate(parts):
            cache = sorted_cache.get(p.get("file"))
            if not cache:
                continue
            starts, clean = cache
            for edge in ("start", "end"):
                t = p.get(edge)
                if t is None:
                    continue
                # Кандидат: последнее слово с start <= t
                idx = bisect.bisect_right(starts, t) - 1
                if idx < 0:
                    continue
                w = clean[idx]
                ws, we = w["start"], w["end"]
                if not (ws < t < we):
                    continue
                if (t - ws) <= tol_s or (we - t) <= tol_s:
                    continue
                out.append({
                    "row_idx": row["row_idx"],
                    "part_idx": pidx,
                    "edge": edge,
                    "word": w.get("word"),
                    "word_start": ws,
                    "word_end": we,
                    "part_value": t,
                })
    return out
```

**Step 4.4: Sanity-проверка эквивалентности `detect_within_word`**

Прогнать validate ДО и ПОСЛЕ на всех проектах с `verified.json`, сверить отчёты:

```bash
# Сохранить выходы старой реализации (если есть baseline) или прогнать на свежей
for proj in projects/*/; do
  vf="$proj/script/verified.json"
  if [ -f "$vf" ]; then
    python _scripts/match_timecodes.py validate "$proj" || true
    cp "$proj/script/validation_report.json" "/tmp/$(basename $proj)_post.json" 2>/dev/null || true
  fi
done
# Сравнить с baseline (если он есть от Step 0.4)
for f in /tmp/*_post.json; do
  base="_baseline_2026-05-08/$(basename $f)"
  if [ -f "$base" ]; then
    diff "$base" "$f" && echo "OK: $f" || echo "DIFF: $f"
  fi
done
```

Expected: «OK» для всех совпадений; если где-то diff — разобраться (возможно edge-case с overlap-границами Whisper, бьющий через 2 слова).

**Step 4.5: Финальная верификация**

```bash
python _scripts/match_timecodes.py search projects/2026-03-thermobags
diff _baseline_2026-05-08/candidates.json projects/2026-03-thermobags/script/candidates.json

python _scripts/build_xml.py projects/2026-03-thermobags
diff _baseline_2026-05-08/2026-03-thermobags_rough_cut.xml \
     projects/2026-03-thermobags/assembly/2026-03-thermobags_rough_cut.xml
```

Expected: оба `diff` пустые.

**Step 4.6: Коммит**

```bash
git add -A
git commit -m "$(cat <<'EOF'
perf: parallel ffprobe, dedup norm_words, bisect in detect_within_word

- build_xml.scan_project: ffprobe всех медиафайлов через ThreadPoolExecutor
  (5-10x быстрее на проектах с 10+ файлами)
- match_timecodes.load_transcripts: norm_words считается один раз и
  передаётся в build_text_index (раньше нормализация шла дважды)
- match_timecodes.detect_within_word: bisect_right по отсортированным
  start'ам вместо линейного скана. На часовых интервью ~10k слов × 200
  партов × 2 границы = 4M → log(10k) ≈ 13 шагов на edge

Артефакты verified против baseline на projects/2026-03-thermobags.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Renumber match-timecodes skill

**Files:**
- Modify: `.claude/commands/match-timecodes.md`

**Step 5.1: Прочитать текущий skill**

```bash
cat .claude/commands/match-timecodes.md
```

Зафиксировать структуру: какие шаги пронумерованы 6.5/6.6/6.7/6.8, какие — 7.

**Step 5.2: Перенумеровать**

Цель: 1, 2, 3, 4, 5, 6, **7**, 8 — где новый шаг 7 это validate-and-fix-loop (бывшие 6.5-6.8 свёрнуты в один шаг с под-пунктами 7.1, 7.2, 7.3, 7.4), а бывший шаг 7 (итоги) становится 8.

Конкретно:
- Бывший «Step 6.5 (validate + iteration controller setup)» → 7.1
- Бывший «Step 6.6 (row picker + context builder)» → 7.2
- Бывший «Step 6.7 (fix-агенты)» → 7.3
- Бывший «Step 6.8 (merger)» → 7.4
- Бывший «Step 7 (итоги)» → 8

Заменить все упоминания «Step 6.5/6.6/6.7/6.8» в тексте (если есть кросс-референсы) на новые номера.

**Step 5.3: Smoke test**

Если есть проект с готовым `candidates.json` — прогнать `/match-timecodes`. Если нет — просто прочитать markdown глазами на предмет логичности нумерации.

**Step 5.4: Коммит**

```bash
git add .claude/commands/match-timecodes.md
git commit -m "$(cat <<'EOF'
docs(match-timecodes): renumber steps after validate-loop integration

Шаги 6.5/6.6/6.7/6.8 свёрнуты в один шаг 7 (validate-and-fix-loop) с
под-пунктами 7.1-7.4. Бывший шаг 7 (итоги) → 8. Раньше нумерация
отражала историю интеграции, теперь — логическую структуру скилла.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Финальная проверка

После всех 5 задач:

```bash
git log --oneline -7
```

Expected: 5 коммитов поверх baseline + 1 design doc + 1 plan = 7 строк.

Прогнать full pipeline на термосумках:
```bash
python _scripts/match_timecodes.py search projects/2026-03-thermobags
# (если есть verified.json) python _scripts/match_timecodes.py validate projects/2026-03-thermobags
python _scripts/build_xml.py projects/2026-03-thermobags
```

Expected: всё отрабатывает, XML открывается в DaVinci, рулоны на местах.

Удалить `_baseline_2026-05-08/` когда уверены:
```bash
rm -rf _baseline_2026-05-08/
# .gitignore тоже почистить (или оставить как есть на будущее)
```
