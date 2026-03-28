# YouTube Best Practices Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Добавить 4 новых приёма в справочник `docs/youtube-best-practices/` и интегрировать их в `/yt-analyze`.

**Architecture:** 4 независимых `.md`-файла (14-17) в формате существующих практик + обновление скилла `yt-analyze` (добавление в список файлов и секцию «по ситуации»).

**Tech Stack:** Markdown-файлы, без кода.

---

### Task 1: Создать 14-hero-arc.md

**Files:**
- Create: `docs/youtube-best-practices/14-hero-arc.md`
- Reference: `docs/youtube-best-practices/06-misconception-first.md` (формат-образец)
- Reference: `docs/article-examples/термосумки.md`, `docs/article-examples/когтеточки.md`, `docs/article-examples/агродроны.md` (фактура для примеров)

**Step 1: Написать файл**

Структура:
- `# Арка героя`
- `## Суть` — герой как персонаж с трансформацией (кем был → что случилось → кем стал). Отличие от Interview Format: тот покрывает отбор цитат, арка — раскрытие характера.
- `## Правила` — 4 правила из дизайн-дока:
  1. Найти точку «до» и «после» в транскрипте
  2. Трансформация конкретная, не абстрактная
  3. Показывать слабости и ошибки
  4. 2-3 поворотных момента, не полная биография
- `## Примеры` — заголовок `> Все цифры в примерах взяты из статей в docs/article-examples/.`, затем 2-3 примера на фактуре статей (термосумки: стройка → долги → экспорт; агродроны: увидел огоньки в поле → купил дрон → 3.6 млн за сезон). Формат: «Плохо (пересказ биографии)» vs «Хорошо (арка через поворотные моменты)».
- `## Источники` — Campbell, Снайдер, Blackman

**Step 2: Commit**

```bash
git add docs/youtube-best-practices/14-hero-arc.md
git commit -m "docs: добавить приём «Арка героя» в youtube-best-practices"
```

---

### Task 2: Создать 15-contrast-juxtaposition.md

**Files:**
- Create: `docs/youtube-best-practices/15-contrast-juxtaposition.md`
- Reference: те же article-examples

**Step 1: Написать файл**

Структура:
- `# Контраст и джакстапозиция`
- `## Суть` — два факта рядом, разница говорит сама. Отличие от misconception-first.
- `## Правила` — 5 правил из дизайн-дока
- `## Примеры` — когтеточки: себестоимость 368 ₽ vs комиссия Ozon 739 ₽; термосумки: «хорошая изоляция» vs «минус 20-30 градусов за 30 минут»; агродроны: трактор 30 га vs дрон 150 га за ночь. Формат: «Плохо (факт без пары)» vs «Хорошо (два факта рядом)».
- `## Источники` — McKee, Blackman

**Step 2: Commit**

```bash
git add docs/youtube-best-practices/15-contrast-juxtaposition.md
git commit -m "docs: добавить приём «Контраст и джакстапозиция» в youtube-best-practices"
```

---

### Task 3: Создать 16-nested-narrative.md

**Files:**
- Create: `docs/youtube-best-practices/16-nested-narrative.md`
- Reference: те же article-examples

**Step 1: Написать файл**

Структура:
- `# Вложенный нарратив (story-in-story)`
- `## Суть` — микро-история 30-60 сек из транскрипта героя. Отличие от цитаты.
- `## Правила` — 5 правил из дизайн-дока
- `## Примеры` — термосумки: история про объявление в газете и первые звонки; когтеточки: «забрал команду, снял склад»; агродроны: ночь в поле, увидел огоньки. Формат: «Плохо (голая цитата-факт)» vs «Хорошо (мини-сюжет с завязкой и развязкой)».
- `## Источники` — McKee, Storybrand

**Step 2: Commit**

```bash
git add docs/youtube-best-practices/16-nested-narrative.md
git commit -m "docs: добавить приём «Вложенный нарратив» в youtube-best-practices"
```

---

### Task 4: Создать 17-viewer-proxy.md

**Files:**
- Create: `docs/youtube-best-practices/17-viewer-proxy.md`
- Reference: те же article-examples

**Step 1: Написать файл**

Структура:
- `# Зритель-прокси`
- `## Суть` — автор как представитель зрителя. Отличие от re-hooks.
- `## Правила` — 5 правил из дизайн-дока
- `## Примеры` — термосумки: «Подождите, пятнадцать лет в долгах — и он не закрылся?»; когтеточки: «То есть Ozon забирает больше, чем стоит произвести?»; агродроны: «Триста пятьдесят тысяч за четыре часа — серьёзно?». Формат: «Плохо (автор пересказывает нейтрально)» vs «Хорошо (автор реагирует как зритель)».
- `## Источники` — Neville Medhora, Blackman

**Step 2: Commit**

```bash
git add docs/youtube-best-practices/17-viewer-proxy.md
git commit -m "docs: добавить приём «Зритель-прокси» в youtube-best-practices"
```

---

### Task 5: Обновить /yt-analyze — добавить новые приёмы

**Files:**
- Modify: `.claude/commands/yt-analyze.md:67-98`

**Step 1: Добавить файлы в список чтения (строки 67-78)**

Добавить после строки 78:
```
- `14-hero-arc.md`
- `15-contrast-juxtaposition.md`
- `16-nested-narrative.md`
- `17-viewer-proxy.md`
```

**Step 2: Добавить в секцию «по ситуации» (строки 90-98)**

Добавить после строки 94:
```
- **14 Hero Arc** — подходит, если в материале герой прошёл трансформацию (точка «до» резко отличается от «после»)
- **15 Contrast** — подходит, если в материале есть пары фактов/цифр, разница между которыми говорит сама за себя
- **16 Nested Narrative** — подходит, если в транскрипте есть яркие мини-истории героя (случай, эпизод) с завязкой и развязкой
- **17 Viewer Proxy** — подходит, если материал содержит контринтуитивные факты или цифры, вызывающие естественное удивление
```

**Step 3: Commit**

```bash
git add .claude/commands/yt-analyze.md
git commit -m "feat: добавить 4 новых приёма в /yt-analyze"
```
