# Перенос пайплайна нарезки на машину сотрудника (Mac)

**Дата:** 2026-04-29
**Статус:** дизайн, готов к плану

## Задача

Сотрудник на своём Mac (Apple Silicon) принимает сырые материалы и сам выпускает черновую сборку для DaVinci Resolve. Я ухожу из петли «нарезка».

**Вход у сотрудника:** сырые видео (войсовер Славы + интервью героя) + готовый `script.csv` (текст реплик, без таймкодов).
**Выход:** `assembly/<имя>_rough_cut_local.fcpxml` для импорта в DaVinci. Дальнейшая работа в DaVinci — на сотруднике, обратно мне ничего не отдаёт.

**Граница ответственности:**
- Я: пишу скрипты, скилл `/match-timecodes`, скилл `/new-project`, обновляю репо. Сценарии пишу у себя через `/yt-write` и отдаю готовый `script.csv`.
- Сотрудник: устанавливает инструмент один раз, получает сценарий, запускает три фазы, импортирует FCPXML в DaVinci.

## Принятые ключевые решения

1. **Граница пайплайна B:** на машине сотрудника вся цепочка от сырых видео + готового CSV до FCPXML. Транскрибация и cut_pauses — у него, не у меня.
2. **Claude Code (вариант A):** сотрудник заводит свой Anthropic-аккаунт и подписку. Я даю репо со скиллами и скриптами.
3. **Mac Apple Silicon.** Win/Linux не поддерживаем.
4. **Гибридный setup:** детерминированный `setup.command` ставит всё через brew + uv + npm. Claude Code как fallback для траблшутинга («открой Claude Code, попроси: "почини, вот лог"»).
5. **Cut_pauses внутри пайплайна** на машине сотрудника (не у меня).
6. **Подход 2 — два скрипта `prepare.command` и `assemble.command`** с агентным шагом `/match-timecodes` между ними.
7. **Структура папок проекта создаётся через `/new-project` в Claude Code** (новый скилл).
8. **Отдельный приватный репо `factory-employee`** (вариант A) — чистая релизная версия, без черновиков основного `factory`.

## Архитектура — три фазы

```
[1] УСТАНОВКА (один раз)
    setup.command
      ├─ brew install ffmpeg, python@3.11, node, uv
      ├─ npm install -g @anthropic-ai/claude-code
      ├─ uv venv .venv && uv pip install -r requirements.txt
      ├─ прогрев моделей (faster-whisper large-v3 + whisperx aligner)
      └─ проверка .env (HF_TOKEN + согласие с лицензиями pyannote)

[2] ПОДГОТОВКА (каждый проект)
    /new-project 2026-05-myvideo                   # в Claude Code
    [сотрудник копирует видео и кладёт script.csv]
    prepare.command projects/2026-05-myvideo
      ├─ cut_pauses (raw → cuts)
      ├─ transcribe (cuts → transcripts)
      ├─ match_timecodes search → candidates.json
      └─ match_timecodes compact → words_compact.txt

[3] ВЕРИФИКАЦИЯ (каждый проект, агентно)
    /match-timecodes projects/2026-05-myvideo      # в Claude Code
      → verified.json

[4] СБОРКА (каждый проект)
    assemble.command projects/2026-05-myvideo
      ├─ match_timecodes snap → script.csv (с таймкодами)
      └─ build_xml --davinci → assembly/<имя>_rough_cut_local.fcpxml

→ Импорт в DaVinci, дальше работа в DaVinci.
```

**Принципы:**
- Идемпотентность: повторный запуск любой фазы пропускает уже сделанное.
- Логи всех фаз в `projects/<имя>/.factory.log` (одним файлом, с таймстемпами).
- Sequential, не параллельно: heavy tasks по одному (memory `feedback_no_parallel_heavy_tasks.md`).
- При ошибке любой фазы — печать инструкции «открой Claude Code, попроси `"почини, вот лог"`» (гибрид-fallback).

## Структура у сотрудника

```
factory-employee/                   ← отдельный приватный репо
  setup.command                     ← фаза [1]
  prepare.command                   ← фаза [2]
  assemble.command                  ← фаза [4]
  update.command                    ← периодически
  requirements.txt                  ← пин-версии Python deps
  .env.example                      ← шаблон HF_TOKEN
  README.md                         ← полная инструкция
  QUICKSTART.md                     ← короткий one-pager
  docs/setup/hf_token/*.png         ← скриншоты регистрации HF
  _scripts/                         ← cut_pauses.py, transcribe.py,
                                       match_timecodes.py, build_xml.py
                                       (зеркалятся из основного factory)
  .claude/skills/match-timecodes/   ← существующий скилл
  .claude/skills/new-project/       ← новый скилл, создаёт структуру проекта
  CLAUDE.md                         ← (опц.) кратко: что есть, как ставить
  .gitignore                        ← .venv/, models/, projects/, .env, *.log
  .venv/                            ← создаётся setup'ом
  models/                           ← кэш faster-whisper / pyannote
  projects/
    <имя>/
      raw/{voiceover,interviews}/   ← кладёт сотрудник
      script/script.csv             ← кладёт сотрудник
      cuts/, transcripts/, candidates.json, words_compact.txt
      verified.json                 ← /match-timecodes
      assembly/<имя>_rough_cut*.{xml,fcpxml}
      .factory.log                  ← логи всех фаз
```

**Минимум ручных действий сотрудника на новый проект:**

1. В Claude Code: `/new-project 2026-05-myvideo` → создана структура.
2. Скопировать видео в `raw/voiceover/` и `raw/interviews/`.
3. Положить присланный `script.csv` в `script/`.
4. Двойной клик `prepare.command` → выбрать проект из списка → ждать.
5. В Claude Code: `/match-timecodes projects/2026-05-myvideo`.
6. Двойной клик `assemble.command` → выбрать проект.
7. Импорт FCPXML в DaVinci.

## setup.command (фаза [1])

Идемпотентный bash. Каждый шаг проверяет «уже установлено?» и пропускает.

1. **Sanity:** `uname -m` = `arm64`. Иначе предупредить и выйти.
2. **Homebrew:** установить если нет; `brew update` если есть.
3. **ffmpeg + ffprobe:** `brew install ffmpeg`.
4. **Python 3.11:** `brew install python@3.11`. (whisperx устойчив на 3.10–3.11.)
5. **Node + Claude Code:** `brew install node && npm install -g @anthropic-ai/claude-code`. Печать: «открой Claude Code, авторизуйся через `/login`».
6. **uv:** `brew install uv`.
7. **venv + deps:** `uv venv .venv && uv pip install -r requirements.txt`.
8. **Прогрев моделей:** скачать `large-v3` для faster-whisper и whisperx-aligner в `models/` (~3 GB). Если уже есть — пропустить.
9. **HF_TOKEN:** проверить `.env`. Если нет — открыть README на разделе про HuggingFace и завершиться. После создания `.env` повторный setup доходит до конца. Валидация токена: `huggingface_hub.HfApi().whoami()` + тестовый запрос на `pyannote/speaker-diarization-3.1`. Если нет согласия с лицензией — печать «зайди на <url>, нажми Agree, перезапусти setup».
10. **Финал:** `setup_complete.flag`, печать next steps.

**Логи:** `setup.log` в корне репо.

## prepare.command (фаза [2])

**Аргументы:** `./prepare.command projects/<имя>`. Двойной клик из Finder → интерактивный prompt со списком папок в `projects/`, сотрудник вводит цифру.

1. **Sanity:** проверить `setup_complete.flag`, `.venv`, `.env` с `HF_TOKEN`, `projects/<имя>/raw/`, `projects/<имя>/script/script.csv`.
2. **Activate:** `source .venv/bin/activate`, экспорт `HF_TOKEN`.
3. **ETA-предупреждение:** `ffprobe` по всем `raw/*` → суммарная длительность → формула `~0.7×duration` cut_pauses + `~0.3×duration` transcribe на M-чипе. Печать «примерно N часов».
4. **cut_pauses войсовера:** `python _scripts/cut_pauses.py projects/<имя>/raw/voiceover --output projects/<имя>/cuts/voiceover --profile slava`. Идемпотентно по существующим `*_clean.mp4`.
5. **cut_pauses интервью:** то же с `--profile hero`.
6. **transcribe:** `python _scripts/transcribe.py projects/<имя>/cuts --speakers 2 --json --output projects/<имя>/transcripts`. Идемпотентно.
7. **match_timecodes search:** `python _scripts/match_timecodes.py search projects/<имя>` → `candidates.json`.
8. **match_timecodes compact:** `python _scripts/match_timecodes.py compact projects/<имя>` → `words_compact.txt`.
9. **Финал:** «Подготовка готова. Теперь в Claude Code: `/match-timecodes projects/<имя>`. После — двойной клик assemble.command.»

**Логи:** `projects/<имя>/.factory.log`. Каждый шаг — таймстемп старта/конца, exit code, last 5 строк stderr на ошибке.

**При падении:** печать «упало на шаге N. Лог: projects/<имя>/.factory.log. Открой Claude Code, попроси: "почини, вот лог"».

**В начале prepare** — тихий `git fetch`, проверка отставания от `origin/main`. Если отстаём — печать «есть обновление, запусти update.command (1 минута)». Не блокирует.

## assemble.command (фаза [4])

**Аргументы:** как у prepare.

1. **Sanity:** проверить `projects/<имя>/script/verified.json` непустой, `transcripts/` есть. Если `verified.json` нет — печать «сначала запусти `/match-timecodes projects/<имя>` в Claude Code».
2. **Activate:** `source .venv/bin/activate`.
3. **snap:** `python _scripts/match_timecodes.py snap projects/<имя>` → таймкоды в `script/script.csv`.
4. **build_xml --davinci:** `python _scripts/build_xml.py projects/<имя> --davinci` → 4 файла в `assembly/`.
5. **Финал:** «Готово. Импортируй в DaVinci: `projects/<имя>/assembly/<имя>_rough_cut_local.fcpxml`».

**Логи:** дописывает в существующий `.factory.log`.

## update.command (синхронизация)

1. `git fetch && git pull --rebase`.
2. Если изменился `requirements.txt` — `uv pip install -r requirements.txt` в существующий venv.
3. Если изменилась пин-версия Claude Code — `npm install -g @anthropic-ai/claude-code@X.Y.Z`.
4. Печать `git log --oneline -5` как «что нового».

**Триггер:** в начале `prepare.command` тихий `git fetch` + предупреждение, если `origin/main` ушёл вперёд. Не блокирует — сотрудник сам решает.

## HF_TOKEN

Раздел в `README.md` + 4–5 скриншотов в `docs/setup/hf_token/`:

1. Регистрация на huggingface.co.
2. `pyannote/segmentation-3.0` → «Agree and access repository».
3. `pyannote/speaker-diarization-3.1` → «Agree».
4. Settings → Access Tokens → New token (read).
5. `cp .env.example .env`, вставить токен.

`setup.command` валидирует токен и согласие с лицензиями отдельным проверочным запросом. При невалидности — ясное сообщение что и где сделать.

## QUICKSTART.md

Один экран:

```
# Quickstart

## Один раз
1. Двойной клик setup.command. Жди ~10 минут.
2. Открой Claude Code → /login → авторизация.

## Каждый новый проект
1. Claude Code: /new-project 2026-05-myvideo
2. Видео:
   raw/voiceover/   ← войсовер Славы
   raw/interviews/  ← интервью героя
3. Сценарий: положить script.csv в script/
4. Двойной клик prepare.command, выбрать проект (≈2-3 часа)
5. Claude Code: /match-timecodes projects/2026-05-myvideo
6. Двойной клик assemble.command, выбрать проект
7. Импорт в DaVinci: projects/<имя>/assembly/<имя>_rough_cut_local.fcpxml

## Что-то сломалось
Открой Claude Code в этой папке, попроси:
"посмотри projects/<имя>/.factory.log и почини"
```

## Скилл `/new-project`

Новый скилл `.claude/skills/new-project/SKILL.md`. Аргумент: имя проекта в формате `YYYY-MM-description`.

Создаёт:
- `projects/<имя>/raw/voiceover/`
- `projects/<имя>/raw/interviews/`
- `projects/<имя>/script/`
- `projects/<имя>/script/script.csv` — пустой шаблон с заголовками (синхронно с тем форматом, который читает `match_timecodes.py search`).
- `projects/<имя>/project.md` (опц.) — небольшой шаблон для заметок.

## Что НЕ делаем

- **Не делаем GUI / electron / py2app bundle.** Гибрид brew + uv + venv проще, контролируемее. PyInstaller на whisperx + torch — отдельный круг ада.
- **Не делаем телеметрию.** Никаких «логи отправляются ко мне». Гибрид-fallback через Claude Code достаточен.
- **Не делаем параллельную обработку.** Heavy tasks строго sequential.
- **Не делаем drag-and-drop через AppleScript.** Простой интерактивный prompt в bash достаточен.
- **Не делаем real-time progress в Claude Code.** `tqdm` в Терминале с цветами достаточен.
- **Не пересматриваем архитектуру существующих скриптов.** `cut_pauses.py`, `transcribe.py`, `match_timecodes.py`, `build_xml.py` оборачиваем как есть.
- **Не делаем CI / тест-фреймворк** на машине сотрудника. Smoke у меня и/или с сотрудником по видеосвязи.
- **Не делаем backup проектов.** Видео локально, ответственность сотрудника.
- **Не делаем Win/Linux.** Mac-only.
- **Не отдаёт результат обратно.** Сотрудник работает в DaVinci сам.

## Тестирование

**Уровень 1 — smoke setup на чистой машине.** Идеально — VM (UTM с macOS arm64) или с сотрудником по видеосвязи. Цель: setup отрабатывает за разумное время, все 10 шагов «зелёные», `setup.log` без ошибок.

**Уровень 2 — smoke прохода на маленьком проекте.** Тестовый проект (1 короткое интервью + короткий войсовер, ~5 минут общей длительности), `script.csv` с 3-5 репликами. Сотрудник проходит все 6 шагов QUICKSTART. FCPXML открывается в DaVinci.

**Уровень 3 — регрессия на боевом проекте.** `projects/2026-03-thermobags`: даю сотруднику raw/ + script.csv, он сам генерит cuts/, transcripts/, verified.json, FCPXML. Сравниваю с моим эталоном на Win — структура XML и порядок клипов должны совпадать. Допустимое расхождение: small float-noise в таймкодах из-за разной точности whisper/ffmpeg между платформами. Если расхождение существенное (>0.5с на клип) — копать в детерминированности whisper между платформами (отдельная задача).

## Затронутые файлы

**Новые в `factory-employee`:**
- `setup.command`, `prepare.command`, `assemble.command`, `update.command`
- `requirements.txt` с пин-версиями (faster-whisper, whisperx, torch arm64-MPS, pyannote-audio, tqdm, huggingface_hub, ffmpeg-python если нужно)
- `.env.example`
- `README.md` (полный)
- `QUICKSTART.md` (короткий)
- `docs/setup/hf_token/*.png`
- `.claude/skills/new-project/SKILL.md`
- `.gitignore` с `.venv/`, `models/`, `projects/`, `.env`, `setup.log`, `setup_complete.flag`, `.factory.log`
- `CLAUDE.md` для employee-репо (короткий, что это за репо и как им пользоваться — опц.)

**Зеркалятся из основного `factory`:**
- `_scripts/cut_pauses.py`, `_scripts/transcribe.py`, `_scripts/match_timecodes.py`, `_scripts/build_xml.py` — как есть, без изменений.
- `.claude/skills/match-timecodes/` — как есть.

**В основном `factory` создаётся новый скилл `/new-project`** (одновременно для меня и для зеркалирования в employee-репо).

## Открытые вопросы / риски

1. **Whisper-детерминированность между Win и Mac.** На разных платформах faster-whisper и whisperx могут давать слегка разные таймкоды слов. Если регрессия Уровня 3 покажет существенное расхождение — нужна отдельная задача про фиксацию seed и/или принятие float-noise как нормы.
2. **Apple Silicon + torch + MPS.** Не все версии torch стабильно работают с pyannote через MPS. В requirements.txt пин-версии нужно проверить на VM до отдачи сотруднику. На крайний случай — fallback на CPU (медленнее, но стабильнее).
3. **Зеркалирование `_scripts/`.** Лучше через `git subtree` (полная история, можно cherry-pick фиксы) или просто periodic copy при релизе. Решение по факту, не блокер дизайна.
4. **Размер моделей.** ~3 GB моделей + ~1 GB зависимостей torch + сами видео = быстро забьётся диск. README должен предупредить «свободно ≥50 GB на проект».
5. **`script.csv` формат.** Дизайн закладывает что сотрудник кладёт CSV в формате который ожидает `match_timecodes.py search`. Нужно проверить точный формат и зафиксировать пример в QUICKSTART.

---

Дизайн утверждён в брейншторме (2026-04-29). Следующий шаг — `superpowers:writing-plans` для разбивки на implementation tasks.
