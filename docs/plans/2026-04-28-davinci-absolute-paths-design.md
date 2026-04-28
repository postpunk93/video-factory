# DaVinci FCPXML с абсолютными путями

## Контекст

`build_xml.py` сейчас генерирует:
- FCP 7 XML в двух версиях: `_rough_cut.xml` (относительные пути) + `_rough_cut_local.xml` (абсолютные).
- При флаге `--davinci` дополнительно `_rough_cut.fcpxml` (FCPXML 1.9) — **только с относительными путями**.

Когда давинчи открывают на той же машине, где собиралась сборка, относительные пути требуют ручного релинка. Нужна симметрия с FCP 7 — допфайл с абсолютными путями.

## Решение

Параметризовать `build_fcpxml(... , relative: bool)` и при `--davinci` сгенерировать обе версии.

### Изменения в `_scripts/build_xml.py`

1. **`build_fcpxml` принимает `relative: bool`.** В цикле `resources` (строка ~598):
   ```python
   src_url = info["path"].name if relative else path_to_fcpxml_url(info["path"])
   ```
   Функция `path_to_fcpxml_url` уже определена (строка 336), сейчас не используется — пригодится здесь.

2. **Цикл генерации в `main`** (по аналогии с FCP 7, строки 844–854):
   ```python
   if args.davinci:
       for relative, suffix in [(False, "_local"), (True, "")]:
           fcpxml = build_fcpxml(clips, files, seq_settings, seq_name, relative=relative)
           ...
   ```

### Файлы на выходе при `--davinci`

- `{name}_rough_cut.fcpxml` — относительные пути (для передачи в zip)
- `{name}_rough_cut_local.fcpxml` — абсолютные пути (локальное открытие без релинка)

### Дока

Обновить описание `--davinci` в `CLAUDE.md`:
> С флагом `--davinci` дополнительно генерирует `{name}_rough_cut.fcpxml` (относительные) и `{name}_rough_cut_local.fcpxml` (абсолютные пути) — FCPXML 1.9 для DaVinci Resolve.

## Что НЕ делаем

- Не трогаем структуру FCPXML, элементы, тайминг — меняется только `src` ассетов.
- Тестов на `build_xml` в репо нет; отдельные не пишем — проверка глазами на живом проекте.
