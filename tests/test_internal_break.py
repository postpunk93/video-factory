"""Тесты merged-word detection (B7 — обход Whisper-артефакта)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_scripts"))

from match_timecodes import find_internal_break  # noqa: E402


class TestFindInternalBreak(unittest.TestCase):
    def test_short_word_no_change(self):
        """Слово короче 1.0с — не подозрительное, границы не двигаются."""
        word_start = {"start": 10.0, "end": 10.4, "word": "На"}
        word_end = {"start": 15.0, "end": 15.5, "word": "видео"}
        new_start, new_end = find_internal_break(
            file_path=None,
            word_at_start=word_start,
            word_at_end=word_end,
            current_start=10.0,
            current_end=15.5,
            silencedetect_fn=lambda *args, **kwargs: self.fail(
                "silencedetect не должен вызываться"),
        )
        self.assertEqual(new_start, 10.0)
        self.assertEqual(new_end, 15.5)

    def test_long_start_word_with_pause_shifts_start(self):
        """Длинное first_word с паузой внутри — start сдвигается к её концу."""
        word_start = {"start": 38.99, "end": 40.58, "word": "На"}  # 1.59с
        word_end = {"start": 43.08, "end": 44.08, "word": "когтеточек."}

        def fake_silencedetect(path, t_start, t_end):
            if t_start == 38.99 and t_end == 40.58:
                return [{"start": 40.40, "end": 40.50}]
            return []

        new_start, new_end = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_end,
            current_start=38.99,
            current_end=44.08,
            silencedetect_fn=fake_silencedetect,
        )
        self.assertAlmostEqual(new_start, 40.50)
        self.assertEqual(new_end, 44.08)

    def test_long_end_word_with_pause_shifts_end(self):
        """Длинное last_word с паузой внутри — end сдвигается к её началу."""
        word_start = {"start": 100.0, "end": 100.3, "word": "Слово"}
        word_end = {"start": 105.0, "end": 107.5, "word": "длинное"}  # 2.5с

        def fake_silencedetect(path, t_start, t_end):
            if t_start == 105.0 and t_end == 107.5:
                return [{"start": 106.0, "end": 106.2}]
            return []

        new_start, new_end = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_end,
            current_start=100.0,
            current_end=107.5,
            silencedetect_fn=fake_silencedetect,
        )
        self.assertEqual(new_start, 100.0)
        self.assertAlmostEqual(new_end, 106.0)

    def test_long_word_no_pause_inside_fallback(self):
        """Длинное слово, но silencedetect не нашёл — возвращаются оригиналы."""
        word_start = {"start": 10.0, "end": 12.0, "word": "Длинное"}
        new_start, new_end = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_start,
            current_start=10.0,
            current_end=12.0,
            silencedetect_fn=lambda *args, **kwargs: [],
        )
        self.assertEqual(new_start, 10.0)
        self.assertEqual(new_end, 12.0)

    def test_multiple_internal_pauses_picks_last_for_start(self):
        """Несколько внутренних пауз — для start берём последнюю."""
        word_start = {"start": 0.0, "end": 3.0, "word": "X"}

        def fake(path, t_start, t_end):
            return [
                {"start": 0.5, "end": 0.7},
                {"start": 1.5, "end": 1.8},
                {"start": 2.5, "end": 2.7},
            ]

        new_start, _ = find_internal_break(
            file_path=Path("/fake.mov"),
            word_at_start=word_start,
            word_at_end=word_start,
            current_start=0.0,
            current_end=3.0,
            silencedetect_fn=fake,
        )
        self.assertAlmostEqual(new_start, 2.7)


if __name__ == "__main__":
    unittest.main()
