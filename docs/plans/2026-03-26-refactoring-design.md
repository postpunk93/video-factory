# Рефакторинг структуры проекта

**Дата:** 2026-03-26
**Статус:** утверждён

## Цель

Навести порядок: убрать мусор из проектов, вынести `build_xml.py` в generic-скрипт, очистить корень репо.

## 1. Generic `build_xml.py` → `_scripts/`

Объединить два проектных `build_xml.py` (tulips, thermobags) в один generic скрипт.

**Интерфейс:**
```bash
python _scripts/build_xml.py <project_dir>
```

**Логика:**
- Сканирует `raw/voiceover/` и `raw/interviews/` — находит медиафайлы
- Снимает метаданные через `ffprobe` (resolution, fps, sample_rate, channels, duration)
- Определяет fps секвенции по основному интервью-файлу
- Читает `script/script.csv` с таймкодами (формат: `filename, MM:SS.ss -> MM:SS.ss`)
- Генерирует FCP XML (два варианта: абсолютные + относительные пути)
- Сохраняет в `assembly/{project_name}_rough_cut.xml` и `{project_name}_rough_cut_local.xml`

**Конфиг не нужен** — всё выводится автоматически. Имя секвенции = имя проекта.

## 2. Удаление из проектов

### tulips/script/
- `match_timecodes.py` — устаревшая копия (заменена `_scripts/match_timecodes.py`)
- `merge_verified.py` — одноразовый скрипт с хардкодом данных
- `chunk_*.json`, `*_context.txt` — промежуточные артефакты агентной верификации

### thermobags/script/
- `_merge_verified.py` — одноразовый скрипт
- `_chunk*.json`, `_verify_*.json`, `_hero_rows.json`, `_slava_rows.json`, `_unverified.json` — промежуточные артефакты

### Оба проекта
- `assembly/build_xml.py` — заменён generic-версией в `_scripts/`
- Все `*.tmp.*` файлы — артефакты Claude Code

## 3. Очистка корня

- Все `*.tmp.*` файлы (в корне, `_scripts/`, проектах) — удалить
- `audio1343572807.txt`, `audio1367966378.txt`, `audio1375241478.txt` — переместить в `docs/notes/audio-process-call/` (три части одного созвона)
- `pipeline.md`, `youtube-script.md` — переместить в `docs/notes/`

## 4. Что НЕ трогаем

- `_scripts/` (cut_pauses.py, transcribe.py, match_timecodes.py)
- `script/script.csv`, `verified.json`, `candidates.json` — рабочие данные
- `assembly/*.xml` — сгенерированные проекты Premiere
- `docs/plans/` — документация
- Структуру папок проектов (raw/, transcripts/, cuts/ и т.д.)

## Порядок выполнения

1. Создать generic `_scripts/build_xml.py`
2. Проверить на обоих проектах (tulips, thermobags)
3. Удалить мусор из проектов
4. Очистить корень, переместить документы
5. Обновить CLAUDE.md
