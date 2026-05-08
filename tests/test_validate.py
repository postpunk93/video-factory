"""Тесты overlap-validator (этап B2 video-use ideas)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_scripts"))

from match_timecodes import detect_overlaps  # noqa: E402


class TestDetectOverlaps(unittest.TestCase):
    def test_overlap_in_same_file(self):
        """Два парта в одной строке с одним file и пересечением — конфликт."""
        rows = [{
            "row_idx": 51,
            "chosen_parts": [
                {"file": "a.mov", "start": 100.0, "end": 110.0},
                {"file": "a.mov", "start": 109.0, "end": 115.0},
            ],
        }]
        overlaps = detect_overlaps(rows, min_overlap_ms=50)
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(overlaps[0]["row_idx"], 51)
        self.assertEqual(overlaps[0]["file"], "a.mov")
        self.assertAlmostEqual(overlaps[0]["intersection_s"], 1.0, places=2)

    def test_no_overlap_different_files(self):
        """Парты в разных файлах не оверлапятся, даже если по времени совпадают."""
        rows = [{
            "row_idx": 1,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 5.0},
                {"file": "b.mov", "start": 0.0, "end": 5.0},
            ],
        }]
        self.assertEqual(detect_overlaps(rows, min_overlap_ms=50), [])

    def test_below_min_overlap_threshold(self):
        """Оверлап < min_overlap_ms — игнорим (артефакт Whisper)."""
        rows = [{
            "row_idx": 2,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 5.020},
                {"file": "a.mov", "start": 5.000, "end": 10.0},  # 20ms оверлап
            ],
        }]
        self.assertEqual(detect_overlaps(rows, min_overlap_ms=50), [])

    def test_three_overlapping_parts(self):
        """N>2 пересекающихся партов — все пары репортятся."""
        rows = [{
            "row_idx": 80,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 2.0},
                {"file": "a.mov", "start": 1.0, "end": 3.0},
                {"file": "a.mov", "start": 2.5, "end": 4.0},
            ],
        }]
        overlaps = detect_overlaps(rows, min_overlap_ms=50)
        # пары (0,1), (1,2) — пересекаются; (0,2) — нет (2.0 vs 2.5)
        self.assertEqual(len(overlaps), 2)

    def test_clean_data(self):
        """Корректные данные — пустой список."""
        rows = [{
            "row_idx": 1,
            "chosen_parts": [
                {"file": "a.mov", "start": 0.0, "end": 5.0},
                {"file": "a.mov", "start": 6.0, "end": 10.0},
            ],
        }]
        self.assertEqual(detect_overlaps(rows, min_overlap_ms=50), [])


class TestDetectWithinWord(unittest.TestCase):
    def _words(self):
        # Транскрипт: 3 слова с известными границами
        return [
            {"word": "первое", "start": 0.0, "end": 0.5},
            {"word": "второе", "start": 0.7, "end": 1.2},
            {"word": "третье", "start": 1.5, "end": 2.0},
        ]

    def test_part_end_inside_word(self):
        """end парта попадает в середину слова → конфликт."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 22,
            "chosen_parts": [{"file": "a.mov", "start": 0.0, "end": 0.9}],
        }]
        transcripts = {"a.mov": self._words()}
        flags = detect_within_word(rows, transcripts, word_tol_ms=50)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["edge"], "end")
        self.assertEqual(flags[0]["word"], "второе")

    def test_part_start_on_boundary(self):
        """start парта на границе слова (в пределах допуска) → ок."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 1,
            "chosen_parts": [{"file": "a.mov", "start": 0.03, "end": 0.5}],
        }]  # 30ms от 0.0 — внутри ±50ms допуска
        transcripts = {"a.mov": self._words()}
        self.assertEqual(detect_within_word(rows, transcripts, word_tol_ms=50), [])

    def test_part_in_silence(self):
        """Граница парта в паузе между словами → ок."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 1,
            "chosen_parts": [{"file": "a.mov", "start": 0.6, "end": 1.35}],
        }]  # обе границы в паузах
        transcripts = {"a.mov": self._words()}
        self.assertEqual(detect_within_word(rows, transcripts, word_tol_ms=50), [])

    def test_missing_transcript(self):
        """Нет транскрипта для file → пропускаем (не падаем)."""
        from match_timecodes import detect_within_word
        rows = [{
            "row_idx": 1,
            "chosen_parts": [{"file": "missing.mov", "start": 0.0, "end": 5.0}],
        }]
        self.assertEqual(detect_within_word(rows, {}, word_tol_ms=50), [])


class TestValidateOrchestration(unittest.TestCase):
    def test_load_transcripts_for_validation(self):
        """Хелпер _load_transcripts_for_validation: читает *.transcript.json
        и возвращает dict[file_basename, list[word]]."""
        from match_timecodes import _load_transcripts_for_validation
        # Используем реальный проект, если есть
        proj = Path(__file__).resolve().parent.parent / "projects" / "2026-03-thermobags"
        if not proj.exists():
            self.skipTest("нет projects/2026-03-thermobags для теста")
        transcripts = _load_transcripts_for_validation(proj)
        self.assertIsInstance(transcripts, dict)
        # Хотя бы один файл с непустым списком слов
        self.assertTrue(any(len(v) > 0 for v in transcripts.values()))


if __name__ == "__main__":
    unittest.main()
