#!/usr/bin/env python3
"""Многопроходное сопоставление реплик сценария с таймкодами из транскриптов.

Команды:
  search <project_dir>   — Pass 1: поиск кандидатов по n-граммам
  snap <project_dir>     — Pass 3: привязка таймкодов к тишине
  compact <project_dir>  — Генерация words_compact.txt
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi"}


# ─── Утилиты ───────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Приводит текст к нижнему регистру, ё→е, убирает пунктуацию, схлопывает пробелы."""
    text = text.lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fmt_tc(seconds: float) -> str:
    """Секунды → 'MM:SS.ss'."""
    if seconds <= 0:
        return "00:00.00"
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m:02d}:{s:05.2f}"


# ─── Текстовый индекс ──────────────────────────────────────────────────────

def build_text_index(words: list[dict]) -> tuple[str, list[int]]:
    """Собирает полный нормализованный текст и карту char→word_idx."""
    parts = []
    char_map = []
    for i, w in enumerate(words):
        norm = normalize(w["word"])
        if not norm:
            continue
        if parts:
            char_map.append(i)  # пробел принадлежит следующему слову
        parts.append(norm)
        char_map.extend([i] * len(norm))
    full_text = " ".join(parts)
    return full_text, char_map


def _find_all(needle: str, haystack: str) -> list[int]:
    """Все позиции вхождения подстроки."""
    positions = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


MAX_WORD_DURATION = 1.5  # секунд — максимальная разумная длительность одного слова


def _safe_time(word: dict, field: str, words: list[dict], idx: int) -> float:
    """Берёт start/end из слова; если 0.0 — ищет у соседей.

    Для end: ограничивает длительность слова MAX_WORD_DURATION
    (артефакт Whisper — end последнего слова сегмента часто растянут на тишину).
    """
    val = word.get(field, 0.0)
    if val and val > 0.0:
        # Защита от артефактов Whisper: end слишком далеко от start
        if field == "end":
            word_start = word.get("start", 0.0)
            if word_start > 0 and val - word_start > MAX_WORD_DURATION:
                return round(word_start + MAX_WORD_DURATION, 2)
        return val
    # Ищем ближайшего соседа с валидным значением
    direction = -1 if field == "start" else 1
    for offset in range(1, 20):
        ni = idx + direction * offset
        if 0 <= ni < len(words):
            nval = words[ni].get(field, 0.0)
            if nval and nval > 0.0:
                return nval
    return 0.0


# ─── Fuzzy whole-match (LCS) ───────────────────────────────────────────────

# Разрыв в matched_b > FALSE_START_GAP считается false-start'ом
# (спикер начал, ошибся, повторил) и режется на отдельные части.
FALSE_START_GAP = 5
# Часть с количеством совпавших слов < FALSE_START_MIN_PART игнорируется как
# фрагмент false-start'а (например, 2 слова "курьеры тут" перед чистым дублем).
FALSE_START_MIN_PART = 3


def fuzzy_whole_match(phrase: str, transcripts: dict, min_score: float = 0.85) -> list[dict] | None:
    """LCS по скользящему окну. Возвращает список частей (1+) или None.

    Каждая часть: {file, start, end, score, words_matched, total_words, text}.
    Обычно одна часть. Если внутри окна обнаружен false-start (разрыв в
    выравнивании > FALSE_START_GAP слов транскрипта), фраза режется на
    несколько частей — гарбидж между чистыми попытками выкидывается.
    """
    pwords = normalize(phrase).split()
    if len(pwords) < 3:
        return None

    # Двухпроходный поиск:
    # Pass 1 — быстрый rolling-LCS только для score, ищем лучшее окно.
    # Pass 2 — full DP + backtrack только для победителя.
    # Перед LCS — multiset-prefilter: верхняя оценка LCS = пересечение
    # bag-of-words фразы и окна. Если меньше порога, LCS заведомо ниже.
    pcounter = Counter(pwords)
    min_overlap = int(min_score * len(pwords))
    best = None  # (score, words, twords, start_idx, filename)

    for filename, tdata in transcripts.items():
        words = tdata["words"]
        twords = tdata.get("norm_words") or [normalize(w.get("word", "")) for w in words]

        m = len(twords)
        if m == 0:
            continue

        # Широкое окно нужно чтобы захватить false-start'ы:
        # спикер мог начать → споткнуться → начать заново. Узкое окно
        # видит только одну попытку и теряет другую.
        window_len = int(len(pwords) * 2.5) + 5
        for start_idx in range(0, max(1, m - window_len + 1)):
            end_idx = min(m, start_idx + window_len)
            window = twords[start_idx:end_idx]

            wcounter = Counter(window)
            overlap = sum(min(pcounter[w], wcounter[w]) for w in pcounter)
            if overlap < min_overlap:
                continue

            lcs_len = _lcs_length(pwords, window)
            score = lcs_len / len(pwords)

            if score >= min_score and (best is None or score > best[0]):
                best = (score, words, twords, start_idx, filename)

    if best is None:
        return None

    score, words, twords, start_idx, filename = best
    window_len = int(len(pwords) * 2.5) + 5
    end_idx = min(len(twords), start_idx + window_len)
    _, matched_pairs = _lcs_align(pwords, twords[start_idx:end_idx])
    parts_split = _split_false_starts(matched_pairs, FALSE_START_GAP, FALSE_START_MIN_PART)
    parts_split = _drop_redundant_parts(parts_split)
    if not parts_split:
        return None

    result = []
    for p in parts_split:
        first_widx = start_idx + p["b_first"]
        last_widx = start_idx + p["b_last"]
        start_t = _safe_time(words[first_widx], "start", words, first_widx)
        end_t = _safe_time(words[last_widx], "end", words, last_widx)
        part_text = " ".join(pwords[p["a_first"]:p["a_last"] + 1])
        result.append({
            "file": filename,
            "start": round(start_t, 2),
            "end": round(end_t, 2),
            "score": round(score, 3),
            "words_matched": p["count"],
            "total_words": len(pwords),
            "text": part_text,
        })
    return result


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Только длина LCS (rolling DP). Без восстановления выравнивания.

    Используется в pass 1 fuzzy_whole_match — быстрее чем _lcs_align,
    т.к. не аллоцирует полную таблицу.
    """
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        ai = a[i - 1]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[m]


def _lcs_align(a: list[str], b: list[str]) -> tuple[int, list[tuple[int, int]]]:
    """LCS с восстановлением выравнивания.

    Возвращает (длина_LCS, пары_(a_idx,_b_idx)_совпавших_слов).
    Пары отсортированы по возрастанию b_idx.
    """
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0, []
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    matched = []
    i, j = n, m
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            matched.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    matched.reverse()
    return dp[n][m], matched


def _split_false_starts(matched_pairs: list[tuple[int, int]],
                        gap_threshold: int,
                        min_part_words: int) -> list[dict]:
    """Режет matched_pairs на части по разрывам в b > gap_threshold.

    Возвращает список dict-ов: {a_first, a_last, b_first, b_last, count}.
    Части с count < min_part_words отбрасываются (шум).
    """
    if not matched_pairs:
        return []
    groups = [[matched_pairs[0]]]
    for ai, bi in matched_pairs[1:]:
        prev_bi = groups[-1][-1][1]
        if bi - prev_bi > gap_threshold:
            groups.append([(ai, bi)])
        else:
            groups[-1].append((ai, bi))

    result = []
    for g in groups:
        if len(g) < min_part_words:
            continue
        result.append({
            "a_first": g[0][0],
            "a_last": g[-1][0],
            "b_first": g[0][1],
            "b_last": g[-1][1],
            "count": len(g),
        })
    return result


def _drop_redundant_parts(parts: list[dict]) -> list[dict]:
    """Дропает части, чей a-диапазон (слова фразы) полностью покрыт другой частью.

    Это false-start того же куска: спикер начал, остановился, начал заново
    с того же места. В таких случаях оставляем самую полную попытку.
    """
    if len(parts) < 2:
        return parts
    keep = [True] * len(parts)
    for i, p in enumerate(parts):
        for j, q in enumerate(parts):
            if i == j or not keep[j]:
                continue
            if (q["a_first"] <= p["a_first"]
                    and q["a_last"] >= p["a_last"]
                    and q["count"] > p["count"]):
                keep[i] = False
                break
    return [p for p, k in zip(parts, keep) if k]


# ─── Разбиение на предложения и склейка частей ─────────────────────────────

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Делит текст по [.!?]. Пустые/тривиальные (<3 слов) игнорируются."""
    parts = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return [p for p in parts if len(p.split()) >= 3]


def merge_adjacent_parts(parts: list[dict], max_gap: float = 3.0) -> list[dict]:
    """Склеивает соседние parts, которые в одном файле и разрыв < max_gap сек."""
    if len(parts) < 2:
        return parts
    merged = [parts[0]]
    for p in parts[1:]:
        last = merged[-1]
        if (p["file"] == last["file"]
                and 0 <= p["start"] - last["end"] < max_gap):
            merged[-1] = {
                "file": last["file"],
                "start": last["start"],
                "end": p["end"],
                "text": last["text"] + " " + p["text"],
            }
        else:
            merged.append(p)
    return merged


def find_quote_parts(phrase: str, transcripts: dict) -> dict:
    """Главная функция поиска. Возвращает словарь с ключами parts/unmatched/mode.

    Структура:
        {
            "parts": [{text, candidates: [{file, start, end}, ...]}],
            "unmatched": [str],
            "mode": "whole" | "split",
        }

    Для whole-match `parts` содержит один элемент со списком candidates длины 1.
    Для split-match каждый part имеет только свои candidates.
    Если внутри whole-match найден false-start — возвращаются несколько parts
    (между чистыми попытками вырезается гарбидж), mode остаётся "whole".
    """
    whole_parts = fuzzy_whole_match(phrase, transcripts)
    if whole_parts:
        # Когда whole вернул одну часть — текст полной фразы.
        # Когда несколько (false-start split) — у каждой части свой срез слов.
        single = len(whole_parts) == 1
        return {
            "parts": [{
                "text": phrase if single else w["text"],
                "candidates": [{
                    "file": w["file"],
                    "start": w["start"],
                    "end": w["end"],
                }],
            } for w in whole_parts],
            "unmatched": [],
            "mode": "whole",
        }

    sentences = split_sentences(phrase)
    if not sentences:
        # Короткая фраза — одна "часть" с обычным кандидатским поиском.
        cands = find_candidates(phrase, transcripts)
        return {
            "parts": [{
                "text": phrase,
                "candidates": [
                    {"file": c["file"], "start": c["start"], "end": c["end"]}
                    for c in cands
                ],
            }],
            "unmatched": [],
            "mode": "split",
        }

    parts_out = []
    unmatched = []
    for s in sentences:
        cands = find_candidates(s, transcripts)
        cands.sort(key=lambda c: c["start"])
        if not cands:
            unmatched.append(s)
            continue
        parts_out.append({
            "text": s,
            "candidates": [
                {"file": c["file"], "start": c["start"], "end": c["end"]}
                for c in cands
            ],
        })

    # Мёрдж соседних: только для частей с единственным кандидатом.
    single_cand_parts = [
        {"file": p["candidates"][0]["file"],
         "start": p["candidates"][0]["start"],
         "end": p["candidates"][0]["end"],
         "text": p["text"]}
        for p in parts_out if len(p["candidates"]) == 1
    ]
    merged = merge_adjacent_parts(single_cand_parts)

    # Сливаем обратно: если все parts_out имеют 1 кандидата — возвращаем merged.
    # Иначе оставляем как есть (агент-ревьюер выберет).
    if all(len(p["candidates"]) == 1 for p in parts_out):
        parts_out = [
            {
                "text": m["text"],
                "candidates": [{"file": m["file"], "start": m["start"], "end": m["end"]}],
            }
            for m in merged
        ]

    return {
        "parts": parts_out,
        "unmatched": unmatched,
        "mode": "split",
    }


# ─── Поиск кандидатов ──────────────────────────────────────────────────────

def find_candidates(phrase: str, transcripts: dict) -> list[dict]:
    """N-грамм поиск (6→3 слов) по всем транскриптам. Возвращает все совпадения."""
    phrase_norm = normalize(phrase)
    pwords = phrase_norm.split()
    if len(pwords) < 3:
        return []

    all_matches = []

    for filename, tdata in transcripts.items():
        full_text = tdata["full_text"]
        char_map = tdata["char_map"]
        words = tdata["words"]

        file_matches = []

        for n in range(min(6, len(pwords)), 2, -1):
            for i in range(len(pwords) - n + 1):
                gram = " ".join(pwords[i : i + n])
                positions = _find_all(gram, full_text)
                for pos in positions:
                    if pos >= len(char_map):
                        continue
                    widx = char_map[min(pos, len(char_map) - 1)]
                    # Корректируем начало/конец на всю фразу
                    start_widx = max(0, widx - i)
                    end_widx = min(len(words) - 1, start_widx + len(pwords) - 1)

                    start_t = round(_safe_time(words[start_widx], "start", words, start_widx), 2)
                    end_t = round(_safe_time(words[end_widx], "end", words, end_widx), 2)

                    # Дедупликация: мержим если в пределах 5 секунд
                    merged = False
                    for m in file_matches:
                        if abs(m["start"] - start_t) < 5:
                            if n > m["ngram_len"]:
                                m["start"] = start_t
                                m["end"] = end_t
                                m["words_start"] = start_widx
                                m["words_end"] = end_widx
                                m["ngram_len"] = n
                            merged = True
                            break
                    if not merged:
                        file_matches.append({
                            "file": filename,
                            "start": start_t,
                            "end": end_t,
                            "words_start": start_widx,
                            "words_end": end_widx,
                            "ngram_len": n,
                        })

            if file_matches:
                break  # Нашли по длинной n-грамме — короче не пробуем

        all_matches.extend(file_matches)

    return all_matches


# ─── Загрузка данных ────────────────────────────────────────────────────────

def load_script(project_dir: Path) -> list[dict]:
    """Читает script.csv. Возвращает список {row_idx, speaker, text, col}."""
    csv_path = project_dir / "script" / "script.csv"
    if not csv_path.exists():
        print(f"Ошибка: не найден {csv_path}", file=sys.stderr)
        sys.exit(1)

    lines = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # пропускаем заголовок
        for row_idx, row in enumerate(reader, start=2):  # строки с 2 (1 = заголовок)
            while len(row) < 4:
                row.append("")
            # text_col — колонка текста, tc_col — колонка таймкодов
            # CSV: Слава(0), Таймкоды(1), Герой(2), Таймкоды(3)
            for text_col, tc_col, speaker in [(0, 1, "slava"), (2, 3, "hero")]:
                text = row[text_col].strip()
                if not text:
                    continue
                if text.startswith("ЭПИЗОД"):
                    continue
                lines.append({
                    "row_idx": row_idx,
                    "speaker": speaker,
                    "text": text,
                    "col": tc_col,
                })
    print(f"Загружено строк из сценария: {len(lines)}")
    return lines


def load_transcripts(project_dir: Path) -> dict:
    """Читает все *.transcript.json из transcripts/. Возвращает {filename: {words, full_text, char_map}}."""
    tr_dir = project_dir / "transcripts"
    if not tr_dir.exists():
        print(f"Ошибка: не найдена папка {tr_dir}", file=sys.stderr)
        sys.exit(1)

    result = {}
    for jp in sorted(tr_dir.glob("*.transcript.json")):
        with open(jp, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Собираем все слова из всех сегментов
        all_words = []
        for seg in data.get("segments", []):
            all_words.extend(seg.get("words", []))

        if not all_words:
            print(f"  Пропущен {jp.name}: нет слов")
            continue

        source = data.get("source", jp.stem.replace(".transcript", ""))
        full_text, char_map = build_text_index(all_words)
        norm_words = [normalize(w.get("word", "")) for w in all_words]

        result[source] = {
            "words": all_words,
            "full_text": full_text,
            "char_map": char_map,
            "norm_words": norm_words,
        }
        print(f"  Транскрипт: {source} — {len(all_words)} слов")

    return result


def _get_speaker_files(project_dir: Path) -> tuple[set[str], set[str]]:
    """Определяет какие файлы — войсовер (slava), какие — интервью (hero)."""
    voiceover_dir = project_dir / "raw" / "voiceover"
    interviews_dir = project_dir / "raw" / "interviews"

    voiceover_files = set()
    interview_files = set()

    if voiceover_dir.exists():
        for f in voiceover_dir.iterdir():
            if f.suffix.lower() in VIDEO_EXTS:
                voiceover_files.add(f.name)

    if interviews_dir.exists():
        for f in interviews_dir.iterdir():
            if f.suffix.lower() in VIDEO_EXTS:
                interview_files.add(f.name)

    return voiceover_files, interview_files


# ─── Silence detection ─────────────────────────────────────────────────────

def detect_silences(video_path: Path) -> list[dict]:
    """Запускает ffmpeg silencedetect, возвращает [{start, end}, ...]."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", "silencedetect=noise=-30dB:d=0.3",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        print("Ошибка: ffmpeg не найден", file=sys.stderr)
        sys.exit(1)

    output = result.stderr
    silences = []
    starts = re.findall(r"silence_start:\s*([\d.]+)", output)
    ends = re.findall(r"silence_end:\s*([\d.]+)", output)

    for i in range(min(len(starts), len(ends))):
        silences.append({
            "start": float(starts[i]),
            "end": float(ends[i]),
        })

    return silences


def snap_to_silence(start: float, end: float, silences: list[dict],
                    window: float = 2.0,
                    min_start: float = 0.0,
                    max_end: float = float("inf")) -> tuple[float, float]:
    """Привязывает start к ближайшему silence_end до него, end — к ближайшему silence_start после.

    min_start / max_end — жёсткие ограничения: snapped_start не меньше min_start,
    snapped_end не больше max_end. Если в ограниченном окне нет подходящей тишины —
    fallback на оригинальный start / end (без snap)."""
    snapped_start = start
    snapped_end = end

    best_dist_start = window
    for s in silences:
        # silence_end до start (±0.1s допуск на перекрытие), не раньше min_start
        if s["end"] < min_start:
            continue
        dist = max(0, start - s["end"])
        if s["end"] <= start + 0.1 and dist < best_dist_start:
            best_dist_start = dist
            snapped_start = s["end"]

    best_dist_end = window
    for s in silences:
        # silence_start после end (±0.1s допуск на перекрытие), не позже max_end
        if s["start"] > max_end:
            continue
        dist = max(0, s["start"] - end)
        if s["start"] >= end - 0.1 and dist < best_dist_end:
            best_dist_end = dist
            snapped_end = s["start"]

    return round(snapped_start, 2), round(snapped_end, 2)


# ─── Команда: search ───────────────────────────────────────────────────────

def cmd_search(project_dir: Path) -> None:
    """Pass 1: поиск кандидатов для каждой строки сценария."""
    print(f"=== Поиск кандидатов: {project_dir.name} ===\n")

    script_lines = load_script(project_dir)
    transcripts = load_transcripts(project_dir)

    if not transcripts:
        print("Ошибка: транскрипты не найдены", file=sys.stderr)
        sys.exit(1)

    voiceover_files, interview_files = _get_speaker_files(project_dir)
    print(f"\nФайлы войсовера: {voiceover_files or '(не определены)'}")
    print(f"Файлы интервью: {interview_files or '(не определены)'}")
    print()

    rows_out = []
    stats = {"single": 0, "multiple": 0, "multi_part": 0, "partial": 0, "not_found": 0}

    for line in script_lines:
        speaker = line["speaker"]

        # Фильтруем транскрипты по спикеру
        if speaker == "slava" and voiceover_files:
            filtered = {k: v for k, v in transcripts.items() if k in voiceover_files}
        elif speaker == "hero" and interview_files:
            filtered = {k: v for k, v in transcripts.items() if k in interview_files}
        else:
            filtered = {}

        # Фолбэк: если после фильтрации пусто — ищем по всем
        if not filtered:
            filtered = transcripts

        result = find_quote_parts(line["text"], filtered)
        parts = result["parts"]
        unmatched = result["unmatched"]

        if not parts and unmatched:
            # Все предложения провалились — это not_found, а не partial.
            status = "not_found"
            stats["not_found"] += 1
        elif unmatched:
            status = "partial"
            stats["partial"] += 1
        elif len(parts) > 1:
            status = "multi_part"
            stats["multi_part"] += 1
        elif len(parts) == 1 and len(parts[0]["candidates"]) == 1:
            status = "single"
            stats["single"] += 1
        elif len(parts) == 1 and len(parts[0]["candidates"]) > 1:
            status = "multiple"
            stats["multiple"] += 1
        else:
            status = "not_found"
            stats["not_found"] += 1

        # Вывод
        if status == "single":
            c = parts[0]["candidates"][0]
            print(f"  ✓ Строка {line['row_idx']}: {fmt_tc(c['start'])} -> {fmt_tc(c['end'])} — {line['text'][:60]}")
        elif status == "multi_part":
            print(f"  ≈ Строка {line['row_idx']}: {len(parts)} частей — {line['text'][:60]}")
        elif status == "partial":
            print(f"  ⚠ Строка {line['row_idx']}: {len(parts)} найдено, {len(unmatched)} нет — {line['text'][:60]}")
        elif status == "multiple":
            locs = ", ".join(fmt_tc(c["start"]) for c in parts[0]["candidates"])
            print(f"  ? Строка {line['row_idx']}: {len(parts[0]['candidates'])} кандидатов [{locs}] — {line['text'][:60]}")
        else:
            print(f"  ✗ Строка {line['row_idx']}: НЕ НАЙДЕНО — {line['text'][:60]}")

        rows_out.append({
            "row_idx": line["row_idx"],
            "speaker": speaker,
            "col": line["col"],
            "text": line["text"],
            "parts": parts,
            "unmatched": unmatched,
            "mode": result["mode"],
            "status": status,
        })

    output = {
        "rows": rows_out,
        "stats": stats,
    }

    out_path = project_dir / "script" / "candidates.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n=== Статистика ===")
    print(f"  Single:     {stats['single']}")
    print(f"  Multiple:   {stats['multiple']}")
    print(f"  Multi-part: {stats.get('multi_part', 0)}")
    print(f"  Partial:    {stats.get('partial', 0)}")
    print(f"  Not found:  {stats['not_found']}")
    print(f"\nРезультат: {out_path}")


# ─── Команда: snap ─────────────────────────────────────────────────────────

def _get_chosen_parts(row: dict) -> list[dict]:
    """Возвращает список chosen_parts из строки verified.json.

    Поддерживает оба формата:
    - новый: row["chosen_parts"] = [{file, start, end, text?}, ...]
    - старый: row["chosen"] = {file, start, end} → нормализуется в список из одного элемента.
    """
    chosen_parts = row.get("chosen_parts")
    if chosen_parts is not None:
        return [p for p in chosen_parts if p and p.get("file")]
    chosen = row.get("chosen")
    if chosen and chosen.get("file"):
        return [chosen]
    return []


def cmd_snap(project_dir: Path) -> None:
    """Pass 3: привязка таймкодов к паузам (тишине)."""
    print(f"=== Привязка к тишине: {project_dir.name} ===\n")

    verified_path = project_dir / "script" / "verified.json"
    if not verified_path.exists():
        print(f"Ошибка: не найден {verified_path}", file=sys.stderr)
        sys.exit(1)

    with open(verified_path, "r", encoding="utf-8") as f:
        verified = json.load(f)

    # Собираем уникальные файлы из всех частей всех строк.
    files_needed = set()
    for row in verified["rows"]:
        parts = _get_chosen_parts(row)
        for p in parts:
            if p.get("file"):
                files_needed.add(p["file"])

    # Определяем где искать видеофайлы
    raw_dirs = [
        project_dir / "raw" / "voiceover",
        project_dir / "raw" / "interviews",
        project_dir / "raw",
    ]

    # Детектим тишину для каждого файла
    silence_cache: dict[str, list[dict]] = {}
    for fname in sorted(files_needed):
        video_path = None
        for d in raw_dirs:
            candidate = d / fname
            if candidate.exists():
                video_path = candidate
                break
        if not video_path:
            print(f"  Внимание: файл {fname} не найден, пропускаем")
            continue
        print(f"  Детект тишины: {fname}...")
        silence_cache[fname] = detect_silences(video_path)
        print(f"    Найдено пауз: {len(silence_cache[fname])}")

    # Загружаем CSV для записи
    csv_path = project_dir / "script" / "script.csv"
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        csv_rows = list(reader)

    # Привязываем таймкоды
    for row in verified["rows"]:
        parts = _get_chosen_parts(row)
        if not parts:
            continue

        snapped_parts: list[tuple[str, float, float]] = []
        for i, p in enumerate(parts):
            fname = p.get("file")
            if not fname:
                continue

            # Ближайший предыдущий парт в том же файле (внутри строки)
            prev = next((q for q in reversed(parts[:i]) if q.get("file") == fname), None)
            # Ближайший следующий парт в том же файле (внутри строки)
            nxt = next((q for q in parts[i+1:] if q.get("file") == fname), None)

            min_start = prev["end"] if prev else 0.0
            max_end = nxt["start"] if nxt else float("inf")

            # Защита от уже пересекающихся word-границ в verified.json
            if min_start > p["start"]:
                print(f"  Внимание: строка {row['row_idx']} — word-границы соседних частей пересекаются "
                      f"(prev.end={min_start} > p.start={p['start']}), снимаем нижнее ограничение")
                min_start = 0.0
            if max_end < p["end"]:
                print(f"  Внимание: строка {row['row_idx']} — word-границы соседних частей пересекаются "
                      f"(nxt.start={max_end} < p.end={p['end']}), снимаем верхнее ограничение")
                max_end = float("inf")

            silences = silence_cache.get(fname, [])
            ss, se = snap_to_silence(p["start"], p["end"], silences,
                                     min_start=min_start, max_end=max_end)
            snapped_parts.append((fname, ss, se))

        if not snapped_parts:
            continue

        # Формат: "file: MM:SS.ss — MM:SS.ss" на часть, разделитель " || ".
        tc_strs = [f"{fn}: {fmt_tc(ss)} — {fmt_tc(se)}" for fn, ss, se in snapped_parts]
        tc_str = " || ".join(tc_strs)

        ridx = row["row_idx"]
        tc_col = row.get("col", 1)
        csv_idx = ridx - 1  # 1-based → 0-based
        if csv_idx < len(csv_rows):
            while len(csv_rows[csv_idx]) <= tc_col:
                csv_rows[csv_idx].append("")
            csv_rows[csv_idx][tc_col] = tc_str

        preview = tc_str if len(tc_str) <= 80 else tc_str[:77] + "..."
        print(f"  Строка {ridx}: {len(snapped_parts)} часть(и) — {preview}")

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_rows)

    print(f"\nОбновлён: {csv_path}")


# ─── Команда: compact ──────────────────────────────────────────────────────

def cmd_compact(project_dir: Path) -> None:
    """Генерирует words_compact.txt из каждого transcript.json."""
    print(f"=== Генерация words_compact.txt: {project_dir.name} ===\n")

    tr_dir = project_dir / "transcripts"
    if not tr_dir.exists():
        print(f"Ошибка: не найдена папка {tr_dir}", file=sys.stderr)
        sys.exit(1)

    for jp in sorted(tr_dir.glob("*.transcript.json")):
        with open(jp, "r", encoding="utf-8") as f:
            data = json.load(f)

        all_words = []
        for seg in data.get("segments", []):
            all_words.extend(seg.get("words", []))

        if not all_words:
            print(f"  Пропущен {jp.name}: нет слов")
            continue

        out_path = tr_dir / jp.name.replace(".transcript.json", ".words_compact.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            for idx, w in enumerate(all_words):
                start = w.get("start", 0.0)
                end = w.get("end", 0.0)
                word = w.get("word", "")
                f.write(f"{idx:5d} {start:8.2f}-{end:8.2f} {word}\n")

        print(f"  {out_path.name}: {len(all_words)} слов")

    print("\nГотово.")


# ─── main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Сопоставление реплик сценария с таймкодами транскриптов"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_search = subparsers.add_parser("search", help="Pass 1: поиск кандидатов")
    p_search.add_argument("project_dir", type=Path, help="Путь к папке проекта")

    p_snap = subparsers.add_parser("snap", help="Pass 3: привязка к тишине")
    p_snap.add_argument("project_dir", type=Path, help="Путь к папке проекта")

    p_compact = subparsers.add_parser("compact", help="Генерация words_compact.txt")
    p_compact.add_argument("project_dir", type=Path, help="Путь к папке проекта")

    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    if not project_dir.exists():
        print(f"Ошибка: папка {project_dir} не существует", file=sys.stderr)
        sys.exit(1)

    if args.command == "search":
        cmd_search(project_dir)
    elif args.command == "snap":
        cmd_snap(project_dir)
    elif args.command == "compact":
        cmd_compact(project_dir)


if __name__ == "__main__":
    main()
