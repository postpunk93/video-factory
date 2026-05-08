# Дизайн — что взять из video-use под наши задачи

**Дата:** 2026-05-08
**Источник идей:** `C:\Projects\video-use` (browser-use/video-use, open source)
**Контекст ветки:** `fix/verified-overlap-cause`

## Зачем

Сравнили наш пайплайн (детерминированные скрипты + сценарист-человек + DaVinci) с
video-use (LLM-driven editing с EDL.json и render.py). Большая часть их идей нам
не нужна: physical cut/render выкинут как класс — задача стала «правильно собрать
карту таймкодов для импорта в DaVinci». DaVinci сам делает crossfade'ы,
loudnorm, color grade, конкатенацию.

Что **остаётся применимым** — то, что улучшает **карту таймкодов**: артефакты
для агентов и сценариста + детерминированная валидация выбора агента-верификатора.

## Цели (этап B — этот документ)

1. Закрыть открытую задачу `project_verified_json_overlap_fix.md` —
   детектировать оверлапы word-границ внутри одной строки `verified.json`
   детерминированно, без догадок агента.
2. Дополнительно ловить «попадание границы парта внутрь слова» — когда `start`
   или `end` парта приходится не на word boundary транскрипта.
3. Дать сценаристу и агенту читабельный артефакт `packed.md` — фразовое
   представление транскриптов с `[start-end]` и (если есть) speaker-тегом.
   Адаптация `helpers/pack_transcripts.py` из video-use под формат WhisperX.

## Не-цели

- Автоматически чинить оверлапы. Validator только репортит — решение остаётся
  за человеком/агентом-верификатором (явное решение в духе video-use «verify,
  don't auto-fix»).
- Менять стек ASR (WhisperX → ElevenLabs Scribe). Отдельный разговор.
- Покрывать аудио fades, loudnorm, HDR-tonemap, color grade — DaVinci делает
  это лучше, и нам это и не нужно (мы работаем картой, а не рендерим видео).
- Делать `timeline_view` PNG. Этап A — после того, как (B) поработает на
  реальном проекте и станет ясно, нужно ли вообще.

## Этап B1 — pack-формат транскриптов

Новая команда `match_timecodes.py pack <project_dir>`. Сканирует
`transcripts/*.transcript.json` (формат WhisperX:
`{segments: [{words: [{word, start, end, speaker?}]}]}`), группирует
word-level entries во фразы по правилу:

- **разрыв на тишине** — gap между концом предыдущего kept-токена и началом
  следующего ≥ `0.5s` (порог как у video-use, конфигурируется флагом
  `--silence-threshold`),
- **разрыв на смене speaker** — если `--diarize` использовался при
  транскрибации (иначе тегов нет — разбиение только по тишине).

**Output:**
- `<project>/transcripts/{file}.packed.txt` — на каждый исходник,
- `<project>/transcripts/packed.md` — общий index-файл, склейка с заголовками.

**Формат строки:**
```
[01:23.45-01:27.10] S0 текст фразы
```
Без speaker-тега, если диаризации не было:
```
[01:23.45-01:27.10] текст фразы
```

**Кто читает:**
- сценарист — структурный обзор транскриптов вместо плоских `*.transcript.txt`,
- `/yt-analyze` — улучшенный вход (фразы вместо абзацев),
- агент-верификатор `/match-timecodes` — для контекста при выборе кандидатов.

**Что НЕ удаляем:** существующие `*.transcript.txt` (плоский) и
`*.words_compact.txt` (для агента поиска по словам) остаются как есть. Pack —
дополнительный артефакт, не замена.

**Объём:** ~80 строк в новой функции `pack_transcripts()` + регистрация
подкоманды. Никаких новых deps.

## Этап B2 — overlap-validator

Новая команда `match_timecodes.py validate <project_dir>`. Читает
`script/verified.json`, проверяет каждую `row` на два класса проблем.

### Проблема 1 — Word-overlap внутри одной строки

Для каждой пары парт `(i, j)` в `_get_chosen_parts(row)` с одинаковым
`file`: если `[start_i, end_i]` пересекается с `[start_j, end_j]` (т. е.
`max(start_i, start_j) < min(end_i, end_j) - min_overlap_tol`) — это
конфликт. Это ровно тот класс ошибок, который описан в открытой задаче
(термосумки, строки 51, 81, 90).

### Проблема 2 — Within-word boundary

Для каждого парта `(file, start, end)` загружаем
`transcripts/{file}.transcript.json`, ищем слова, у которых
`word.start < part.start < word.end` или `word.start < part.end < word.end`.

Если граница парта попадает внутрь слова (а не близко к его `start` или `end`
в пределах допуска `±word_tol_ms`) — это конфликт.

### Output

Список конфликтов в stdout, машиночитаемая копия в
`script/validation_report.json`:

```json
{
  "overlaps": [{"row_idx": 51, "file": "1774165021.6478019.mov",
                "part_a": 0, "part_b": 1, "intersection_s": 1.19}],
  "within_word": [{"row_idx": 22, "part_idx": 0, "edge": "end",
                   "word": "...", "word_start": 12.34, "word_end": 12.78,
                   "part_value": 12.55}]
}
```

Exit code: `1` если есть проблемы, `0` если чисто. **Ничего не модифицирует.**

### Где встраивается

- standalone — `match_timecodes.py validate <project>` для CI/проверки и для
  скилла `/match-timecodes`,
- `cmd_snap` в начале вызывает validator: если есть оверлапы — печатает их и
  **отказывается** snap-нуть (потому что snap всё равно записал бы сломанный
  CSV); within-word — только warning, не блокер.

### Что НЕ делает

- не пытается чинить (ни «midpoint», ни «снепить к тишине внутри пересечения») —
  явное решение «verify, don't auto-fix»,
- не валидирует CSV (`script.csv`) — только `verified.json`. CSV генерируется
  из verified.json + snap, исправлять надо upstream.

### Пороги (дефолты)

- `--word-tol-ms 50` — допуск «граница парта попала на word boundary»,
- `--min-overlap-ms 50` — порог минимального оверлапа (чтобы не спамить
  копеечными артефактами Whisper).

**Объём:** ~120 строк в `validate_verified()` + helper `_check_within_word()`
+ регистрация подкоманды. Никаких новых deps.

## Этап A — timeline_view (эскиз, не реализация)

Только наброс — детали разбираем отдельным дизайн-доком после того, как (B)
поработает.

**Идея:** порт `helpers/timeline_view.py` из video-use под наш формат
WhisperX. На вход — путь к видео, диапазон `[start, end]`, путь к
`*.transcript.json`. На выход — PNG: filmstrip (10 кадров) + RMS-waveform +
метки слов от Whisper + затемнение пауз ≥400 мс.

**Где может встраиваться:**
- standalone CLI: `_scripts/timeline_view.py <video> <start> <end>`,
- инструмент агента в `/match-timecodes`: для каждого кандидата с
  `status: multiple` или `multi_part` агент генерит PNG, смотрит, выбирает
  осмысленно (а не по тексту вслепую).

**Зависимости (новые):** `Pillow`, `numpy`. Это первая «тяжёлая» зависимость
в проекте — поэтому спорный вопрос.

**Решение брать или нет — после (B).** Гипотеза: validator закроет оверлапы
детерминированно, within-word warning'и выявят остальные кейсы. Если их
останется мало или они тривиально чинятся переверификацией — timeline_view не
нужен. Если их много и агент стабильно ошибается на одних и тех же местах —
берём.

## Тестирование

**Минимум:**
- `tests/test_pack.py` — phrase-grouping на синтетических transcripts:
  проверка разрыва на тишине ≥0.5s, на смене speaker, отсутствие лишних
  разрывов на коротких паузах.
- `tests/test_validate.py` — два класса проблем на синтетике: пара партов с
  известным пересечением → детектится; парт с границей внутри слова →
  детектится; всё чисто → exit 0.

**E2E проверка на живом проекте:**
`python _scripts/match_timecodes.py validate projects/2026-03-thermobags`.
Должны увидеть конкретно строки 51, 81, 90 (известные кейсы из памяти про
оверлапы). Если они там — фикс работает; если нет — дизайн не покрывает
реальную боль, возвращаемся к доске.

**Что НЕ покрывается тестами:** `pack` рендеринг markdown — слишком тривиально
и читается глазами; визуальный QC всё равно нужен.

## Что из video-use НЕ берём (и почему)

Для записи в память проекта и чтобы не возвращаться к этому списку:

- **30ms audio fades, per-segment extract → lossless concat** — это в DaVinci.
- **Loudnorm two-pass** — DaVinci.
- **HDR → SDR tone mapping** — DaVinci (если вообще встретится).
- **Auto color grade по signalstats** — DaVinci.
- **`render.py` целиком** — мы не рендерим финал, мы делаем FCPXML.
- **EDL JSON формат** — у нас аналог `script.csv` + DaVinci-импорт. Менять
  этот контракт = трогать build_xml.py + workflow сценариста, ROI отрицательный.
- **`grade.py` presets / `--filter` raw** — DaVinci.
- **Subtitles LAST в filter chain** — у нас нет subtitle-pipeline.
- **Parallel sub-agents для анимаций** — у нас сейчас нет анимационных
  оверлеев. Если появятся — этот паттерн пригодится, но это другая задача.
- **ElevenLabs Scribe вместо WhisperX** — отдельный разговор: цена, latency,
  word-level качество для русского языка нужно проверять. Не в этом дизайне.
- **`project.md` session memory** — у нас уже есть `project.md` в каждом
  проекте + auto-memory `MEMORY.md`. Дублировать их паттерн не надо.
