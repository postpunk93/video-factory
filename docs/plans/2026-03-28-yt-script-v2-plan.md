# YouTube Script v2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create two new Claude Code skills (`/yt-analyze`, `/yt-write`) that produce YouTube scripts with integrated dramaturgy and self-review.

**Architecture:** Two user-facing skills + two support files. `/yt-analyze` reads materials + 13 best practice files, outputs `analysis.md`. `/yt-write` reads `analysis.md` + materials, writes script, then launches a review agent for 1-3 self-check iterations.

**Tech Stack:** Claude Code skills (markdown command files in `.claude/commands/`), CSV output

**Design doc:** `docs/plans/2026-03-28-yt-script-v2-design.md`

**Test project:** `projects/2026-03-thermobags` (has `raw/article.md` + `transcripts/*.transcript.txt`)

---

### Task 1: Write `yt-examples.md` — compact format examples

Support file referenced by `/yt-write`. Trimmed version of existing `youtube-script-examples.md` (~200-250 lines vs 390).

**Files:**
- Create: `.claude/commands/yt-examples.md`
- Reference: `.claude/commands/youtube-script-examples.md` (existing, source material)

**Step 1: Read existing examples file**

Read `.claude/commands/youtube-script-examples.md` in full.

**Step 2: Write `yt-examples.md`**

Keep (with examples — model gets confused without them):
- Самодостаточные vs несамодостаточные цитаты — алгоритм выбора + примеры хорошо/плохо
- Подводки к цитатам — обязательный тест + шаблоны + пример хорошо/плохо
- Распределение контента — пошаговая логика + антипаттерн пересказа + правильный вариант
- Смысловые мостики — правило 3 шагов + шаблоны + один пример
- Введение новой информации — правило + один пример (технический термин)

Remove (rules are clear enough without examples):
- Таблица цифр — example moves to `/yt-analyze` skill
- Ошибки с цифрами — reformulate as compact rules (no rounded examples)
- Диалоговые паттерны — just the banned phrases list, no examples

Add frontmatter:
```yaml
---
name: yt-examples
description: "Примеры формата для скилла /yt-write. НЕ вызывать напрямую."
---
```

Target: ~200-250 lines.

**Step 3: Verify line count and structure**

Run: `wc -l .claude/commands/yt-examples.md`
Expected: 200-250 lines

**Step 4: Commit**

```bash
git add .claude/commands/yt-examples.md
git commit -m "feat: yt-examples — компактные примеры формата для yt-write"
```

---

### Task 2: Write `yt-review-checklist.md` — review agent checklist

Support file loaded by the review agent inside `/yt-write`.

**Files:**
- Create: `.claude/commands/yt-review-checklist.md`
- Reference: `docs/plans/2026-03-28-yt-script-v2-design.md` (section "Агент-ревьюер")

**Step 1: Write the checklist file**

Structure:
```markdown
---
name: yt-review-checklist
description: "Чеклист для агента-ревьюера сценария. НЕ вызывать напрямую."
---

# Чеклист ревью сценария

## Как работать

1. Прочитать script_draft.csv и analysis.md
2. Пройти по 4 блокам чеклиста
3. Для каждой проблемы: описание + номер строки + исправление
4. Если проблемы есть — исправить CSV и пройти проверку заново
5. Максимум 3 прогона. Если после 3-го остались проблемы — сохранить список в script/review_notes.md

## Блок 1: Фактчекинг
[items from design]

## Блок 2: Драматургия
[items from design]

## Блок 3: Доступность
[items from design]

## Блок 4: Формат
[items from design]
```

Each checklist item should be actionable with a clear pass/fail criterion. Copy items from the design doc's "Чеклист — 4 блока" section, but make each item a concrete instruction (not just a statement).

Example transformation:
- Design: "Каждая цифра есть в таблице цифр из analysis.md"
- Checklist: "Выписать все числа из сценария. Для каждого — найти соответствие в таблице цифр из analysis.md. Если числа нет в таблице и оно не помечено [РАСЧЁТ] — это ошибка."

Add section on how to verify quotes:
- Read specific transcript files mentioned in analysis.md
- Search for the quote text
- Verify it's verbatim (exact match including errors, repetitions, filler words)

**Step 2: Commit**

```bash
git add .claude/commands/yt-review-checklist.md
git commit -m "feat: yt-review-checklist — чеклист для агента-ревьюера"
```

---

### Task 3: Write `yt-analyze.md` — analysis skill

Main skill file for `/yt-analyze`.

**Files:**
- Create: `.claude/commands/yt-analyze.md`
- Reference: `docs/plans/2026-03-28-yt-script-v2-design.md` (section "/yt-analyze — детали")
- Reference: `.claude/commands/youtube-script.md` (existing skill — reuse number table format, "Когда НЕ использовать" section)
- Reference: `docs/youtube-best-practices/*.md` (13 files — skill must instruct Claude to read them)

**Step 1: Write the skill file**

Frontmatter:
```yaml
---
name: yt-analyze
description: "Анализ материалов для YouTube-сценария. Использование: /yt-analyze <project_dir>. Требует: raw/article.md + transcripts/*.transcript.txt."
---
```

Structure:
```markdown
# Анализ материалов для YouTube-сценария

[Format description — same as existing skill]

## Когда НЕ использовать
[Same as existing skill]

## Шаг 0: Чтение материалов
- Read <project_dir>/raw/article.md
- Read <project_dir>/transcripts/*.transcript.txt
- If <project_dir> not provided — ask user

## Шаг 1: Таблица цифр
[From existing skill — golden rule, format, marking]
Include the number table example (moved from yt-examples)
Include compact rules for number errors (no examples, just rules):
- НЕ округлять без обоснования
- НЕ путать опт и розницу
- НЕ строить цепочку расчётов от неверного числа
- НЕ придумывать итоговые цифры

## Шаг 2: Фокус исследования
1. Денежный вопрос
2. Цепочка создания ценности (4-7 участников)
3. Место героя

## Шаг 3: Выбор драматургических приёмов
Read all 13 files in docs/youtube-best-practices/
Classify into always-on and situational
Select 0-2 situational practices with justification
Output: compact instructions per selected practice

## Шаг 4: Структура сценария
- 3-5 открывающих вопросов (open loops)
- Трёхактная структура with topics per act
- Where loops open and close

## Шаг 5: Ключевые цитаты
- 8-12 strongest quotes from transcripts
- For each: text, source file, timestamp, where in structure

## Шаг 6: Сохранение
Save to <project_dir>/script/analysis.md
Show to user, wait for confirmation

⛔ НЕ ПИСАТЬ СЦЕНАРИЙ. Для написания → /yt-write
```

Key details:
- Step 3 must list all 13 file paths explicitly for Claude to read
- The "always-on" practices should be summarized as compact rules (not "read file X"), since they'll be embedded in analysis.md for the writer
- The "situational" practices need selection criteria from the best practice files

**Step 2: Verify skill loads correctly**

Run in Claude Code: `/yt-analyze` (without project_dir) — should prompt for project_dir.

**Step 3: Commit**

```bash
git add .claude/commands/yt-analyze.md
git commit -m "feat: /yt-analyze — скилл анализа материалов с выбором драматургических приёмов"
```

---

### Task 4: Write `yt-write.md` — writing skill (orchestrator)

Main skill file for `/yt-write`. Orchestrates: architecture → writing → review agent.

**Files:**
- Create: `.claude/commands/yt-write.md`
- Reference: `docs/plans/2026-03-28-yt-script-v2-design.md` (sections "Фаза 1-3")
- Reference: `.claude/commands/yt-examples.md` (created in Task 1 — skill must load it)
- Reference: `.claude/commands/yt-review-checklist.md` (created in Task 2 — review agent loads it)

**Step 1: Write the skill file**

Frontmatter:
```yaml
---
name: yt-write
description: "Написание YouTube-сценария по анализу. Использование: /yt-write <project_dir>. Требует: script/analysis.md (от /yt-analyze)."
---
```

Structure:
```markdown
# Написание YouTube-сценария

## Предусловие
- Проверить, что <project_dir>/script/analysis.md существует
- Если нет — сообщить: сначала запустите /yt-analyze

## Шаг 0: Загрузка контекста
Read:
- <project_dir>/script/analysis.md
- <project_dir>/raw/article.md
- <project_dir>/transcripts/*.transcript.txt
- .claude/commands/yt-examples.md (примеры формата)

## Шаг 1: Архитектура сценария
[Segment map — 6-10 segments, each with: strategy, technique, quote, Slava thesis, open loops, visual]
Do NOT write full text yet — only the map.

## Шаг 2: Написание сценария
[All writing rules from design: quotes, distribution, accessibility, language, markup]
Write full script following the architecture.

## Шаг 3: Сохранение
Save to <project_dir>/script/script_draft.csv
Format: 4 columns — Слава,Таймкоды,Герой,Таймкоды
Columns 2 and 4 — empty.

## Шаг 4: Ревью
Launch review agent (Agent tool) with prompt:
- Read <project_dir>/script/script_draft.csv
- Read <project_dir>/script/analysis.md
- Read .claude/commands/yt-review-checklist.md
- Follow checklist instructions
- If issues found: fix CSV and re-check (max 3 rounds)
- Save review_notes.md if unresolved issues remain

## Готово
Report: what was written, how many review rounds, any unresolved issues.
```

Key details:
- Шаг 2 must include ALL writing rules inline (not by reference) — this is the core of the skill
- The review agent prompt in Шаг 4 must be self-contained — agent gets fresh context
- Include the yt-examples.md loading instruction explicitly
- Монтажная разметка rules: [B-ROLL], [ГРАФИКА], [МУЗЫКА], [ПАУЗА], [INTERRUPT]

**Step 2: Commit**

```bash
git add .claude/commands/yt-write.md
git commit -m "feat: /yt-write — скилл написания сценария с агентом-ревьюером"
```

---

### Task 5: Test `/yt-analyze` on thermobags project

**Files:**
- Test input: `projects/2026-03-thermobags/raw/article.md` + `projects/2026-03-thermobags/transcripts/*.transcript.txt`
- Expected output: `projects/2026-03-thermobags/script/analysis.md`

**Step 1: Back up existing script files**

The project already has `script/script_draft.csv` and other files. Don't overwrite them.
Check if `script/analysis.md` already exists — if yes, rename to `analysis_old.md`.

**Step 2: Run `/yt-analyze projects/2026-03-thermobags`**

Verify output contains:
- [ ] Таблица цифр — all numbers from materials with sources
- [ ] Денежный вопрос — not a topic description
- [ ] Цепочка ценности — 4-7 participants
- [ ] Выбранные практики — always-on listed + 0-2 situational with justification
- [ ] Трёхактная структура — topics per act, loop open/close points
- [ ] Ключевые цитаты — 8-12 quotes with source files

**Step 3: Verify numbers accuracy**

Spot-check 5 numbers from the table against actual article/transcript content.

**Step 4: Commit analysis.md if good**

```bash
git add projects/2026-03-thermobags/script/analysis.md
git commit -m "test: analysis.md для термосумок — тест /yt-analyze"
```

---

### Task 6: Test `/yt-write` on thermobags project

**Files:**
- Test input: `projects/2026-03-thermobags/script/analysis.md` (from Task 5)
- Expected output: `projects/2026-03-thermobags/script/script_draft.csv` (new version)

**Step 1: Rename existing draft**

```bash
mv projects/2026-03-thermobags/script/script_draft.csv projects/2026-03-thermobags/script/script_draft_v1.csv
```

**Step 2: Run `/yt-write projects/2026-03-thermobags`**

Verify output against checklist:
- [ ] CSV format correct (4 columns)
- [ ] Quotes are verbatim from transcripts
- [ ] ~70/30 hero/author ratio
- [ ] Hook in first segment with promise + stakes
- [ ] Open loops from analysis.md are opened and closed
- [ ] Semantic bridges between topic transitions
- [ ] Terms explained before use
- [ ] Numbers written as spoken words
- [ ] Монтажная разметка present ([B-ROLL], [МУЗЫКА], etc.)
- [ ] Review agent ran (check for review_notes.md or clean pass)

**Step 3: Compare with v1 draft**

Side-by-side comparison of `script_draft_v1.csv` (old skill) vs new `script_draft.csv`:
- Which has better hook?
- Which has better structure/pacing?
- Are the dramaturgy practices visible?
- Is the review agent's work visible (cleaner result)?

**Step 4: Report results to user**

Present findings for A/B comparison. User decides if quality is sufficient.
