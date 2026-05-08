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


if __name__ == "__main__":
    unittest.main()
