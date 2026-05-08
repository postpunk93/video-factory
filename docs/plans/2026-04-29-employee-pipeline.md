# Перенос пайплайна нарезки на машину сотрудника — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Создать отдельный приватный репозиторий `factory-employee` с тремя командными скриптами и документацией, чтобы сотрудник на Mac мог собрать FCPXML для DaVinci из сырых видео + готового CSV-сценария, без моего участия.

**Architecture:** Три фазы (`setup.command` → `prepare.command` → `/match-timecodes` в Claude Code → `assemble.command`). Гибрид: детерминированные bash-скрипты + Claude Code как fallback для траблшутинга. Существующие Python-скрипты из основного `factory` копируются в новый репо как есть.

**Tech Stack:** bash, Homebrew, uv, Python 3.11, faster-whisper, whisperx, pyannote-audio, Claude Code (npm CLI), git.

**Дизайн:** `docs/plans/2026-04-29-employee-pipeline-design.md`

---

## Контекст для исполнителя

В этом проекте нет тестового фреймворка. Верификация делается:

1. **Smoke-тесты** через прямые вызовы скриптов на синтетических/реальных данных.
2. **Регрессия** на boilerplate-проекте `projects/2026-03-thermobags` — сравнение финального FCPXML с эталоном Win-пайплайна.
3. **Манульный smoke setup** на чистой macOS Apple Silicon машине (VM UTM или с сотрудником по видеосвязи).

**Где работаем.** Новый репо `factory-employee` создаётся локально в `C:\Users\Alex\Videos\factory-employee\` (рядом с основным `factory`), потом push в новый приватный github repo. Все Python-скрипты копируются из основного `factory/_scripts/`. Скилл `/match-timecodes` копируется из `factory/.claude/skills/match-timecodes/`.

**Платформа исполнителя.** Я (исполнитель) на Windows. Мac-only части (bash скрипты с Homebrew, .command файлы, `chmod +x`) проверяю синтаксисом и логикой, реальный smoke — отдельным шагом с сотрудником или на UTM VM.

**Пин-версии в `requirements.txt`** — на момент написания дизайна я не на Mac и не могу проверить точные версии. В плане использую разумные defaults; перед отдачей сотруднику Task 12 валидирует их на VM/живой машине, при необходимости корректирует.

---

## Task 1: Создать новый репо `factory-employee` и базовый каркас

**Files:**
- Create: `C:\Users\Alex\Videos\factory-employee\.gitignore`
- Create: `C:\Users\Alex\Videos\factory-employee\.env.example`
- Create: `C:\Users\Alex\Videos\factory-employee\README.md` (skeleton — наполнение в Task 10)
- Create: `C:\Users\Alex\Videos\factory-employee\CLAUDE.md` (короткий — что это за репо)

**Step 1: Создать папку и инициализировать git**

```bash
mkdir C:/Users/Alex/Videos/factory-employee
cd C:/Users/Alex/Videos/factory-employee
git init
```

Ожидаемое: создана папка с пустым `.git/`.

**Step 2: Написать `.gitignore`**

```gitignore
# Python venv и кэш моделей — большие, не коммитить
.venv/
models/
__pycache__/
*.pyc

# Локальные настройки сотрудника
.env
setup_complete.flag

# Логи
setup.log
*.log

# Артефакты проектов (видео, транскрипты, сборки)
projects/

# OS
.DS_Store

# Claude Code
.claude/scheduled_tasks.lock
.claude/projects/
```

**Step 3: Написать `.env.example`**

```bash
# (Опционально) HuggingFace token для pyannote — нужен ТОЛЬКО если запускаешь
# transcribe.py с флагом --diarize (по умолчанию диаризация выключена и не
# используется в основном пайплайне). Если флаг тебе не нужен — оставь как есть
# или удали .env.
#
# Получи на https://huggingface.co/settings/tokens (read access).
# Перед этим зайди на pyannote/segmentation-3.0 и pyannote/speaker-diarization-3.1,
# нажми "Agree and access repository" на каждом.
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Step 4: Skeleton `README.md`**

```markdown
# Factory Employee

Пайплайн нарезки видео для YouTube-интервью на Mac.

См. `QUICKSTART.md` для быстрого старта.

(Полное наполнение в Task 10.)
```

**Step 5: Короткий `CLAUDE.md`**

```markdown
# CLAUDE.md

Это релизная копия инструмента нарезки для сотрудника. Работает на Mac (Apple Silicon).

**Что лежит:**
- `setup.command` — установка (один раз).
- `prepare.command` — фаза 1: cut_pauses + transcribe + match search.
- `assemble.command` — фаза 3: snap + build_xml.
- `update.command` — синхронизация с git.
- `_scripts/*.py` — копии скриптов из основного `factory`.
- `.claude/commands/match-timecodes.md` — команда для Claude Code (агентная верификация таймкодов).

## Структура нового проекта

Когда сотрудник просит «создай структуру для нового проекта 2026-05-...», создаётся:

```
projects/<имя>/
  raw/
    voiceover/    ← начитка Славы (видеофайлы .mp4/.mov/.mkv/.avi)
    interviews/   ← записи героя (видеофайлы)
  script/
    script.csv    ← пустой шаблон с заголовками
```

Формат `script.csv`: 4 колонки `Слава`, `Слава timecode`, `Герой`, `Герой timecode`. Сотрудник заполняет реплики в `Слава` и `Герой` (одна реплика на строку, в той же row). Колонки таймкодов оставлять пустыми — заполняются автоматически фазой `assemble.command`. Пустой шаблон:

```csv
Слава,Слава timecode,Герой,Герой timecode
```

**Что НЕ лежит:** ничего из основного `factory`, кроме копий выше.

При обновлении скриптов в основном `factory` синхронизируй сюда вручную (см. дизайн `factory/docs/plans/2026-04-29-employee-pipeline-design.md` — внутренний design doc, у сотрудника его нет).
```

**Step 6: Initial commit**

```bash
cd C:/Users/Alex/Videos/factory-employee
git add .gitignore .env.example README.md CLAUDE.md
git commit -m "init: skeleton factory-employee repo

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Ожидаемое: один коммит, четыре файла.

---

## Task 2: Скопировать `_scripts/` и скилл `/match-timecodes` из основного factory

**Files:**
- Copy: `C:\Users\Alex\Videos\factory\_scripts\*.py` → `C:\Users\Alex\Videos\factory-employee\_scripts\`
- Copy: `C:\Users\Alex\Videos\factory\.claude\skills\match-timecodes\` → `C:\Users\Alex\Videos\factory-employee\.claude\skills\match-timecodes\`

**Step 1: Скопировать скрипты**

```bash
mkdir -p C:/Users/Alex/Videos/factory-employee/_scripts
cp C:/Users/Alex/Videos/factory/_scripts/cut_pauses.py C:/Users/Alex/Videos/factory-employee/_scripts/
cp C:/Users/Alex/Videos/factory/_scripts/transcribe.py C:/Users/Alex/Videos/factory-employee/_scripts/
cp C:/Users/Alex/Videos/factory/_scripts/match_timecodes.py C:/Users/Alex/Videos/factory-employee/_scripts/
cp C:/Users/Alex/Videos/factory/_scripts/build_xml.py C:/Users/Alex/Videos/factory-employee/_scripts/
```

Если в `_scripts/` есть другие файлы (helpers, constants) — скопировать их тоже. Проверка:

```bash
ls C:/Users/Alex/Videos/factory/_scripts/
```

**Step 2: Скопировать скилл `/match-timecodes`**

```bash
mkdir -p C:/Users/Alex/Videos/factory-employee/.claude/skills/
cp -r C:/Users/Alex/Videos/factory/.claude/skills/match-timecodes/ C:/Users/Alex/Videos/factory-employee/.claude/skills/
```

**Step 3: Проверить что всё на месте**

```bash
ls C:/Users/Alex/Videos/factory-employee/_scripts/
ls C:/Users/Alex/Videos/factory-employee/.claude/skills/match-timecodes/
```

Ожидаемое: 4 (или больше) `.py` файла в `_scripts/`; в `match-timecodes/` — содержимое скилла (SKILL.md и доп. файлы если есть).

**Step 4: Commit**

```bash
cd C:/Users/Alex/Videos/factory-employee
git add _scripts/ .claude/
git commit -m "chore: скопировать _scripts и скилл match-timecodes из factory

Source: factory @ <hash основного factory HEAD>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Замени `<hash>` на актуальный хеш HEAD основного `factory` через `cd C:/Users/Alex/Videos/factory && git rev-parse --short HEAD`. Это даёт трекинг от какого момента mirror был сделан.

---

## Task 3: `requirements.txt` с пин-версиями

**Files:**
- Create: `C:\Users\Alex\Videos\factory-employee\requirements.txt`

**Step 1: Написать requirements.txt**

```
# Pinned versions for Mac Apple Silicon (M1/M2/M3).
# Tested on Python 3.11.
# Update Task 12 (smoke на VM) подтверждает совместимость.

# Whisper и aligner
faster-whisper==1.0.3
whisperx==3.1.5

# Torch с MPS-поддержкой для Apple Silicon
torch==2.2.2
torchaudio==2.2.2

# Диаризация
pyannote.audio==3.1.1

# HuggingFace clients
huggingface-hub==0.23.0

# Прогресс-бары
tqdm==4.66.4

# YAML/CSV — обычно из stdlib, но если cut_pauses.py нужны — добавить
```

**Замечания:**
- `torch==2.2.2` — последняя стабильная для arm64 + MPS на момент написания. На Mac она ставится из обычного pypi (без `--extra-index-url`).
- Версии могут устареть. Task 12 валидирует, при необходимости корректирует.

**Step 2: Commit**

```bash
cd C:/Users/Alex/Videos/factory-employee
git add requirements.txt
git commit -m "chore: pin Python deps для Mac arm64 + MPS

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `setup.command`

**Files:**
- Create: `C:\Users\Alex\Videos\factory-employee\setup.command`

**Step 1: Написать setup.command**

Ключевые соображения:
- Bash, shebang `#!/bin/bash`.
- `set -e` для строгой остановки при ошибке.
- Каждый шаг с проверкой «уже сделано?».
- Все вывод в Терминал и в `setup.log`.
- В конце `chmod +x` через права в git (см. Step 4).

```bash
#!/bin/bash
# setup.command — установка инструмента нарезки на Mac Apple Silicon.
# Идемпотентный: можно запускать сколько угодно раз.

set -e
cd "$(dirname "$0")"

LOG="setup.log"
exec > >(tee -a "$LOG") 2>&1

log_step() {
    echo ""
    echo "=== [$(date +%H:%M:%S)] $1 ==="
}

log_step "Проверка платформы"
if [ "$(uname -m)" != "arm64" ]; then
    echo "ОШИБКА: этот инструмент только для Mac Apple Silicon (M1/M2/M3)."
    echo "Текущая архитектура: $(uname -m)"
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi
echo "✓ Apple Silicon"

# Очистить флаг успешного завершения — будет создан в самом конце.
# Иначе предыдущий успешный запуск + текущий аборт оставит stale flag,
# и prepare.command поверит, что setup ok.
rm -f setup_complete.flag

log_step "Homebrew"
if ! command -v brew &> /dev/null; then
    echo "Homebrew не найден, устанавливаю..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Apple Silicon: brew в /opt/homebrew/bin, нужно добавить в PATH текущей сессии
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "✓ Homebrew установлен ($(brew --version | head -1))"
    brew update
fi

# Защита от Rosetta x86 Homebrew (typично после миграции с Intel Mac).
# Если у пользователя есть /usr/local/bin/brew (x86), `command -v brew` найдёт
# его раньше /opt/homebrew/bin/brew, и мы поставим x86-пакеты под Rosetta —
# torch и whisper позже грохнутся с непонятными ошибками.
BREW_PREFIX=$(brew --prefix)
if [ "$BREW_PREFIX" != "/opt/homebrew" ]; then
    echo "ОШИБКА: найден x86 Homebrew по пути $BREW_PREFIX (Rosetta)."
    echo "Нужна arm64-версия Homebrew по /opt/homebrew."
    echo ""
    echo "Удали x86 Homebrew:"
    echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)\""
    echo "Затем перезапусти setup.command — он поставит arm64-версию автоматически."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi
echo "✓ Homebrew по $BREW_PREFIX (arm64)"

log_step "ffmpeg"
if ! command -v ffmpeg &> /dev/null || ! command -v ffprobe &> /dev/null; then
    brew install ffmpeg
else
    echo "✓ ffmpeg установлен ($(ffmpeg -version | head -1 | awk '{print $3}'))"
fi

log_step "Python 3.11"
if ! command -v python3.11 &> /dev/null; then
    brew install python@3.11
else
    echo "✓ Python 3.11 установлен ($(python3.11 --version))"
fi

log_step "Node.js + Claude Code"
if ! command -v node &> /dev/null; then
    brew install node
else
    echo "✓ Node $(node --version) установлен"
fi
if ! command -v claude &> /dev/null; then
    npm install -g @anthropic-ai/claude-code
else
    echo "✓ Claude Code установлен ($(claude --version 2>/dev/null || echo 'verify manually'))"
fi
echo ""
echo "ВАЖНО: после завершения setup открой Claude Code в этой папке"
echo "и авторизуйся (claude → /login)."
echo ""

log_step "uv (быстрый pip)"
if ! command -v uv &> /dev/null; then
    brew install uv
else
    echo "✓ uv установлен ($(uv --version))"
fi

log_step "Виртуальное окружение"
if [ ! -d ".venv" ]; then
    uv venv .venv --python python3.11
else
    echo "✓ .venv существует"
fi
source .venv/bin/activate

log_step "Python зависимости"
uv pip install -r requirements.txt
echo "✓ зависимости установлены"

log_step "Прогрев моделей (faster-whisper large-v3 + whisperx aligner)"
mkdir -p models
.venv/bin/python - <<'PY'
import os
os.environ['HF_HOME'] = os.path.join(os.getcwd(), 'models', 'hf')
os.environ['XDG_CACHE_HOME'] = os.path.join(os.getcwd(), 'models', 'cache')
print("Скачиваю faster-whisper large-v3 (может занять 5-10 минут)...")
from faster_whisper import WhisperModel
WhisperModel("large-v3", device="cpu", compute_type="int8")
print("✓ faster-whisper large-v3")

print("Скачиваю whisperx (align модель + diarization)...")
import whisperx
# align модель скачается при первом вызове load_align_model
print("✓ whisperx (модели скачаются при первом transcribe)")
PY

log_step "Проверка .env (HF_TOKEN — опционально)"
# HF_TOKEN нужен только если будешь запускать transcribe.py с --diarize
# (по умолчанию диаризация выключена). Без токена setup пройдёт, просто
# пропустим валидацию — пайплайн от этого не сломается.

if [ ! -f ".env" ]; then
    echo "ℹ .env не найден — диаризация отключена (это нормально)."
    echo "  Если когда-нибудь понадобится --diarize: см. docs/setup/hf_token/README.md"
else
    # Загрузить .env
    set -a
    . ./.env
    set +a

    if [ -z "$HF_TOKEN" ] || [ "$HF_TOKEN" = "hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" ]; then
        echo "ℹ HF_TOKEN не задан в .env — диаризация отключена."
        echo "  Если нужна — см. docs/setup/hf_token/README.md"
    else
        # Валидация токена и доступа к pyannote (warning-only, не fail)
        .venv/bin/python - <<'PY' || echo "  (не критично — нужно только для --diarize)"
import os
from huggingface_hub import HfApi
api = HfApi(token=os.environ['HF_TOKEN'])
try:
    user = api.whoami()
    print(f"✓ HF_TOKEN валиден (user: {user['name']})")
except Exception as e:
    print(f"⚠ HF_TOKEN невалиден: {e}")
    raise SystemExit(1)

for repo in ("pyannote/speaker-diarization-3.1", "pyannote/segmentation-3.0"):
    try:
        api.model_info(repo)
        print(f"✓ есть доступ к {repo}")
    except Exception as e:
        print(f"⚠ нет доступа к {repo}.")
        print(f"  Зайди на https://huggingface.co/{repo} и нажми 'Agree'.")
        raise SystemExit(1)
PY
    fi
fi

touch setup_complete.flag

log_step "ГОТОВО"
echo ""
echo "Установка завершена. Что дальше:"
echo ""
echo "  1. Открой Claude Code в Терминале:"
echo "     cd $(pwd)"
echo "     claude"
echo "     /login    (авторизация в Anthropic)"
echo ""
echo "  2. См. QUICKSTART.md для шагов на каждый новый проект."
echo ""

read -p "Нажми Enter чтобы закрыть..." _
```

**Step 2: Сделать исполняемым**

В git у файлов нет прав по умолчанию на Win-checkout. Установить exec-бит через git:

```bash
cd C:/Users/Alex/Videos/factory-employee
git update-index --chmod=+x setup.command
```

(Этот флаг сохранится в индексе и при чекаут на Mac файл будет исполняемым.)

**Step 3: Smoke-проверка синтаксиса**

```bash
bash -n C:/Users/Alex/Videos/factory-employee/setup.command
```

Ожидаемое: ничего не печатает (синтаксис ok).

**Step 4: Commit**

```bash
cd C:/Users/Alex/Videos/factory-employee
git add setup.command
git commit -m "feat: setup.command — установка инструмента (brew + uv + venv + warmup)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `update.command`

**Files:**
- Create: `C:\Users\Alex\Videos\factory-employee\update.command`

**Step 1: Написать**

```bash
#!/bin/bash
# update.command — обновить инструмент с github и переустановить deps если нужно.

set -e
cd "$(dirname "$0")"

LOG="setup.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== [$(date +%H:%M:%S)] Обновление ==="

# Хук для дружелюбного сообщения при любой неожиданной ошибке.
# Все ошибки git/pip/npm пойдут через set -e и сюда.
trap 'echo ""; echo "✗ Ошибка во время обновления. Пришли Алексу файл setup.log."' ERR

# Препроверки: setup должен быть пройден.
if [ ! -f .venv/bin/activate ]; then
    echo "ОШИБКА: .venv не найден. Сначала запусти setup.command."
    exit 1
fi

OLD_HEAD=$(git rev-parse HEAD)
git fetch origin
# --autostash: если у пользователя случайные изменения в working tree
# (например ручное правки), git временно прячет их в stash, делает rebase,
# и накатывает обратно. Защита от хард-стопов на dirty working tree.
git pull --rebase --autostash origin main
NEW_HEAD=$(git rev-parse HEAD)

if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
    echo "✓ Уже на последней версии."
    exit 0
fi

echo ""
echo "Что обновилось:"
git log --oneline "$OLD_HEAD..$NEW_HEAD" | head -20
echo ""

# Если изменился requirements.txt — переустановить
if git diff --name-only "$OLD_HEAD" "$NEW_HEAD" | grep -q '^requirements.txt$'; then
    echo "requirements.txt изменился, обновляю Python-зависимости..."
    source .venv/bin/activate
    uv pip install -r requirements.txt
    echo "✓ зависимости обновлены"
fi

# Если есть указание новой версии Claude Code (например в файле CLAUDE_CODE_VERSION)
if [ -f "CLAUDE_CODE_VERSION" ]; then
    # tr -d убирает любой trailing newline/whitespace из ручно отредактированного файла,
    # иначе npm install получит мусорный package spec.
    REQUIRED=$(tr -d '[:space:]' < CLAUDE_CODE_VERSION)
    CURRENT=$(claude --version 2>/dev/null | awk '{print $NF}' || echo "")
    if [ "$REQUIRED" != "$CURRENT" ]; then
        echo "Обновляю Claude Code до $REQUIRED..."
        npm install -g "@anthropic-ai/claude-code@$REQUIRED"
    fi
fi

echo ""
echo "✓ Обновление завершено."
```

**Step 2: Exec-бит и smoke**

```bash
cd C:/Users/Alex/Videos/factory-employee
git update-index --chmod=+x update.command
bash -n update.command
```

**Step 3: Commit**

```bash
git add update.command
git commit -m "feat: update.command — git pull + переустановка deps если изменились

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `prepare.command`

**Files:**
- Create: `C:\Users\Alex\Videos\factory-employee\prepare.command`

**Step 1: Написать**

```bash
#!/bin/bash
# prepare.command — фаза подготовки: cut_pauses + transcribe + match search.
# Аргумент: путь к проекту (projects/<имя>) или интерактивный prompt при двойном клике.

set -e
cd "$(dirname "$0")"

# --- 1. Sanity ---

if [ ! -f "setup_complete.flag" ]; then
    echo "ОШИБКА: сначала запусти setup.command (двойной клик)."
    echo "Закрой это окно, найди setup.command в Finder и сделай двойной клик."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "ОШИБКА: .venv не найден. Запусти setup.command заново."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "ОШИБКА: .env не найден. Запусти setup.command заново."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

# --- 2. Выбор проекта ---

PROJECT="$1"
if [ -z "$PROJECT" ]; then
    # Интерактивный режим (двойной клик)
    echo "Доступные проекты:"
    PROJECTS=()
    i=1
    for d in projects/*/; do
        if [ -d "$d" ]; then
            name=$(basename "$d")
            echo "  $i) $name"
            PROJECTS+=("$name")
            i=$((i+1))
        fi
    done
    if [ ${#PROJECTS[@]} -eq 0 ]; then
        echo ""
        echo "Нет проектов. Создай через Claude Code: попроси \"создать структуру для нового проекта YYYY-MM-описание\""
        read -p "Нажми Enter чтобы закрыть..." _
        exit 1
    fi
    echo ""
    read -p "Выбери номер проекта: " choice
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#PROJECTS[@]}" ]; then
        echo "ОШИБКА: неверный номер проекта."
        read -p "Нажми Enter чтобы закрыть..." _
        exit 1
    fi
    PROJECT="projects/${PROJECTS[$((choice-1))]}"
fi

if [ ! -d "$PROJECT" ]; then
    echo "ОШИБКА: $PROJECT не существует."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

PROJ_NAME=$(basename "$PROJECT")
LOG="$PROJECT/.factory.log"

# --- 3. Проверка входных файлов ---

if [ ! -d "$PROJECT/raw" ]; then
    echo "ОШИБКА: $PROJECT/raw не существует."
    echo "Создай через Claude Code: попроси \"создать структуру для проекта $PROJ_NAME\""
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

if [ ! -f "$PROJECT/script/script.csv" ]; then
    echo "ОШИБКА: $PROJECT/script/script.csv не найден."
    echo "Положи туда сценарий и запусти ещё раз."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

# Хотя бы один видеофайл должен быть в raw/
VIDEO_COUNT=$(find "$PROJECT/raw" -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.avi' \) | wc -l | tr -d ' ')
if [ "$VIDEO_COUNT" -eq 0 ]; then
    echo "ОШИБКА: в $PROJECT/raw нет видеофайлов (.mp4/.mov/.mkv/.avi)."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

# --- 4. Активация venv и env ---

source .venv/bin/activate
set -a
. ./.env
set +a

# Логирование (после $LOG разрешён, чтобы trap мог на него сослаться)
exec > >(tee -a "$LOG") 2>&1

# Дружелюбный обработчик любой неожиданной ошибки в тяжёлых шагах ниже
# (cut_pauses/transcribe/match — каждый по 30-90 минут; падение на середине
# реальный кейс: OOM, сетевые сбои при скачивании моделей).
# Без trap'а пользователь видит сырой Python traceback и закрытое окно.
on_error() {
    echo ""
    echo "✗ ОШИБКА на одном из шагов выше."
    echo "Лог: $LOG"
    echo ""
    echo "Открой Claude Code в этой папке и попроси:"
    echo "  посмотри $LOG и почини"
    echo ""
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
}
trap on_error ERR

log_step() {
    echo ""
    echo "=== [$(date +%H:%M:%S)] $1 ==="
}

# --- 5. Проверка обновлений (тихая) ---

# Только если origin настроен (после Task 13 push). До этого — пропускаем тихо.
if git remote get-url origin >/dev/null 2>&1; then
    if git fetch origin --quiet 2>/dev/null; then
        BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "0")
        if [ "$BEHIND" -gt 0 ]; then
            echo ""
            echo "⚠  Доступно обновление инструмента ($BEHIND новых коммитов)."
            echo "   Запусти update.command когда сможешь (1 минута)."
            echo ""
        fi
    fi
fi

# --- 6. ETA ---

log_step "Оценка времени"
TOTAL_SEC=0
while IFS= read -r f; do
    DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null || echo "0")
    DUR_INT=${DUR%.*}
    TOTAL_SEC=$((TOTAL_SEC + DUR_INT))
done < <(find "$PROJECT/raw" -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.avi' \))

# Эмпирика: cut_pauses ~0.7×, transcribe ~0.3× → итого 1.0×
ETA_MIN=$((TOTAL_SEC / 60))
echo "Найдено видео: $VIDEO_COUNT, общая длительность: $((TOTAL_SEC / 60)) минут"
echo "Примерное время обработки: ~$ETA_MIN минут (можно оставить и заняться другим)"
echo "Скрипт идемпотентный — если упадёт на середине, можно запускать повторно: уже обработанные файлы пропустятся."

# --- 7. cut_pauses войсовера ---

if [ -d "$PROJECT/raw/voiceover" ] && [ -n "$(ls -A "$PROJECT/raw/voiceover" 2>/dev/null)" ]; then
    log_step "cut_pauses войсовера (--profile slava)"
    .venv/bin/python _scripts/cut_pauses.py "$PROJECT/raw/voiceover" \
        --output "$PROJECT/cuts/voiceover" \
        --profile slava
fi

# --- 8. cut_pauses интервью ---

if [ -d "$PROJECT/raw/interviews" ] && [ -n "$(ls -A "$PROJECT/raw/interviews" 2>/dev/null)" ]; then
    log_step "cut_pauses интервью (--profile hero)"
    .venv/bin/python _scripts/cut_pauses.py "$PROJECT/raw/interviews" \
        --output "$PROJECT/cuts/interviews" \
        --profile hero
fi

# --- 9. transcribe ---

log_step "Транскрибация (whisperx, без диаризации)"
if [ -d "$PROJECT/cuts" ]; then
    .venv/bin/python _scripts/transcribe.py "$PROJECT/cuts" \
        --json \
        --output "$PROJECT/transcripts"
else
    echo "ОШИБКА: $PROJECT/cuts не создан (cut_pauses не выполнился)."
    exit 1
fi

# --- 10. match_timecodes search ---

log_step "Поиск кандидатов таймкодов"
.venv/bin/python _scripts/match_timecodes.py search "$PROJECT"

# --- 11. words_compact для агента ---

log_step "Подготовка words_compact для агента"
.venv/bin/python _scripts/match_timecodes.py compact "$PROJECT"

# --- 12. Финал ---

log_step "ПОДГОТОВКА ГОТОВА"
echo ""
echo "Что дальше:"
echo ""
echo "  1. Открой Claude Code (если ещё не открыт):"
echo "     cd $(pwd) && claude"
echo ""
echo "  2. Запусти агентную верификацию:"
echo "     /match-timecodes $PROJECT"
echo ""
echo "  3. Когда агент закончит (создан $PROJECT/script/verified.json):"
echo "     двойной клик на assemble.command, выбери проект"
echo ""

read -p "Нажми Enter чтобы закрыть..." _
```

**Step 2: Exec-бит и smoke**

```bash
cd C:/Users/Alex/Videos/factory-employee
git update-index --chmod=+x prepare.command
bash -n prepare.command
```

**Step 3: Commit**

```bash
git add prepare.command
git commit -m "feat: prepare.command — cut_pauses + transcribe + match_timecodes search

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `assemble.command`

**Files:**
- Create: `C:\Users\Alex\Videos\factory-employee\assemble.command`

**Step 1: Написать**

```bash
#!/bin/bash
# assemble.command — фаза сборки: snap + build_xml --davinci.

set -e
cd "$(dirname "$0")"

# --- 1. Sanity ---

if [ ! -f "setup_complete.flag" ]; then
    echo "ОШИБКА: сначала запусти setup.command."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

# --- 2. Выбор проекта ---

PROJECT="$1"
if [ -z "$PROJECT" ]; then
    echo "Доступные проекты:"
    PROJECTS=()
    i=1
    for d in projects/*/; do
        if [ -d "$d" ]; then
            name=$(basename "$d")
            echo "  $i) $name"
            PROJECTS+=("$name")
            i=$((i+1))
        fi
    done
    if [ ${#PROJECTS[@]} -eq 0 ]; then
        echo "Нет проектов."
        read -p "Нажми Enter чтобы закрыть..." _
        exit 1
    fi
    read -p "Выбери номер проекта: " choice
    PROJECT="projects/${PROJECTS[$((choice-1))]}"
fi

if [ ! -d "$PROJECT" ]; then
    echo "ОШИБКА: $PROJECT не существует."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

# --- 3. Проверка verified.json ---

if [ ! -f "$PROJECT/script/verified.json" ]; then
    echo "ОШИБКА: $PROJECT/script/verified.json не найден."
    echo ""
    echo "Сначала запусти агентную верификацию в Claude Code:"
    echo "  /match-timecodes $PROJECT"
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

# Не пустой?
if [ ! -s "$PROJECT/script/verified.json" ]; then
    echo "ОШИБКА: $PROJECT/script/verified.json пустой."
    read -p "Нажми Enter чтобы закрыть..." _
    exit 1
fi

LOG="$PROJECT/.factory.log"

source .venv/bin/activate

exec > >(tee -a "$LOG") 2>&1

log_step() {
    echo ""
    echo "=== [$(date +%H:%M:%S)] $1 ==="
}

# --- 4. snap ---

log_step "snap-to-silence (verified.json → script.csv с таймкодами)"
python _scripts/match_timecodes.py snap "$PROJECT"

# --- 5. build_xml --davinci ---

log_step "Генерация FCPXML для DaVinci"
python _scripts/build_xml.py "$PROJECT" --davinci

# --- 6. Финал ---

PROJ_NAME=$(basename "$PROJECT")
FCPXML_LOCAL="$PROJECT/assembly/${PROJ_NAME}_rough_cut_local.fcpxml"

log_step "СБОРКА ГОТОВА"
echo ""
if [ -f "$FCPXML_LOCAL" ]; then
    echo "FCPXML для DaVinci:"
    echo "  $(pwd)/$FCPXML_LOCAL"
    echo ""
    echo "Импортируй этот файл в DaVinci Resolve:"
    echo "  File → Import → Timeline → выбери $FCPXML_LOCAL"
else
    echo "⚠ ${FCPXML_LOCAL} не создан — проверь лог: $LOG"
fi

echo ""
read -p "Нажми Enter чтобы закрыть..." _
```

**Step 2: Exec-бит и smoke**

```bash
cd C:/Users/Alex/Videos/factory-employee
git update-index --chmod=+x assemble.command
bash -n assemble.command
```

**Step 3: Commit**

```bash
git add assemble.command
git commit -m "feat: assemble.command — snap + build_xml --davinci

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: README.md (полный) и QUICKSTART.md

**Files:**
- Modify: `C:\Users\Alex\Videos\factory-employee\README.md` (полное наполнение)
- Create: `C:\Users\Alex\Videos\factory-employee\QUICKSTART.md`

**Step 1: README.md**

```markdown
# Factory Employee

Пайплайн нарезки YouTube-интервью на Mac.

На вход — сырые видео (войсовер + интервью) и готовый сценарий в CSV.
На выход — FCPXML для импорта в DaVinci Resolve.

См. [QUICKSTART.md](QUICKSTART.md) для пошаговой инструкции.

## Что делает

```
сырые видео + script.csv (текст реплик)
        ↓
[prepare.command]
        ↓
cut_pauses (удаление пауз и слов-паразитов)
        ↓
transcribe (whisperx; диаризация опционально через --diarize)
        ↓
match_timecodes search (поиск кандидатов)
        ↓
[/match-timecodes в Claude Code — агентная верификация]
        ↓
[assemble.command]
        ↓
snap-to-silence (снап границ к тишине)
        ↓
build_xml --davinci
        ↓
FCPXML для DaVinci Resolve
```

## Установка

См. [QUICKSTART.md](QUICKSTART.md) раздел «Один раз».

Опционально (для `transcribe.py --diarize`): [docs/setup/hf_token/README.md](docs/setup/hf_token/README.md). В дефолтном пайплайне токен не нужен.

## Структура репо

- `setup.command` — установка (один раз).
- `prepare.command` — фаза подготовки (на каждый проект).
- `assemble.command` — фаза сборки (на каждый проект).
- `update.command` — обновление инструмента (`git pull` + переустановка deps).
- `_scripts/` — Python-скрипты (cut_pauses, transcribe, match_timecodes, build_xml).
- `.claude/skills/match-timecodes/` — скилл для Claude Code (агентная верификация таймкодов).
- `requirements.txt` — Python-зависимости с пин-версиями.
- `.env.example` — шаблон для HF_TOKEN (нужен только под опциональный `transcribe.py --diarize`).
- `projects/<имя>/` — рабочие директории каждого видео (создаются по запросу в Claude Code).

## Если что-то сломалось

Открой Claude Code в этой папке и попроси:

```
посмотри projects/<имя>/.factory.log и почини
```

Claude разберёт ошибку и предложит фикс. Если упало в setup — лог в `setup.log`.

## Системные требования

- Mac Apple Silicon (M1/M2/M3)
- macOS 13 (Ventura) или новее
- ~50 GB свободного места (модели + видео + промежуточные файлы)
- Стабильный интернет (для скачивания моделей при первом setup ~3 GB)

## Контакты

Если ничего не помогло — пиши Алексу.
```

**Step 2: QUICKSTART.md**

```markdown
# Quickstart

## Один раз

1. Двойной клик `setup.command`. Жди ~10 минут (скачивание моделей).
2. (Опционально) Если планируешь запускать `transcribe.py --diarize`, заведи `.env` с `HF_TOKEN`. См. [docs/setup/hf_token/README.md](docs/setup/hf_token/README.md). Без него дефолтный пайплайн работает.
3. Открой Claude Code:
   - В Терминале: `cd /путь/к/factory-employee && claude`
   - При первом запуске: `/login` → авторизация в Anthropic.

## На каждое новое видео

### Шаг 1. Создать проект (в Claude Code)

В Claude Code напиши:

```
создай структуру для нового проекта 2026-05-tulips-may
```

Имя в формате `YYYY-MM-описание`. Claude Code сам создаст папки `raw/voiceover/`, `raw/interviews/`, `script/` и пустой `script.csv`.

### Шаг 2. Положить материалы

Скопируй файлы:

- Войсовер Славы → `projects/2026-05-tulips-may/raw/voiceover/`
- Интервью героя → `projects/2026-05-tulips-may/raw/interviews/`
- Сценарий → `projects/2026-05-tulips-may/script/script.csv`

### Шаг 3. Подготовка (двойной клик)

`prepare.command` → выбери проект из списка.

⏱  Примерно 1 минута на 1 минуту видео (на 4 интервью по часу + получасовой войсовер — около 4-5 часов).

В конце скрипт скажет что делать дальше.

### Шаг 4. Верификация (в Claude Code)

```
/match-timecodes projects/2026-05-tulips-may
```

Агент пройдёт по неоднозначным репликам, попросит подтвердить выбор.

### Шаг 5. Сборка (двойной клик)

`assemble.command` → выбери проект из списка.

В конце получишь путь к FCPXML.

### Шаг 6. Импорт в DaVinci

```
projects/2026-05-tulips-may/assembly/2026-05-tulips-may_rough_cut_local.fcpxml
```

В DaVinci: **File → Import → Timeline** → выбери этот файл.

## Что-то сломалось?

Открой Claude Code и напиши:

```
посмотри projects/<имя>/.factory.log и почини
```

Если упало в setup → `setup.log`.

## Обновить инструмент

Двойной клик `update.command`. Если в начале `prepare.command` появилось предупреждение про обновление — самое время.
```

**Step 3: Commit**

```bash
cd C:/Users/Alex/Videos/factory-employee
git add README.md QUICKSTART.md
git commit -m "docs: README и QUICKSTART

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: HF_TOKEN docs (опциональный поток)

Эта инструкция нужна ТОЛЬКО если сотрудник захочет запускать `transcribe.py --diarize`. В дефолтном пайплайне диаризация не используется и токен не нужен.

**Files:**
- Create: `C:\Users\Alex\Videos\factory-employee\docs\setup\hf_token\README.md`

**Step 1: Написать README.md**

Без скриншотов на этом шаге — добавит сотрудник после первого setup'а или я отдельным коммитом, если будет нужно. Текстовая инструкция самодостаточна.

```markdown
# Получение HF_TOKEN (опционально)

Этот токен нужен **только** если запускаешь `transcribe.py --diarize` (диаризация — разметка «Спикер 1/2» в TXT). По умолчанию диаризация выключена и токен не требуется.

`pyannote/speaker-diarization-3.1` (диаризация в `transcribe.py --diarize`) требует доступ через HuggingFace токен. Это бесплатно, но нужна одноразовая регистрация и согласие с лицензиями.

## Шаги

### 1. Регистрация на HuggingFace

Зайди на https://huggingface.co и зарегистрируйся (или войди если есть аккаунт).

### 2. Согласие с лицензией pyannote/segmentation-3.0

Зайди на https://huggingface.co/pyannote/segmentation-3.0
Заполни форму («Affiliation» / «What's your purpose» — можно «video editing») и нажми **Agree and access repository**.

### 3. Согласие с лицензией pyannote/speaker-diarization-3.1

Зайди на https://huggingface.co/pyannote/speaker-diarization-3.1
То же — заполни и **Agree**.

### 4. Создать токен

Зайди на https://huggingface.co/settings/tokens
**New token** → дай название (например, `factory`) → тип **read** → **Generate token**.
Скопируй токен (он начинается с `hf_`).

### 5. Положить токен в .env

В Finder открой папку `factory-employee`.
В Терминале (или через Finder → правый клик `.env.example` → Duplicate → переименовать в `.env`):

```bash
cp .env.example .env
```

Открой `.env` в TextEdit (правый клик → Open With → TextEdit).
Замени `hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` на свой токен.
Сохрани (Cmd+S).

### 6. Проверка

Запусти `setup.command` (двойной клик).
Если `.env` лежит рядом и токен валиден — в логе увидишь:

```
✓ HF_TOKEN валиден (user: <твоё имя>)
✓ есть доступ к pyannote/speaker-diarization-3.1
✓ есть доступ к pyannote/segmentation-3.0
```

Если токена нет — setup просто пропустит этот шаг (это нормально для дефолтного пайплайна).
```

**Step 2: Commit**

```bash
cd C:/Users/Alex/Videos/factory-employee
git add docs/
git commit -m "docs: HF_TOKEN setup guide

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10 (Manual): Smoke setup на Mac (VM или сотрудник)

**Files:** —

**Step 1: Подготовить тест-машину**

Один из вариантов:
- (a) UTM VM с macOS arm64 на моей Win-машине.
- (b) Сотрудник по видеосвязи проходит setup, я смотрю экран.
- (c) Если есть свой Mac — напрямую.

**Step 2: Прогнать setup**

На тест-машине:

```bash
git clone <github_url>/factory-employee
cd factory-employee
./setup.command
```

Ожидаемое:
- Все 10 шагов «зелёные».
- В конце: «Установка завершена. Что дальше: ...».
- `setup.log` содержит полный transcript.
- `setup_complete.flag` создан.
- `.venv/` создано.
- `models/` непустое.

**Step 3: Зафиксировать ошибки**

Если что-то упало — записать конкретный шаг и stderr. Скорее всего:
- `torch==2.2.2` может не поставиться → попробовать `2.3.0` или `2.4.0` для arm64.
- `whisperx` может конфликтовать с какой-то версией torch → uv покажет конфликт версий.
- `pyannote.audio==3.1.1` может требовать другой numpy — uv разрулит.

**Step 4: Корректировка requirements.txt и повторный smoke**

Если фикс понадобился — апдейт `requirements.txt` в основном Win-репо, push, на тест-машине `update.command` или повторный setup.

```bash
cd C:/Users/Alex/Videos/factory-employee
# Edit requirements.txt
git add requirements.txt
git commit -m "chore: pin <package> до <version> — фикс для Mac arm64

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Повторять пока setup не пройдёт чисто.

**Step 5: Зафиксировать рабочие версии**

Когда setup проходит — текущий `requirements.txt` это validated baseline. Не менять без причины.

---

## Task 11 (Manual): Smoke прохода на маленьком тестовом проекте

**Files:** —

**Step 1: Подготовить минимальный тестовый набор**

На тест-машине (или локально на Mac):
- Короткий войсовер (1-2 минуты) — `tiny_voiceover.mp4`.
- Короткое интервью с двумя голосами (3-5 минут) — `tiny_interview.mp4`.
- Сценарий (3-5 реплик в CSV).

**Step 2: Прогнать**

В Claude Code попроси: «создай структуру для проекта 2026-05-smoke-test».

Скопировать видео, положить script.csv:

```bash
cp tiny_voiceover.mp4 projects/2026-05-smoke-test/raw/voiceover/
cp tiny_interview.mp4 projects/2026-05-smoke-test/raw/interviews/
cp test-script.csv projects/2026-05-smoke-test/script/script.csv
```

Двойной клик `prepare.command` → выбрать `2026-05-smoke-test`.

Ожидаемое:
- Каждая фаза печатает прогресс в Терминал.
- В конце: «Подготовка готова. /match-timecodes projects/2026-05-smoke-test».
- `cuts/`, `transcripts/`, `candidates.json`, `words_compact.txt` созданы.

В Claude Code:

```
/match-timecodes projects/2026-05-smoke-test
```

Агент пройдёт реплики, создаст `verified.json`.

Двойной клик `assemble.command` → выбрать `2026-05-smoke-test`.

Ожидаемое:
- `script.csv` обновлён с таймкодами.
- `assembly/2026-05-smoke-test_rough_cut_local.fcpxml` создан.

**Step 3: Импорт в DaVinci**

Открыть DaVinci Resolve → File → Import → Timeline → выбрать FCPXML.

Ожидаемое: импортируется без ошибок, на таймлайне видны клипы V1 (Слава) и V2 (Герой).

**Step 4: Зафиксировать issues**

Если на каком-то шаге упало или результат странный — записать. Скорее всего:
- `cut_pauses.py` или `transcribe.py` могут ругаться на пути с пробелами/кириллицей → проверить кодировку.
- `silencedetect` в `match_timecodes.py snap` требует ffmpeg — проверить что брю поставил корректную версию.
- DaVinci может не открыть FCPXML если пути относительные → проверить `_local.fcpxml` (с абсолютными).

Фиксы — в основном `factory/_scripts/` (если в скриптах), синхронизировать в `factory-employee/_scripts/`, push, retest.

---

## Task 12 (Manual): Регрессия на термосумках

**Files:** —

**Step 1: Подготовить тестовый набор**

Скопировать на тест-машину:
- `factory/projects/2026-03-thermobags/raw/` (целиком).
- `factory/projects/2026-03-thermobags/script/script.csv` — но **только колонки** `Слава` и `Герой`, без таймкодов (зачистить колонки timecode).

**Step 2: Прогнать полный пайплайн**

В Claude Code попроси: «создай структуру для проекта 2026-03-thermobags-regression».

Скопировать видео и подготовленный script.csv.

`prepare.command` → выбрать проект → ждать (на термосумках это ~2-3 часа).

`/match-timecodes projects/2026-03-thermobags-regression` → агентная верификация.

`assemble.command` → выбрать проект.

**Step 3: Сравнить с эталоном Win-пайплайна**

Эталон — `factory/projects/2026-03-thermobags/assembly/2026-03-thermobags_rough_cut_local.fcpxml` (созданный на моей Win-машине после фикса оверлапов).

Сравнение:

```bash
# Структура — одинаковое количество клипов на каждом треке
python -c "
import xml.etree.ElementTree as ET
def count_clips(path):
    root = ET.parse(path).getroot()
    return [(track.tag, len(list(track.iter('clip')))) for track in root.iter('track')]

print('Эталон:', count_clips('эталон.fcpxml'))
print('Регрессия:', count_clips('регрессия.fcpxml'))
"
```

Ожидаемое: совпадает структура (одинаковое количество клипов на V1 и V2, одинаковая последовательность файлов).

**Расхождения:**
- ✓ Допустимо: float-noise в `start`/`end` таймкодах до ~0.1с (whisperx даёт чуть разные результаты на CPU vs GPU vs MPS).
- ✗ Недопустимо: разное число клипов, другой порядок, другой выбор файлов.

**Step 4: Документировать расхождения**

Если значительные расхождения — записать в issue:
- Какая фаза вышла иначе (transcribe? match search? snap?).
- На каких репликах.
- Возможные причины.

Это становится отдельной задачей про детерминированность — не блокер для отдачи сотруднику, но открытый риск 1 из дизайна.

---

## Task 13 (Manual): Push в приватный github repo и доступ сотруднику

**Files:** —

**Step 1: Создать приватный github repo**

В browser: github.com → New repository → name `factory-employee` → **Private** → не инициализируй с README (у нас уже есть).

**Step 2: Push**

```bash
cd C:/Users/Alex/Videos/factory-employee
git remote add origin git@github.com:<your-user>/factory-employee.git
git branch -M main
git push -u origin main
```

(или https URL если ssh не настроен).

**Step 3: Добавить сотрудника как collaborator**

github.com/<your-user>/factory-employee → Settings → Collaborators → Add people → ник сотрудника → Read access (хватит read — апдейтов через update.command, write им не нужен).

**Step 4: Отдать инструкцию сотруднику**

Текст (можно в мессенджер):

```
Привет! Инструмент нарезки готов. Что делать:

1. Установи Xcode Command Line Tools (нужно для git):
   В Терминале: xcode-select --install

2. Склонируй репо:
   cd ~/Documents
   git clone git@github.com:<your-user>/factory-employee.git
   (если ssh не настроен — https://github.com/<your-user>/factory-employee.git)

3. Открой папку в Finder, двойной клик setup.command.
   Жди ~10 минут.

4. (Опционально) Если планируешь запускать transcribe.py --diarize —
   заведи .env с HF_TOKEN по docs/setup/hf_token/README.md.
   В дефолтном пайплайне токен не нужен.

5. Дальше — QUICKSTART.md.

Если что-то сломается — открой Claude Code в этой папке (claude в Терминале)
и попроси: "посмотри лог setup.log и почини".
```

**Step 5: Проверить что сотрудник прошёл setup и smoke**

По связи (или по сообщениям) проверить что:
- setup.log без ошибок.
- prepare.command на маленьком тестовом проекте проходит.
- /match-timecodes работает.
- assemble.command создаёт FCPXML.
- DaVinci открывает FCPXML.

**Step 6: (Опционально) Memory update**

Создать новый memory `project_employee_pipeline.md` про то что инструмент перенесён и где он. Обновить `MEMORY.md`.

---

## Тестирование (общая стратегия)

Юнит-тестов нет, есть три уровня верификации:

1. **Smoke синтаксиса bash-скриптов** — `bash -n` (Task 4-7).
2. **Smoke setup на Mac** — Task 12. Все шаги проходят, deps ставятся.
3. **Smoke маленького проекта** — Task 13. Полный пайплайн на минимальных данных.
4. **Регрессия на термосумках** — Task 14. Сравнение с Win-эталоном.

## Откат

Откат в новом репо тривиальный — `git reset --hard <hash>` или удалить локальный клон и склонить заново.
В основном `factory` ничего не меняется. Откат для нового репо — `git reset --hard <hash>` или удалить локальный клон.

## Открытые вопросы / риски (из дизайна)

1. **Whisper-детерминированность Win vs Mac.** Может всплыть в Task 14. Решение по факту.
2. **torch + MPS совместимость.** Может потребовать корректировку `requirements.txt` в Task 12.
3. **Зеркалирование `_scripts/`.** Сейчас простое копирование. Если апдейты основного `factory` будут частыми — настроить `git subtree`. Не блокер, отдельная задача.
4. **Размер диска.** ~50 GB на проект (видео + кэш). README предупреждает.
5. **`script.csv` формат.** Task 8 фиксирует пример в скилле; если формат будет меняться — синхронно править в `match_timecodes.py` и в скилле.
