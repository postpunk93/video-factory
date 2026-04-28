# DaVinci FCPXML с абсолютными путями — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** При флаге `--davinci` в `_scripts/build_xml.py` генерировать два файла FCPXML — с относительными и абсолютными путями (по аналогии с FCP 7 XML).

**Architecture:** Параметризовать существующую функцию `build_fcpxml(... , relative: bool)` (сейчас всегда относительные) и в `main` обернуть запись в цикл `[(False, "_local"), (True, "")]` — точная симметрия с уже работающей логикой для FCP 7 (build_xml.py:844–854).

**Tech Stack:** Python 3, `xml.etree.ElementTree`, существующая утилита `path_to_fcpxml_url` (build_xml.py:336).

**Design doc:** `docs/plans/2026-04-28-davinci-absolute-paths-design.md`

**Тестов нет:** для `build_xml.py` нет автотестов в репозитории; верификация — ручной прогон на `projects/tulips` + грep `pathurl` в выходных файлах. Это решение зафиксировано в дизайн-доке, отдельный харнес не пишем (YAGNI).

---

## Task 1: Параметризовать `build_fcpxml`

**Files:**
- Modify: `_scripts/build_xml.py:572` (сигнатура `build_fcpxml`)
- Modify: `_scripts/build_xml.py:598` (формирование `src_url`)

**Step 1: Обновить сигнатуру**

Изменить:
```python
def build_fcpxml(clips, files, seq_settings, seq_name):
```
на:
```python
def build_fcpxml(clips, files, seq_settings, seq_name, relative=True):
```

`relative=True` оставляем дефолтом — текущее поведение, на случай других вызовов (их сейчас нет, но безопаснее).

**Step 2: Подменить формирование `src_url`**

Найти строку (примерно 598):
```python
src_url = info["path"].name
```

Заменить на:
```python
src_url = info["path"].name if relative else path_to_fcpxml_url(info["path"])
```

`path_to_fcpxml_url` уже определён на строке 336, импорта добавлять не нужно.

**Step 3: Sanity-check синтаксиса**

Запустить:
```bash
python -c "import ast; ast.parse(open('_scripts/build_xml.py', encoding='utf-8').read())"
```
Ожидаем: пустой вывод (без исключений).

---

## Task 2: Цикл генерации в `main`

**Files:**
- Modify: `_scripts/build_xml.py:856–865` (блок `if args.davinci`)

**Step 1: Заменить блок `if args.davinci`**

Найти текущий блок (строки 856–865):
```python
    # FCPXML для DaVinci Resolve
    if args.davinci:
        fcpxml = build_fcpxml(clips, files, seq_settings, seq_name)
        xml_str = xml_to_string(fcpxml, doctype="fcpxml")

        out_path = assembly_dir / f"{project_name}_rough_cut.fcpxml"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml_str)

        print(f"Сохранено (FCPXML / DaVinci Resolve): {out_path}")
```

Заменить на:
```python
    # FCPXML для DaVinci Resolve
    if args.davinci:
        for relative, suffix in [(False, "_local"), (True, "")]:
            fcpxml = build_fcpxml(clips, files, seq_settings, seq_name, relative=relative)
            xml_str = xml_to_string(fcpxml, doctype="fcpxml")

            out_path = assembly_dir / f"{project_name}_rough_cut{suffix}.fcpxml"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(xml_str)

            label = ("абсолютные пути (локальный)" if suffix == "_local"
                     else "относительные пути (для zip)")
            print(f"Сохранено (FCPXML / DaVinci, {label}): {out_path}")
```

**Step 2: Sanity-check**

```bash
python -c "import ast; ast.parse(open('_scripts/build_xml.py', encoding='utf-8').read())"
```
Ожидаем: пустой вывод.

---

## Task 3: Ручная верификация на projects/tulips

**Files:** только чтение — `projects/tulips/`

**Step 1: Запустить сборку с `--davinci`**

```bash
python _scripts/build_xml.py projects/tulips --davinci
```

Ожидаем в stdout (среди прочего) две строки:
```
Сохранено (FCPXML / DaVinci, абсолютные пути (локальный)): projects/tulips/assembly/tulips_rough_cut_local.fcpxml
Сохранено (FCPXML / DaVinci, относительные пути (для zip)): projects/tulips/assembly/tulips_rough_cut.fcpxml
```

**Step 2: Проверить, что оба файла созданы**

```bash
ls projects/tulips/assembly/*.fcpxml
```
Ожидаем две строки: `tulips_rough_cut.fcpxml` и `tulips_rough_cut_local.fcpxml`.

**Step 3: Проверить pathurl/src в относительной версии**

```bash
grep -E 'src="[^"]+"' projects/tulips/assembly/tulips_rough_cut.fcpxml | head -5
```
Ожидаем `src="имя_файла.расширение"` без `file://`, без слэшей в начале — голые имена файлов.

**Step 4: Проверить pathurl/src в абсолютной версии**

```bash
grep -E 'src="[^"]+"' projects/tulips/assembly/tulips_rough_cut_local.fcpxml | head -5
```
Ожидаем `src="file:///C:/Users/Alex/Videos/factory/projects/tulips/..."` — с `file://`, абсолютным путём, пробелы в `%20`.

**Step 5: Проверить, что других различий между файлами нет**

```bash
diff projects/tulips/assembly/tulips_rough_cut.fcpxml projects/tulips/assembly/tulips_rough_cut_local.fcpxml | head -40
```
Ожидаем: различия **только** в строках с `src="..."` атрибутом ассетов. Любое другое расхождение — баг.

Если по любому из шагов 1–5 ожидание не выполнилось — НЕ переходить к Task 4. Откатиться, разобраться.

---

## Task 4: Обновить CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (раздел `### build_xml.py`)

**Step 1: Заменить описание `--davinci`**

Найти фрагмент в `CLAUDE.md`:
```
С флагом `--davinci` дополнительно генерирует `{name}_rough_cut.fcpxml` (FCPXML 1.9 для DaVinci Resolve).
```

Заменить на:
```
С флагом `--davinci` дополнительно генерирует `{name}_rough_cut.fcpxml` (относительные пути) и `{name}_rough_cut_local.fcpxml` (абсолютные пути) — FCPXML 1.9 для DaVinci Resolve.
```

---

## Task 5: Commit

**Step 1: Посмотреть статус**

```bash
git status
git diff --stat
```
Ожидаем изменения: `_scripts/build_xml.py`, `CLAUDE.md`. Артефакты `projects/tulips/assembly/*.fcpxml` — игнорируются (под gitignore).

**Step 2: Закоммитить**

```bash
git add _scripts/build_xml.py CLAUDE.md
git commit -m "feat(build_xml): для --davinci допфайл FCPXML с абсолютными путями

По аналогии с FCP 7 XML (_local.xml). Файл _local.fcpxml открывается
в DaVinci без релинка медиа.
"
```

**Step 3: Verify**

```bash
git log -1 --stat
```
Ожидаем коммит с двумя файлами в diff.
