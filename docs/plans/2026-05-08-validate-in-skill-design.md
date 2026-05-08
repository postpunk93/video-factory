# Дизайн — интеграция validate в скилл /match-timecodes

**Дата:** 2026-05-08
**Контекст:** только что смержена ветка `fix/verified-overlap-cause` —
`match_timecodes.py validate` детектит word-overlap'ы и within-word boundary
в `verified.json`, `cmd_snap` блокируется на оверлапах. Скилл
`/match-timecodes` (агентная верификация, проход 2) про validate ничего не
знает; цикл «найти проблемы → исправить → проверить» не замкнут.

## Зачем

Сейчас validator работает как safety net: блокирует snap, чтобы сломанный
`verified.json` не утёк в `script.csv`/FCPXML/DaVinci. Но если оверлапы или
within-word есть, пайплайн **встаёт**. Чинить надо либо вручную (читать
отчёт, идти в `/match-timecodes` повторно, переверифицировать конкретные
строки), либо никак (работаешь с тем что есть и слышишь повтор/обрыв в DaVinci).

Цель — замкнуть цикл: после агентной верификации скилл сам зовёт validate,
видит проблемы, точечно подаёт их fix-агенту, повторяет до чистого результата
или до лимита итераций. Человеку остаётся только эскалированные случаи.

## Цели

1. После шага «сохранили `verified.json`» автоматически прогнать validate.
2. Если проблем нет — выйти как раньше.
3. Если есть — собрать ровно проблемные `row_idx`, передать fix-агенту с
   прицельным контекстом (расшифровка проблемы + альтернативы из
   `candidates.json` + `words_compact.txt` ±10s), смержить ответ обратно в
   `verified.json` (только этих строк), повторить validate.
4. Лимит — 3 итерации. После — печатаем оставшиеся проблемы пользователю.
5. Никаких новых артефактов вне скилла; всё через существующий
   `match_timecodes.py validate` + bash + Explore-агенты, как сейчас.

## Не-цели

- Не чиним within-word/overlap детерминированно (snap к word boundary,
  midpoint и т.п.) — сознательно оставляем за человеком/агентом, как в
  принципе video-use «verify, don't auto-fix».
- Не меняем формат `verified.json`, `validation_report.json`,
  `candidates.json` — все артефакты как есть.
- Не пишем новый Python-код для скилла; оркестрация целиком в markdown
  через bash и под-агентов (стиль остальных скиллов проекта).
- Не трогаем главный `/match-timecodes` flow для строк, которых validate
  не флагнул — happy path должен остаться без регрессий.
- Удаление `cut_pauses.py`, замена WhisperX на Scribe, timeline_view (этап A
  из video-use ideas) — отдельные разговоры.

## Архитектура

```
[существующие шаги 1-6 скилла]
       ↓
   verified.json
       ↓
6.5  bash: match_timecodes.py validate <project>
       ↓
   читаем validation_report.json
       ↓
   ┌── чисто? → шаг 7 (final summary)
   │
   └── есть проблемы?
           ↓
       выбираем проблемные row_idx
           ↓
       готовим контекст: проблема + candidates + ±10s words_compact
           ↓
       1-2 параллельных Explore-агентов (1 если ≤30 строк, 2 если >30)
           ↓
       парсим, мержим chosen_parts только этих строк в verified.json
           ↓
       iter += 1; if iter < 3 → goto 6.5
                  else → escalate (печатаем остатки, идём в шаг 7)
```

Никаких новых файлов; вся логика в `.claude/commands/match-timecodes.md`.

## Компоненты (логические блоки скилла)

1. **Validate runner** — `python _scripts/match_timecodes.py validate <project>`.
   Выход — exit code (0/1) + `script/validation_report.json`.

2. **Report parser** — читает `validation_report.json`, собирает
   `set(row_idx)` из `overlaps[]` и `within_word[]`.

3. **Row picker** — выбирает из `verified.json` именно эти `row_idx`.
   К каждой добавляет человекочитаемое описание проблемы:
   - overlap: «парты 0+1 пересекаются на 0.10s в файле X.mov»,
   - within-word: «end парта 0 (189.05s) попадает внутрь слова 'курьерах'
     (187.55–190.14)».

4. **Context builder** — для каждой проблемной строки собирает payload:
   - `text` (оригинальный сценарий),
   - `current_chosen_parts` (что выбрал предыдущий агент),
   - `issues[]` (расшифровка из validation_report),
   - `original_candidates` (из `candidates.json` — все альтернативы со
     `status`),
   - `words_context` — фрагмент `words_compact.txt` ±10s вокруг текущих
     границ, по тому же правилу что в шаге 4 основного скилла.

5. **Fix agent(s)** — 1 Explore-агент при ≤30 проблемных строках, 2 при
   >30 (рамка та же что в шаге 4). Промпт явно указывает: «исправь только
   эти строки, проблемы детерминированно подтверждены, можешь выбрать
   другого кандидата, сдвинуть границу к word boundary, или найти новый
   таймкод; верни тот же формат `chosen_parts[]`».

6. **Result merger** — парсит JSON-ответы, **обновляет в `verified.json`
   только проблемные `row_idx`**, не трогая остальные. Сохраняет файл.

7. **Iteration controller** — счётчик 1..3. После каждого мержа повторно
   зовёт validate. Стоп-условия:
   - validate exit 0 (чисто) → break, шаг 7,
   - iter == 3 → break, escalate,
   - множество проблемных не уменьшилось vs предыдущей итерации → break,
     escalate (защита от тупика).

## Dataflow (детально)

```
verified.json (после шага 6)
    │
    ▼ ITERATION 1..3
    │
    │  bash: match_timecodes.py validate {project}
    │   stdout → пользователю (что сломано)
    │   script/validation_report.json:
    │     {overlaps:[…], within_word:[…],
    │      thresholds:{word_tol_ms, min_overlap_ms}}
    │
    │  parse → set(row_idx) проблемных
    │  if empty → break
    │
    │  build fix_payload[]:
    │    for row in problem_rows:
    │      {
    │        row_idx,
    │        text: original_script_text,
    │        current_chosen_parts: [...],
    │        issues: [
    │          {type:"overlap", parts:[0,1],
    │           file:"X.mov", intersection_s:0.1},
    │          {type:"within_word", part_idx:0,
    │           edge:"end", word:"курьерах",
    │           word_start:187.55, word_end:190.14,
    │           part_value:189.05}
    │        ],
    │        original_candidates: candidates.json[row].parts,
    │        words_context: "...words_compact ±10s..."
    │      }
    │
    │  chunk → 1 fix-агент или 2 (порог 30)
    │  parallel Explore agents → JSON of fixed rows
    │
    │  parse + merge into verified.json (только проблемные row_idx)
    │
    │  iter += 1
    ▼
escalate or step 7
```

**Что меняется в `verified.json`:** только поле `chosen_parts` для проблемных
`row_idx`. Все остальные строки не трогаются — иначе агент может неосознанно
«починить» хорошие.

**Что фиксируется на каждой итерации:** список проблемных строк выбирается
заново — после фикса агент мог сломать что-то ещё (новый кандидат тоже с
оверлапом).

## Error handling

1. **Fix-агент вернул невалидный JSON** — логируем в stdout, пропускаем эту
   строку (не мержим), продолжаем итерацию с другими. Если все строки в
   чанке невалидны — итерация без прогресса, iter инкрементируем как обычно.

2. **Fix-агент вернул `chosen_parts: []` / `confidence: "missing"`** —
   сохраняем как есть; snap позже эту строку пропустит. Не баг.

3. **После фикса проблем стало больше** — валидно, следующий iter поймает.
   Если на iter=3 проблем больше, чем на iter=1 — печатаем warning «фикс
   делает хуже» и эскалируем.

4. **`validation_report.json` не записан** — фатал. Печатаем последние 20
   строк stdout/stderr, останавливаем скилл.

5. **`candidates.json` отсутствует** — fail loudly. (Шаг 1 уже проверяет;
   на этапе fix-loop файл не должен исчезать.)

6. **Нет word-boundary-friendly альтернативы** — например, единственный
   кандидат сам с within-word. Агент возвращает `confidence: "low"` с
   `note` — сохраняем, validator продолжает флагать, после iter=3
   эскалация. Норма для пограничных случаев.

7. **Зацикливание на одних и тех же строках** — защита: `set` проблемных
   `row_idx` сравнивается с предыдущей итерацией. Если не уменьшается —
   эскалируем не дожидаясь iter=3.

## Testing

Скилл — markdown-инструкция, юнит-тесты не применимы напрямую. Что
проверяем:

1. **E2E на `projects/2026-03-thermobags`** — лучший живой набор: 3 overlap
   + 34 within-word.
   - До: `validate` exit 1 с этими цифрами.
   - После прогона скилла: `validate` exit 0 либо явная эскалация со
     списком нерешённых.
   - Замер: сколько итераций потребовалось.

2. **Контрольные точки в stdout** для наблюдения в реальном времени:
   ```
   Iter 1: validate → 3 overlaps + 34 within-word → 37 problem rows
   Iter 1: fix-агент вернул чинит N/37
   Iter 2: validate → X overlaps + Y within-word
   ...
   ```

3. **Регрессия happy path** — на чистом проекте (`projects/tulips`,
   `projects/2026-04-ferma`) скилл должен быстро отстреляться: validate exit
   0 на первой итерации → break, никаких fix-агентов.

4. **Не покрываем тестами:**
   - Качество фиксов — вкусовое, проверяется ушами в DaVinci.
   - Зацикливание на сложных кейсах — сложно симулировать;
     защита `iter ≤ 3` + «множество не уменьшилось» снимает риск
     бесконечного цикла.

5. **Юнит-тесты — если в плане появится Python helper** (например,
   `merge_chosen_parts(verified, fixed_rows)`) — добавим по образцу
   `test_validate.py`. Сейчас helper не запланирован.

## Что НЕ покрыто этим дизайном

- **Этап A (timeline_view PNG)** — отдельный дизайн. Решение брать или нет —
  после прогона этой интеграции на термосумках. Если 34 within-word
  починятся переверификацией — timeline_view не нужен; если останется
  значимое количество эскалированных кейсов — берём.
- **Грязный дубль / фалстарт** — отдельная проблема, validator её не ловит
  и эта интеграция тоже. Чинить в `find_candidates` или промпте основного
  match-timecodes-агента (эвристика «при равных кандидатах предпочесть тот,
  у которого больше тишина перед start»).
- **Удаление `cut_pauses.py`**, замена WhisperX — отдельно.
