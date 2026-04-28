# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Factory** — Video automation pipeline for Russian-language YouTube interviews. Transcription, pause removal, hero reply cutting, project assembly.

Design docs are in `docs/plans/`. Original cut_pauses spec archived in `docs/archive/task-cut-pauses.md`.

## Scripts

### cut_pauses.py — удаление пауз и слов-паразитов

```bash
pip install faster-whisper tqdm
python _scripts/cut_pauses.py <input_file_or_dir> [--output PATH] [--model large-v3] [--pause 0.5] [--profile slava|hero] [--save-transcript]
```

`--profile slava` (по умолчанию) — агрессивная чистка для войсовера: FILLER_WORDS + заикания + междометия + повторы. `--profile hero` — мягкая чистка интервью героя: только заикания, междометия и подряд идущие повторы; FILLER_WORDS не трогаются. Whisper ru-транскрипт редко содержит сами междометия/заикания — на практике на hero-профиле режутся в основном повторы и паузы.

Requires `ffmpeg` and `ffprobe` on PATH. CUDA is auto-detected with CPU fallback. Input должен быть видеоформат (`.mp4/.mov/.mkv/.avi`) — аудио `.m4a/.mp3/.wav` пока не поддерживается.

### transcribe.py — транскрибация с диаризацией

```bash
pip install whisperx
python _scripts/transcribe.py <input_file_or_dir> [--speakers 2] [--model large-v3] [--output PATH] [--json]
```

Requires `ffprobe` on PATH, `HF_TOKEN` env variable (or `--hf-token`) for pyannote diarization model.
Outputs: `{filename}.transcript.txt` (human-readable). With `--json`: also `{filename}.transcript.json` (word-level timestamps).

### match_timecodes.py — сопоставление реплик сценария с таймкодами

```bash
python _scripts/match_timecodes.py search <project_dir>    # Проход 1: поиск кандидатов → candidates.json
python _scripts/match_timecodes.py snap <project_dir>       # Проход 3: snap to silence → обновляет script.csv
python _scripts/match_timecodes.py compact <project_dir>    # Генерация words_compact.txt для агентов
```

Требует `ffmpeg` на PATH (для silencedetect). Транскрипты должны быть в `transcripts/*.transcript.json`.
Проход 2 (агентная верификация) выполняется скиллом `/match-timecodes`.

`candidates.json` содержит `rows[i]` с полями `parts[]` (каждая часть: `text + candidates[]`), `unmatched[]`, `mode` (`whole`/`split`), `status` (`single`/`multiple`/`multi_part`/`partial`/`not_found`). Составные цитаты автоматически определяются через `fuzzy_whole_match` (LCS) + split по предложениям. Агентная верификация пишет в `verified.json` поле `chosen_parts[]` — по одному выбору на каждую часть.

### build_xml.py — генерация FCP 7 XML черновой сборки

```bash
python _scripts/build_xml.py <project_dir> [--davinci]
```

Сканирует `voiceover/` и `interviews/` (видео + аудио форматы), получает метаданные через `ffprobe`, читает `script/script.csv` и генерирует FCP 7 XML в `assembly/`. Для каждого подкаталога приоритет у `cuts/<subdir>/` (если непуст), иначе `raw/<subdir>/`. Так очищенные cut_pauses файлы автоматически подхватываются. Выходные файлы: `{name}_rough_cut.xml` (относительные пути) и `{name}_rough_cut_local.xml` (абсолютные). С флагом `--davinci` дополнительно генерирует `{name}_rough_cut.fcpxml` (FCPXML 1.9 для DaVinci Resolve). Требует `ffprobe` на PATH.

**Формат таймкодов в CSV:** одна реплика может быть составной. Формат части — `file.ext: MM:SS.ss — MM:SS.ss` (двоеточие + em-dash, новый) или `file.ext, MM:SS.ss -> MM:SS.ss` (старый). Составные цитаты склеиваются разделителем ` || `, например:

```
Тюльпаны.mp4: 01:00.00 — 01:03.00 || Тюльпаны 2.mp4: 02:10.00 — 02:12.00
```

`build_xml.py` раскладывает все части впритык на треке спикера (V1 — Слава, V2 — Герой); имя клипа получает суффикс `(i/n)`.

## Skills

### /yt-analyze + /yt-write — создание сценария видео

```bash
/yt-analyze <project_dir>   # Анализ: цифры, угол, приёмы, структура → script/analysis.md
/yt-write <project_dir>     # Написание + ревью → script/script_draft.csv
```

Двухэтапный процесс с интегрированными драматургическими приёмами (`docs/youtube-best-practices/`, 17 файлов) и агентом-ревьюером. `/yt-analyze` выбирает подходящие приёмы по фактуре и строит структуру. `/yt-write` пишет сценарий и запускает самопроверку (1-3 итерации). Дизайн: `docs/plans/2026-03-28-yt-script-v2-design.md`.

Первая версия (`/youtube-script`) архивирована в `docs/archive/youtube-script-v1.md`.

### /match-timecodes — верификация таймкодов

Проход 2 агентной верификации. Запускается после `match_timecodes.py search`.

## Conventions

- **Project folders**: `YYYY-MM-description` under `projects/`, structured by content type:
  ```
  raw/interviews/    ← записи созвонов
  raw/voiceover/     ← начитка Славы
  raw/article.md     ← статья
  transcripts/       ← расшифровки (transcribe.py)
  cuts/              ← нарезки: очищенные видео, реплики героя
  audio/             ← извлечённый звук
  script/            ← сценарий
  subtitles/         ← SRT-файлы
  assembly/          ← FCP XML, проект
  publish/           ← финал + мета
  project.md         ← статус, заметки
  ```
- **Scripts are generic** — accept input + `--output`, don't know about project structure. Orchestration is agent/skill responsibility.
- **Output naming**: `{filename}_clean.mp4`, `{filename}.transcript.txt`
- **User-facing messages and comments**: Russian language
- **Paths**: Use `pathlib.Path` objects
- **Video formats**: `.mp4`, `.mov`, `.mkv`, `.avi`
- **Git branches**: `main` is the primary branch; development happens on `master` or feature branches
