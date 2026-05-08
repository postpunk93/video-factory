"""Тесты pack-формата (этап B1 video-use ideas)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_scripts"))

from match_timecodes import pack_words_into_phrases  # noqa: E402


class TestPackWordsIntoPhrases(unittest.TestCase):
    def test_break_on_silence_threshold(self):
        """Разрыв на паузе >= silence_threshold."""
        words = [
            {"word": "первое", "start": 0.0, "end": 0.5},
            {"word": "слово", "start": 0.55, "end": 1.0},
            # пауза 0.6s >= 0.5s → разрыв
            {"word": "второе", "start": 1.6, "end": 2.0},
            {"word": "предложение", "start": 2.05, "end": 2.6},
        ]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 2)
        self.assertEqual(phrases[0]["text"], "первое слово")
        self.assertEqual(phrases[0]["start"], 0.0)
        self.assertEqual(phrases[0]["end"], 1.0)
        self.assertEqual(phrases[1]["text"], "второе предложение")

    def test_no_break_on_short_pause(self):
        """Пауза < threshold не разрывает."""
        words = [
            {"word": "одна", "start": 0.0, "end": 0.5},
            {"word": "фраза", "start": 0.7, "end": 1.0},  # пауза 0.2s < 0.5s
        ]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 1)
        self.assertEqual(phrases[0]["text"], "одна фраза")

    def test_break_on_speaker_change(self):
        """Смена speaker → разрыв даже без паузы."""
        words = [
            {"word": "первый", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"},
            {"word": "спикер", "start": 0.55, "end": 1.0, "speaker": "SPEAKER_00"},
            {"word": "второй", "start": 1.05, "end": 1.5, "speaker": "SPEAKER_01"},
        ]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 2)
        self.assertEqual(phrases[0]["speaker"], "SPEAKER_00")
        self.assertEqual(phrases[1]["speaker"], "SPEAKER_01")

    def test_no_speaker_field(self):
        """Если в словах нет speaker — поле в выводе None."""
        words = [{"word": "слово", "start": 0.0, "end": 0.5}]
        phrases = pack_words_into_phrases(words, silence_threshold=0.5)
        self.assertIsNone(phrases[0].get("speaker"))

    def test_empty_words(self):
        """Пустой вход → пустой выход."""
        self.assertEqual(pack_words_into_phrases([], silence_threshold=0.5), [])


class TestRenderPackedMarkdown(unittest.TestCase):
    def test_format_with_speaker(self):
        from match_timecodes import render_packed_markdown
        phrases = [
            {"start": 1.5, "end": 3.7, "text": "пример фразы", "speaker": "SPEAKER_00"},
        ]
        md = render_packed_markdown(phrases)
        self.assertIn("[00:01.50-00:03.70] S00 пример фразы", md)

    def test_format_without_speaker(self):
        from match_timecodes import render_packed_markdown
        phrases = [
            {"start": 0.0, "end": 1.0, "text": "без спикера", "speaker": None},
        ]
        md = render_packed_markdown(phrases)
        self.assertIn("[00:00.00-00:01.00] без спикера", md)
        self.assertNotIn(" S", md.replace(":", ""))  # никаких speaker-тегов


if __name__ == "__main__":
    unittest.main()
