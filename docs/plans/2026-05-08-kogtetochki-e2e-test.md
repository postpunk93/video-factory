# E2E test пайплайна на kogtetochki — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Прогнать полный пайплайн `match_timecodes → build_xml` на проекте `2026-04-kogtetochki` и убедиться, что все стадии работают после фиксов 2026-04-28 и 2026-05-08.

**Architecture:** Линейное последовательное выполнение, гейт после каждой стадии. Halt → стоп, обсуждение. Бэкап старого state перед перезаписью для diff'а.

**Tech Stack:** Python 3, ffmpeg/ffprobe, `_scripts/match_timecodes.py`, `_scripts/build_xml.py`, скилл `/match-timecodes`.

**Дизайн:** `docs/plans/2026-05-08-kogtetochki-e2e-test-design.md`

---

### Task 1: Бэкап текущего state

**Files:**
- Create: `projects/2026-04-kogtetochki/script/before-rerun/`
- Copy: `projects/2026-04-kogtetochki/script/{candidates.json,verified.json,script.csv}`
- Copy: `projects/2026-04-kogtetochki/assembly/*.{xml,fcpxml}`

**Step 1: Создать каталог**

```powershell
New-Item -ItemType Directory -Path "projects/2026-04-kogtetochki/script/before-rerun" -Force
New-Item -ItemType Directory -Path "projects/2026-04-kogtetochki/script/before-rerun/assembly" -Force
```

**Step 2: Скопировать state**

```powershell
Copy-Item projects/2026-04-kogtetochki/script/candidates.json projects/2026-04-kogtetochki/script/before-rerun/
Copy-Item projects/2026-04-kogtetochki/script/verified.json projects/2026-04-kogtetochki/script/before-rerun/
Copy-Item projects/2026-04-kogtetochki/script/script.csv projects/2026-04-kogtetochki/script/before-rerun/
Copy-Item projects/2026-04-kogtetochki/assembly/*.xml projects/2026-04-kogtetochki/script/before-rerun/assembly/
Copy-Item projects/2026-04-kogtetochki/assembly/*.fcpxml projects/2026-04-kogtetochki/script/before-rerun/assembly/
```

**Step 3: Verify**

```powershell
Get-ChildItem projects/2026-04-kogtetochki/script/before-rerun/ -Recurse | Select-Object Name, Length
```

Expected: 7 файлов (candidates.json, verified.json, script.csv, 4 XML/FCPXML).

---

### Task 2: match_timecodes search

**Step 1: Запустить search**

```powershell
python _scripts/match_timecodes.py search projects/2026-04-kogtetochki/
```

Expected output: создаётся новый `candidates.json`, печатается распределение статусов (single/multiple/multi_part/partial/not_found).

**Step 2: Verify status distribution**

```powershell
python -c "import json; d=json.load(open('projects/2026-04-kogtetochki/script/candidates.json',encoding='utf8')); from collections import Counter; print(Counter(r['status'] for r in d['rows']))"
```

Expected: `not_found` ≤ 5. Если больше — halt, посмотреть что не нашлось.

---

### Task 3: /match-timecodes (агентная верификация + validate-loop)

**Step 1: Запустить скилл**

Invoke skill: `/match-timecodes projects/2026-04-kogtetochki/`

Скилл сам прогоняет верификацию + auto-fix loop по validate. До 3 итераций fix-агента.

**Step 2: Verify**

```powershell
python _scripts/match_timecodes.py validate projects/2026-04-kogtetochki/
```

Expected: exit 0, в `script/validation_report.json` нет проблем (`overlaps` и `within_word` — пустые списки).

```powershell
python -c "import json; d=json.load(open('projects/2026-04-kogtetochki/script/verified.json',encoding='utf8')); rows=d.get('rows',[]); missing=[r['index'] for r in rows if not r.get('chosen_parts')]; print('missing chosen_parts:', missing)"
```

Expected: пустой список (все строки имеют chosen_parts).

---

### Task 4: match_timecodes snap

**Step 1: Запустить snap**

```powershell
python _scripts/match_timecodes.py snap projects/2026-04-kogtetochki/
```

Expected: exit 0, обновлён `script/script.csv`.

**Step 2: Verify**

```powershell
$old = (Get-Content projects/2026-04-kogtetochki/script/before-rerun/script.csv).Count
$new = (Get-Content projects/2026-04-kogtetochki/script/script.csv).Count
"old: $old new: $new"
```

Expected: разница в 0-2 строки.

---

### Task 5: build_xml --davinci

**Step 1: Запустить**

```powershell
python _scripts/build_xml.py projects/2026-04-kogtetochki/ --davinci
```

Expected: 4 файла в `assembly/`.

**Step 2: Verify**

```powershell
Get-ChildItem projects/2026-04-kogtetochki/assembly/ | Select-Object Name, LastWriteTime
```

Expected: `2026-04-kogtetochki_rough_cut.xml`, `_rough_cut_local.xml`, `_rough_cut.fcpxml`, `_rough_cut_local.fcpxml` — все с свежим LastWriteTime.

```powershell
python -c "import xml.etree.ElementTree as ET; ET.parse('projects/2026-04-kogtetochki/assembly/2026-04-kogtetochki_rough_cut.xml'); ET.parse('projects/2026-04-kogtetochki/assembly/2026-04-kogtetochki_rough_cut.fcpxml'); print('xml ok')"
```

Expected: `xml ok`.

---

### Task 6: Diff с baseline и репорт

**Step 1: Diff script.csv**

```powershell
git --no-pager diff --no-index --stat projects/2026-04-kogtetochki/script/before-rerun/script.csv projects/2026-04-kogtetochki/script/script.csv
```

Распечатать общий объём изменений.

**Step 2: Сводный репорт**

Печатаю в чат:
- Status distribution из candidates.json
- Кол-во итераций validate-loop в /match-timecodes
- Diff line counts script.csv old/new
- Размер новых XML файлов
- Готовность к финальному визуальному осмотру

---

### Task 7: Визуальный осмотр в DaVinci (user)

Этот шаг выполняет пользователь.

**Файл:** `projects/2026-04-kogtetochki/assembly/2026-04-kogtetochki_rough_cut.fcpxml`

**Что проверить:**
- Нет offset'ов в начале клипов (фикс бага 1)
- Нет false-start'ов внутри клипов (фикс бага 3)
- Составные цитаты впритык, без гэпов
- V1 = Слава (voiceover), V2 = Герой (interview)
- Длительности клипов разумные

Пользователь говорит «ок» или показывает проблему — тогда halt и копать в скрипты.
