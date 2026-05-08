# Pipeline cleanup — design

**Дата:** 2026-05-08
**Скоуп:** удаление мёртвого `cut_pauses` + чистка дублирования + точечные фиксы багов и производительности по результатам ревью пайплайна (4 скрипта, ~3700 строк после удаления).

## Контекст

`/simplify` поднял ревью трёх агентов по всему пайплайну (`match_timecodes.py`, `build_xml.py`, `cut_pauses.py`, `transcribe.py` + skills). На вопрос «выкидывать ли cut_pauses» проверил факты:

- 8 директорий `projects/*/cuts/` — все пустые.
- Никакой скрипт не вызывает `_scripts/cut_pauses.py` (CLI-only, нет cross-script зависимостей).
- Единственный консумер `cuts/` — `build_xml._pick_media_dir` (приоритезирует cuts/ над raw/).
- Текущий процесс: match_timecodes/snap → script.csv с таймкодами → build_xml → DaVinci. Промежуточные «очищенные» файлы не нужны, исходники остаются как есть.

## Решение

Делаем серию из 5 логических коммитов. Каждый коммит изолирован, тестируется отдельно, легко откатывается.

## C1 — Удаление cut_pauses

| Файл | Действие |
|---|---|
| `_scripts/cut_pauses.py` | удалить (537 строк) |
| `_scripts/build_xml.py:100-112` `_pick_media_dir` | удалить функцию; в `scan_project` использовать `project_dir / "raw" / "voiceover"` и `project_dir / "raw" / "interviews"` напрямую |
| `CLAUDE.md` | удалить раздел «cut_pauses.py — удаление пауз...»; убрать строку `cuts/` из блока структуры проектов; убрать упоминание «очищенные cut_pauses файлы автоматически подхватываются» из раздела build_xml |
| `projects/*/cuts/` | удалить 8 пустых директорий |
| Память: `project_cut_pauses_audio_support.md` | удалить файл, убрать строку из MEMORY.md |
| Память: `project_cutting_improvements.md` | оставить (исторический след) с пометкой что cut_pauses removed 2026-05-08 |
| `docs/archive/`, `docs/plans/2026-03-16-cut-pauses-*`, `docs/plans/2026-04-23-cutting-improvements-*` | не трогаем — это история |
| `docs/plans/2026-04-29-employee-pipeline*.md` | не трогаем — design doc будущего пайплайна, переписывать отдельно |

**Бонус:** «баг #1» из ревью (snap не смотрит в `cuts/`) автоматически становится не-багом.

## C2 — Общий модуль `_scripts/_common.py`

После удаления cut_pauses реальные дубликаты сжимаются:

| Дубликат | До (4 скрипта) | После (3 скрипта) |
|---|---|---|
| `_ensure_cuda_dll_path` | 2 файла | только transcribe.py — не дубликат |
| `os._exit(0)` хак | 2 файла | только transcribe.py — не дубликат |
| Время `MM:SS` форматтер | 4 файла | 3 (match_timecodes, transcribe, build_xml) |
| ffprobe duration | 3 файла | 2 (transcribe, build_xml) |
| UTF-8 stdio fix | 4 файла | 3 файла |
| `VIDEO_EXTS` константы | 4 файла | 3 файла |

Один файл `_scripts/_common.py` (~80 строк), не пакет:

```python
VIDEO_EXTS = frozenset({".mp4", ".mov", ".mkv", ".avi"})
AUDIO_EXTS = frozenset({".m4a", ".mp3", ".wav", ".aac", ".flac"})
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS

def fix_windows_stdio() -> None: ...
def format_tc(seconds: float, *, fractional: bool = True) -> str: ...
def parse_tc(tc_str: str) -> float: ...
def probe_duration(path: Path) -> float: ...   # с check=True и понятной ошибкой
```

**Миграция:**

- `match_timecodes.py`: `fmt_tc` → `format_tc(s, fractional=True)`; убрать локальный `VIDEO_EXTS`, импортировать из `_common`.
- `transcribe.py`: `format_time` → `format_tc(s, fractional=False)`; `get_duration` → `probe_duration`; убрать локальный `VIDEO_EXTS`.
- `build_xml.py`: inline `MM:SS` (стр. 830-832) → `format_tc(s, fractional=False)`; локальный `parse_tc` → импорт; убрать локальные ext-константы. `probe_file` остаётся (он суперсет).

**Не выносим:** `_ensure_cuda_dll_path`, `os._exit`, `format_unified_tc` (build-xml-специфичный), `normalize` (match-timecodes-специфичный).

## C3 — Баги

### Bug 1 — `transcribe.py:428` `os._exit(0)` глотает exit code

```python
if __name__ == "__main__":
    rc = main() or 0
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)  # CUDA teardown crash workaround; preserve exit code
```

`main()` возвращает 0/1 явно вместо `sys.exit(1)` (последний всё равно перебивался).

### Bug 2 — `transcribe.py:419-421` bare except без traceback

```python
except Exception as e:
    import traceback
    print(f"Ошибка при обработке {filepath.name}: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    continue
```

Если хоть один файл упал — `main()` вернёт 1, и `os._exit(rc)` это передаст.

### Bug 3 — `build_xml.build_fcpxml` мутирует входные `hc["_placed"]`

Текущий код пишет `hc["_placed"] = True` прямо в словари из `hero_clips` (стр. 668, 684, 699). Повторный вызов `build_fcpxml` пропускает все hero-клипы.

```python
placed_ids: set[int] = set()
# вместо hc["_placed"] = True:
placed_ids.add(id(hc))
# вместо if hc.get("_placed"):
if id(hc) in placed_ids: continue
```

`id()` стабилен в пределах вызова (`hero_clips` — конкретные dict-объекты, не копии).

### Bug 4 — Двойной формат `chosen` vs `chosen_parts`

`_get_chosen_parts` (`match_timecodes.py:1010-1023`) — миграционный шим, вызывается в 4 местах. Перенести миграцию в загрузчик:

```python
def _load_verified(project_dir: Path) -> dict:
    with open(project_dir / "script" / "verified.json", encoding="utf-8") as f:
        data = json.load(f)
    for row in data.get("rows", []):
        if "chosen_parts" not in row and row.get("chosen", {}).get("file"):
            row["chosen_parts"] = [row["chosen"]]
        row.pop("chosen", None)
    return data
```

После этого `_get_chosen_parts` удаляется, все consumers читают `row["chosen_parts"]` напрямую.

## C4 — Производительность (только низкий риск)

### #5 — Параллельный ffprobe в `build_xml.scan_project`

`probe_file()` сейчас вызывается последовательно (стр. 139, 149). Через `concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4)` → потоки безопасны (subprocess IO-bound). 5-10× ускорение скана. **Риск низкий.**

### #7 — Дедуп `norm_words`

`load_transcripts` (стр. 803) и `build_text_index` (стр. 126) оба нормализуют каждое слово. Передать готовый `norm_words` в `build_text_index`. ~2× быстрее загрузка транскриптов. **Риск низкий.**

### #8 — `bisect` в `detect_within_word`

`match_timecodes.py:598-646` — для каждого парта × edge линейный проход по всем словам файла. На часовом интервью (~10k слов) × 200 партов × 2 edges = 4M сравнений.

Слова уже отсортированы по `start`. Через `bisect_right([w["start"] for w in words], t) - 1` — O(log n). Проверить кандидата + следующее (на overlap-границы Whisper). **Риск низкий**, но добавим unit-тест на сравнение со старой реализацией на реальных данных.

### Не делаем

- ~~#6 параллельный silencedetect~~ — ffmpeg-on-Windows pipe-quirks, риск выше профита
- ~~#9 sliding counter в `fuzzy_whole_match`~~ — нужен серьёзный регресс-тест, не оправдывает risk

## C5 — Структурные

### #17 — Перенумеровать шаги в `match-timecodes.md`

Сейчас: 1, 2, 3, 4, 5, 6, **6.5, 6.6, 6.7, 6.8**, 7. Это история (validate-loop добавили поверх 7-шаговой логики). Сейчас loop — основной поток. Skill читает Claude каждый раз заново — путаная нумерация = путаное исполнение. Цель: 1, 2, 3, 4, 5, 6, 7, 8 с логичным выделением validate-and-fix-loop в отдельный шаг с под-пунктами.

### Не делаем

- ~~#16 Status enum~~ — статусы появляются и в Python, и в skill markdown; enum не помогает текстовой части. Чистая косметика.
- ~~#18 build_xml clip-loop refactor~~ — трогает XML-output, тестов нет, риск выше профита.

## Тестирование

Автотестов в репо нет. На каждом коммите ручной прогон:

| Коммит | Проверка |
|---|---|
| C1 | `python _scripts/build_xml.py projects/2026-03-thermobags` отрабатывает; в логах `Voiceover: raw/voiceover` (не cuts/); XML открывается в DaVinci |
| C2 | `match_timecodes.py search`, `transcribe.py --help`, `build_xml.py` отрабатывают; XML диф пуст vs C1-baseline |
| C3 | `transcribe.py` на сбойном файле печатает traceback, rc != 0; build_xml генерит hero-клипы корректно |
| C4 | На термосумках: `candidates.json`, `validation_report.json`, `*_rough_cut.xml` идентичны pre-C4-baseline |
| C5 | `/match-timecodes projects/2026-03-thermobags` отрабатывает без сбоев |

Перед C4 сохранить baseline-артефакты для diff'а.

## Последовательность коммитов

1. `refactor: drop cut_pauses, simplify build_xml media discovery` (включая чистку памяти)
2. `refactor: extract _common.py for shared utilities`
3. `fix: real exit code in transcribe, traceback on errors, no input mutation in build_fcpxml, normalize verified.json on load`
4. `perf: parallel ffprobe, dedup norm_words, bisect in detect_within_word`
5. `docs(match-timecodes): renumber steps after validate-loop integration`

## Что осталось за бортом

Сознательно не делаем (для будущих ревью если станет больно):
- Status enum (косметика)
- build_xml clip-loop refactor (риск без тестов)
- Параллельный silencedetect (ffmpeg-on-Windows)
- Sliding counter в `fuzzy_whole_match` (нужен серьёзный регресс)
- Расширение `cut_pauses` на аудио (cut_pauses удаляется — пункт умирает естественно)
