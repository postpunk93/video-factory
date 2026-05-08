# Validate-loop в /match-timecodes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Добавить в скилл `/match-timecodes` автоматический validate-loop:
после сохранения `verified.json` зовём `match_timecodes.py validate`, на
проблемные строки запускаем fix-агента, мержим обратно — до 3 итераций или
до чистого результата. Цель — закрыть цикл, чтобы пайплайн не зависал на
оверлапах/within-word.

**Architecture:** Все правки в одном markdown-файле
`.claude/commands/match-timecodes.md`. Никакого нового Python-кода —
оркестрация через bash-вызовы существующего `match_timecodes.py validate` +
параллельные Explore-агенты. Дизайн утверждён в
`docs/plans/2026-05-08-validate-in-skill-design.md`.

**Tech Stack:** Markdown-инструкция для LLM-оркестратора (как остальные
скиллы проекта); bash для validate; Explore-агенты для починки; JSON
read/write через стандартный инструментарий скилла. Никаких новых
зависимостей.

---

## Структура

- Tasks 1–5: добавить шаги 6.5–6.9 в скилл (validate runner, payload,
  fix-агенты, merge, iteration control)
- Task 6: обновить шаг 7 (final summary) с учётом результата валидации
- Task 7: обновить раздел «Обработка ошибок» новыми сценариями (пп. 1–7
  из дизайна)
- Tasks 8–9: E2E на термосумках + регрессия на чистом проекте
- Task 10: фиксация результатов в memory + обновление CLAUDE.md

Особенность: скилл — markdown-инструкция, классический TDD-цикл «failing
test → impl → pass» неприменим. Вместо него каждый task завершается
sanity-проверкой (markdown остаётся валидным; смысловые блоки на месте) +
коммитом. E2E-проверка реальных эффектов — в Tasks 8–9.

---

### Task 1: Шаг 6.5 — Validate runner + iteration controller

**Files:**
- Modify: `.claude/commands/match-timecodes.md` — добавить новый раздел
  после строки 148 (конец шага 6) и перед существующим шагом 7.

**Step 1: Добавить раздел в скилл**

Вставить после строки 148 (после фразы про нормализацию `chosen` →
`chosen_parts`) новый блок:

````markdown

## 6.5. Validate verified.json и fix-loop

Запусти автоматический цикл проверки и точечной починки. Лимит — 3
итерации; после — эскалация.

**Инициализация:**

```python
iter = 0
prev_problem_set = None
```

**На каждой итерации (`iter` 1..3):**

```bash
python _scripts/match_timecodes.py validate {project_dir}
```

Команда пишет `{project_dir}/script/validation_report.json`:
```json
{
  "overlaps": [
    {"row_idx": 51, "file": "X.mov", "part_a": 0, "part_b": 1,
     "intersection_s": 0.10}
  ],
  "within_word": [
    {"row_idx": 8, "part_idx": 0, "edge": "end",
     "word": "курьерах", "word_start": 187.55, "word_end": 190.14,
     "part_value": 189.05}
  ],
  "thresholds": {"word_tol_ms": 50, "min_overlap_ms": 50}
}
```

Прочитай `validation_report.json`, собери:

```python
problem_set = set(o["row_idx"] for o in overlaps) \
            | set(w["row_idx"] for w in within_word)
```

**Стоп-условия:**

1. `problem_set` пустой — break, перейти к шагу 7. Validate чисто.
2. `iter == 3` — break, эскалировать (см. ниже).
3. `prev_problem_set is not None and len(problem_set) >= len(prev_problem_set)` —
   множество не уменьшилось → break, эскалировать (защита от тупика).

Если ни одно стоп-условие не сработало:

```
[Iter {iter}]: validate → {len(overlaps)} оверлапов + {len(within_word)} within-word → {len(problem_set)} проблемных строк
```

— и переходим к шагу 6.6.

**Эскалация** (печатается в stdout, скилл идёт к шагу 7):

```
⚠ После {iter} итераций фикса осталось {len(problem_set)} проблем:
  row 51: overlap parts 0+1 в X.mov (0.10s)
  row 8:  within-word 'курьерах' (end 189.05s в [187.55, 190.14])
  ...

Следующий шаг — переверифицировать вручную или принять как есть.
script.csv не будет сгенерирован snap'ом, пока есть оверлапы.
```
````

**Step 2: Sanity check**

Прочитай файл целиком, убедись что новый раздел вставлен после шага 6 и
перед шагом 7, синтаксис markdown не сломан, все code-блоки закрыты.

**Step 3: Commit**

```bash
git add .claude/commands/match-timecodes.md
git commit -m "feat(match-timecodes): шаг 6.5 — validate + iteration controller"
```

---

### Task 2: Шаг 6.6 — Row picker + context builder

**Files:**
- Modify: `.claude/commands/match-timecodes.md` — продолжить блок 6.5
  (добавить подраздел 6.6).

**Step 1: Добавить подраздел**

Вставить **сразу после Task 1**, перед началом шага 7:

````markdown

## 6.6. Подготовь fix-payload для проблемных строк

**Row picker.** Из `verified.json` выбери только записи с `row_idx in
problem_set`.

**Context builder.** Для каждой проблемной строки собери `payload`:

```python
{
  "row_idx": <int>,
  "text": <оригинальный текст из verified.json>,
  "current_chosen_parts": <текущий chosen_parts из verified.json>,
  "issues": [
    # из overlaps этой строки:
    {"type": "overlap", "parts": [a, b], "file": "...",
     "intersection_s": 0.10},
    # из within_word этой строки:
    {"type": "within_word", "part_idx": 0, "edge": "end",
     "word": "курьерах", "word_start": 187.55, "word_end": 190.14,
     "part_value": 189.05}
  ],
  "original_candidates": <запись этой row_idx из candidates.json>,
  "words_context": <фрагмент words_compact.txt ±10s вокруг текущих
                    границ chosen_parts, по правилу из шага 4>
}
```

`original_candidates` — это вся запись из `candidates.json` для этой строки
(включая `parts[]`, `unmatched`, `mode`, `status`). Агенту это нужно, чтобы
видеть альтернативы.

`words_context` строится так же, как в шаге 4: из соответствующего
`words_compact.txt` берутся все строки, у которых `START` попадает в
`[part.start - 10, part.end + 10]` для каждого парта в
`current_chosen_parts`.

Сохрани полный список `fix_payload[]` в памяти — он передаётся агенту в шаге 6.7.
````

**Step 2: Sanity check**

Файл — валидный markdown, шаги 6.5 → 6.6 → 7 идут в правильном порядке.

**Step 3: Commit**

```bash
git add .claude/commands/match-timecodes.md
git commit -m "feat(match-timecodes): шаг 6.6 — row picker + context builder"
```

---

### Task 3: Шаг 6.7 — Запуск fix-агентов

**Files:**
- Modify: `.claude/commands/match-timecodes.md` — добавить подраздел 6.7.

**Step 1: Добавить подраздел**

Вставить после Task 2:

````markdown

## 6.7. Запусти fix-агентов

**Чанкинг.** Если `len(fix_payload) <= 30` — 1 агент. Иначе — раздели на 2
примерно равные части и запусти 2 параллельных Explore-агента.

**Промпт fix-агенту:**

---

Ты исправляешь конкретные проблемные строки в `verified.json` для
сценария русскоязычного YouTube-видео. Проблемы детектированы
детерминированным валидатором (`match_timecodes.py validate`) — они **гарантированно** сломают таймлайн в DaVinci, если их не починить:

- **`overlap`** — два парта одной строки имеют пересекающиеся диапазоны в
  одном файле. На таймлайне это даст повтор аудио.
- **`within_word`** — `start` или `end` парта попадает внутрь слова.
  На таймлайне будет обрыв слова посередине.

### Что делать

Для каждой строки выбери **одно** из:

1. **Другой кандидат.** Посмотри `original_candidates` — если status был
   `multiple` или `multi_part`, выбери альтернативу, у которой нет этой
   проблемы.
2. **Сдвиг границы.** Если кандидат в `original_candidates` единственный
   или альтернативы тоже сломаны — сдвинь `start`/`end` к ближайшей
   word-boundary в `words_context`. Для within-word: к `word.end`
   проблемного слова или к `word.start` следующего. Для overlap: укороти
   один из перекрывающихся партов до конца word'а перед пересечением.
3. **Поиск заново.** Если ни (1), ни (2) не дают чистого результата —
   найди в `words_context` альтернативный кусок с тем же смыслом (например,
   повторение фразы дальше по записи).

Если ничего не помогает — верни `confidence: "low"` с пояснением в `note`,
эту строку validator во второй итерации найдёт снова, человек разберётся.

### Формат ответа

JSON-массив (ничего лишнего, можно обернуть в \```json ... \```):

```json
[
  {
    "row_idx": 51,
    "chosen_parts": [
      {"file": "X.mov", "start": 100.0, "end": 108.5, "text": "..."},
      {"file": "X.mov", "start": 110.0, "end": 115.0, "text": "..."}
    ],
    "confidence": "high",
    "note": "выбрал второго кандидата из original_candidates вместо первого"
  }
]
```

- `chosen_parts` — обновлённый массив (как в первичной верификации).
- `confidence`: `"high"` / `"low"` / `"missing"`.
- `note`: что именно сделал (выбрал альтернативу, сдвинул границу, нашёл
  заново). Краткая фраза.

### Проблемные строки

{вставь fix_payload[] из шага 6.6}

---
````

**Step 2: Sanity check**

Markdown валидный, code-блоки закрыты, escape для вложенных backticks (там,
где промпт сам показывает code-блок).

**Step 3: Commit**

```bash
git add .claude/commands/match-timecodes.md
git commit -m "feat(match-timecodes): шаг 6.7 — fix-агенты с прицельным промптом"
```

---

### Task 4: Шаг 6.8 — Result merger

**Files:**
- Modify: `.claude/commands/match-timecodes.md` — добавить подраздел 6.8.

**Step 1: Добавить подраздел**

````markdown

## 6.8. Смержи результаты в verified.json

**Парсинг ответов агентов.** Из каждого агента — JSON-массив. Если
вернулось обёрнуто в \```json ... \``` — сними обёртку и спарси. Объедини
ответы всех fix-агентов в один словарь `fixed: dict[row_idx, result]`.

**Обработка одной строки:**

- Если `row_idx` есть в `fixed`: возьми `chosen_parts`, `confidence`,
  `note` из ответа.
- Если `row_idx` нет в ответе агента (агент не вернул эту строку) — оставь
  её как была. Логируй в stdout: `⚠ row {row_idx}: агент не вернул фикс`.
- Если у агента невалидный JSON — пропусти эту строку, оставь как была,
  логируй: `⚠ row {row_idx}: невалидный JSON от fix-агента`.

**Запись.** Прочитай `verified.json` целиком, обнови **только** строки с
`row_idx in fixed`:

```python
for row in verified["rows"]:
    if row["row_idx"] in fixed:
        f = fixed[row["row_idx"]]
        row["chosen_parts"] = f["chosen_parts"]
        row["confidence"] = f.get("confidence", "low")
        row["note"] = f.get("note", "")
```

`speaker`, `col`, `text` — не трогай. Сохрани verified.json.

**Контрольная точка в stdout:**

```
[Iter {iter}]: fix-агент вернул {len(fixed)}/{len(fix_payload)} строк
```

**Подготовка к следующей итерации:**

```python
prev_problem_set = problem_set
iter += 1
```

И возврат к шагу 6.5 (новый прогон validate).
````

**Step 2: Sanity check**

Markdown валидный, ссылки 6.5/6.6/6.7/6.8 в правильных местах.

**Step 3: Commit**

```bash
git add .claude/commands/match-timecodes.md
git commit -m "feat(match-timecodes): шаг 6.8 — merger результатов в verified.json"
```

---

### Task 5: Обновить шаг 7 (final summary)

**Files:**
- Modify: `.claude/commands/match-timecodes.md` — старый шаг 7 (строки
  150–160) заменить на расширенный.

**Step 1: Заменить шаг 7**

Старый блок:

```markdown
## 7. Выведи итоговую сводку

```
✅ Верификация завершена. Результат: {project_dir}/script/verified.json

  high confidence:  N строк
  low confidence:   N строк
  missing:          N строк (если есть)

Следующий шаг: python _scripts/match_timecodes.py snap {project_dir}
```
```

Новый:

````markdown
## 7. Выведи итоговую сводку

```
✅ Верификация завершена. Результат: {project_dir}/script/verified.json

  high confidence:  N строк
  low confidence:   N строк
  missing:          N строк (если есть)

  Validate: {iter} итерации фикса
  Осталось проблем: {len(final_problem_set)}
    overlaps:    M
    within-word: K
```

**Если `final_problem_set` пустой:**

```
Следующий шаг: python _scripts/match_timecodes.py snap {project_dir}
```

**Если непустой:**

```
⚠ snap будет заблокирован preflight'ом из-за оверлапов.
  Опции:
    - переверифицировать вручную через /match-timecodes повторно;
    - смотреть проблемы в script/validation_report.json;
    - принять как есть и снять блокировку snap (не рекомендуется).
```
````

**Step 2: Sanity check**

Старый шаг 7 заменён, новый блок логически последователен с шагом 6.8.

**Step 3: Commit**

```bash
git add .claude/commands/match-timecodes.md
git commit -m "feat(match-timecodes): расширенный шаг 7 с итогами validate"
```

---

### Task 6: Расширить раздел «Обработка ошибок»

**Files:**
- Modify: `.claude/commands/match-timecodes.md` — раздел в конце файла
  (строки 162–166).

**Step 1: Добавить пункты**

В существующий список добавить:

```markdown
- **Validate / fix-loop:**
  - Если `validation_report.json` не записан после bash-вызова — фатал,
    останови скилл, выведи последние 20 строк stdout/stderr.
  - Если fix-агент вернул `chosen_parts: []` или `confidence: "missing"` —
    сохрани как есть; следующий iter подхватит, либо эскалация.
  - Если на iter=3 множество проблем больше, чем на iter=1 — печатай
    warning «фикс делает хуже» и эскалируй.
  - Если `candidates.json` исчез между шагами 1 и 6.5 — fail loudly,
    останови скилл.
  - Защита от зацикливания: если `len(problem_set) >= len(prev_problem_set)` —
    эскалируй, не дожидаясь iter=3.
```

**Step 2: Sanity check**

Раздел «Обработка ошибок» в конце файла, новые пункты про validate
дописаны после старых.

**Step 3: Commit**

```bash
git add .claude/commands/match-timecodes.md
git commit -m "docs(match-timecodes): error handling для validate-loop"
```

---

### Task 7: Sanity-pass всего скилла

**Files:** только чтение.

**Step 1: Прочитай скилл целиком**

`.claude/commands/match-timecodes.md`. Проверь:

- последовательность шагов: 1, 2, 3, 4, 5, 6, 6.5, 6.6, 6.7, 6.8, 7,
  «Обработка ошибок»;
- code-блоки закрыты (`)``;
- ссылки внутри текста (например, «по правилу из шага 4») указывают на
  существующие шаги;
- ничего не дублируется;
- не осталось забытых старых формулировок (типа «Следующий шаг: snap»
  без условия).

**Step 2: Если есть мелкие правки** — внеси и закоммить отдельно.

```bash
git add .claude/commands/match-timecodes.md
git commit -m "polish(match-timecodes): sanity-проверка после интеграции"
```

Если правок нет — пропусти коммит.

---

### Task 8: E2E на projects/2026-03-thermobags

**Files:** только запуск скилла.

**Step 1: Зафиксировать baseline**

```bash
cp projects/2026-03-thermobags/script/verified.json \
   projects/2026-03-thermobags/script/verified.before-validate-loop.json
python _scripts/match_timecodes.py validate projects/2026-03-thermobags
```

Ожидаемо: 3 overlaps + 34 within-word = 37 problem rows.
Сохрани числа.

**Step 2: Прогнать /match-timecodes на термосумках**

В Claude Code: `/match-timecodes projects/2026-03-thermobags`

Скилл:
- прочитает `candidates.json` и `verified.json` (он уже есть с прошлой
  верификации) — в зависимости от логики скилла, возможно перепрогонит
  всё с нуля. Это нормально.
- дойдёт до шага 6, перепишет `verified.json`,
- запустит шаг 6.5 (validate),
- увидит проблемы, прогонит fix-loop.

В stdout должно быть:

```
[Iter 1]: validate → 3 оверлапов + 34 within-word → 37 проблемных строк
[Iter 1]: fix-агент вернул N/37 строк
[Iter 2]: validate → ...
...
```

**Step 3: Проверить результат**

```bash
python _scripts/match_timecodes.py validate projects/2026-03-thermobags
```

Желаемое: exit 0, оверлапов 0. Within-word — допустимо несколько (не все
кейсы фиксимы переверификацией).

**Step 4: Зафиксировать наблюдения**

В commit-сообщение или новую memory-запись:
- сколько итераций ушло;
- сколько overlaps/within-word осталось после;
- какие строки эскалировались (если были);
- субъективная оценка качества фиксов (открыть полученный rough_cut в
  DaVinci и сравнить со старым `verified.before-validate-loop.json`).

**Step 5: Commit (если были code-правки в процессе)**

Если для прохода E2E пришлось править скилл — отдельные коммиты по сути
правок. Если всё прошло без правок — пропусти.

---

### Task 9: Регрессия на чистом проекте

**Files:** только запуск.

**Step 1: Выбрать чистый проект**

`projects/tulips`, `projects/2026-04-ferma`, `projects/2026-04-kogtetochki` —
все имеют `verified.json` с 0 оверлапами (проверено программно).

Бери любой, желательно `projects/2026-04-ferma` (поменьше).

**Step 2: Прогнать /match-timecodes**

```
/match-timecodes projects/2026-04-ferma
```

Скилл должен:
- дойти до шага 6 как обычно;
- на шаге 6.5 — validate exit 0 на первой итерации;
- сразу перейти к шагу 7 (без fix-агентов);
- финальная сводка должна показать «Validate: 1 итерация, 0 оверлапов».

**Step 3: Проверить, что happy path не сломался**

- `verified.json` — записан;
- никаких лишних fix-агентов не запускалось (по stdout);
- общее время скилла не сильно больше, чем было до интеграции (validate
  быстрый — миллисекунды).

**Step 4: Commit**

Если для прохода регрессии пришлось править скилл — отдельные коммиты.
Если всё чисто — пропусти.

---

### Task 10: Memory + CLAUDE.md

**Files:**
- Modify (опционально): `C:\Users\Alex\.claude\projects\C--Users-Alex-Videos-factory\memory\` —
  обновить или закрыть `project_verified_json_overlap_fix.md`.
- Modify: `CLAUDE.md` — упомянуть в секции `/match-timecodes`.

**Step 1: Обновить memory**

Файл `project_verified_json_overlap_fix.md` — задача закрыта. Либо удалить
запись из `MEMORY.md` и сам файл, либо переписать как «Закрыто 2026-05-08:
match_timecodes.py validate ловит детерминированно; /match-timecodes
авто-чинит fix-loop'ом до 3 итераций».

Использовать инструменты основной сессии (auto memory) — этот шаг
выполняется без bash, через инструменты Claude Code.

**Step 2: Обновить CLAUDE.md**

В секции `/match-timecodes` (если есть; иначе в `## Skills`) добавить
строку:

```markdown
Скилл сам прогоняет `validate` после агентной верификации и за 1–3
итерации точечно чинит проблемные строки fix-агентом. Если за 3
итерации остались проблемы — печатает их, snap позже заблокируется
preflight'ом.
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: validate-loop в /match-timecodes (CLAUDE.md)"
```

(Memory коммитов не требует — она не в репозитории.)

---

## Done criteria

- Скилл `.claude/commands/match-timecodes.md` имеет шаги 6.5–6.8 +
  обновлённый шаг 7 + расширенный «Обработка ошибок».
- E2E на термосумках: после прогона скилла `validate` exit 0 либо
  явная эскалация со списком оставшихся проблем.
- Регрессия на чистом проекте: 1 итерация validate (exit 0), без fix-агентов.
- CLAUDE.md описывает новое поведение скилла.
- Memory обновлена (задача `project_verified_json_overlap_fix.md` закрыта).
- Зависимости проекта не выросли (всё через bash + существующий
  `match_timecodes.py validate`).

## Не покрыто этим планом

- Этап A (timeline_view PNG) — отдельный дизайн, после прогона на
  термосумках. Если after Task 8 within-word warning'ов остаётся много и
  fix-loop их не чинит — берём timeline_view; если чинятся — не нужен.
- Грязный дубль / фалстарт — отдельная задача (вероятно, в основном
  скилле и/или в эвристике `find_candidates`).
- Удаление `cut_pauses.py`, замена WhisperX — отдельные разговоры.
