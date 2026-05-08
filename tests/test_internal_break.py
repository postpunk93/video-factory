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


if __name__ == "__main__":
    unittest.main()
