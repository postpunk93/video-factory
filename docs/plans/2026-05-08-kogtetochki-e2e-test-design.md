# E2E test пайплайна на kogtetochki

**Дата:** 2026-05-08
**Цель:** Регресс-прогон полного пайплайна `match_timecodes → build_xml` на проекте `2026-04-kogtetochki` после фиксов 2026-04-28 (баги 1-3) и 2026-05-08 (validate auto-fix loop). Если ок — двигаемся к улучшению нарезки.

## Контекст

Существующий state на kogtetochki сгенерирован Apr 30 — до:
- LCS-aligned boundaries в `fuzzy_whole_match` (баг 1)
- `_split_false_starts` + `_drop_redundant_parts` (баг 3)
- Удаления `cut_pauses` и упрощения `build_xml` media discovery
- Команды `validate` и preflight в `cmd_snap`
- Auto-fix loop в `/match-timecodes`

Скрипт: 103 строки, 3 составные цитаты с `||`, FIXME/NOT_FOUND нет.

## Архитектура прогона

Линейный пайплайн с гейтом на каждой стадии. Halt → стоп, обсуждение.

```
backup → search → /match-timecodes → snap → build_xml --davinci → DaVinci visual
```

Ресурсоёмкие стадии последовательно (никакого параллелизма).

## Стадии и гейты

| Стадия | Команда | Verify | Halt |
|---|---|---|---|
| backup | копирование в `script/before-rerun/` | файлы скопированы | I/O ошибка |
| search | `match_timecodes.py search` | candidates.json валидный, status distrib | not_found > 5 строк |
| /match-timecodes | скилл | validation_report чистый, все строки `chosen_parts` | auto-fix не сошёлся за 3 итерации |
| snap | `match_timecodes.py snap` | exit 0, script.csv парсится | preflight validate fail |
| build_xml | `build_xml.py --davinci` | 4 файла в `assembly/`, XML парсится | любая ошибка |

## Бэкап

Цель — иметь baseline для diff'а после прогона. Бэкапим:

```
script/before-rerun/
├── candidates.json
├── verified.json
├── script.csv
└── assembly/
    ├── *_rough_cut.xml
    ├── *_rough_cut_local.xml
    ├── *_rough_cut.fcpxml
    └── *_rough_cut_local.fcpxml
```

После прогона — diff `script.csv` vs `before-rerun/script.csv` чтоб увидеть, как фиксы 1-3 сдвинули таймкоды.

## Что не входит

- Транскрибация (готова с Apr 30)
- Тестирование `pack` команды
- Регресс на других проектах (thermobags, tulips и т.д.)
- Автоматическое сравнение XML — diff делаем глазами

## Финальный шаг

Пользователь открывает `assembly/2026-04-kogtetochki_rough_cut.fcpxml` в DaVinci и проверяет:
- Нет offset'ов в начале клипов (фикс бага 1)
- Нет false-start'ов внутри клипов (фикс бага 3)
- Составные цитаты впритык, без гэпов
- V1 = Слава, V2 = Герой
