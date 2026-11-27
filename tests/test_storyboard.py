"""Storyboard headline shortening."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.timing import build_storyboard, scene_headline


class StoryboardHeadlineTest(unittest.TestCase):
    def test_keeps_a_question_that_fits_on_a_phrase_boundary(self):
        text = "Oo, sa device mo tumatakbo yung agent?"
        self.assertEqual(scene_headline(text), text)
        longer = f"{text} Ito ay mahaba pa."
        self.assertEqual(scene_headline(longer), text)

    def test_keeps_a_question_mark_before_a_closing_quote(self):
        text = 'She asked, "tumatakbo yung agent?" Then more words follow here.'
        self.assertEqual(scene_headline(text), 'She asked, "tumatakbo yung agent?"')

    def test_keeps_exclamation_and_stops_before_the_next_phrase(self):
        text = "Stop, tingnan mo ito ngayon! May iba pa dito."
        self.assertEqual(scene_headline(text), "Stop, tingnan mo ito ngayon!")

    def test_cuts_a_long_clause_on_a_word_boundary(self):
        words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta,", "theta"]
        self.assertEqual(scene_headline(" ".join(words)), "alpha beta gamma delta epsilon zeta eta")

    def test_does_not_treat_an_initialism_period_as_the_phrase_end(self):
        text = "Meet the U.S. team today and learn more now please"
        self.assertEqual(scene_headline(text), "Meet the U.S. team today and learn")

    def test_stops_at_the_latest_sentence_that_fits(self):
        text = "One. Two. Three more words follow after this point today."
        self.assertEqual(scene_headline(text), "One. Two.")

    def test_generated_emphasis_keeps_a_hyphenated_word(self):
        paragraph = "Open-source tools save time for everyone."
        spoken = ["Open", "source", "tools", "save", "time", "for", "everyone"]
        words = [
            {"text": text, "start": index / 10, "end": index / 10 + 0.05}
            for index, text in enumerate(spoken, start=1)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "project.json").write_text(json.dumps({"voice": "voice.wav"}), encoding="utf-8")
            (root / "voice.wav").write_bytes(b"voice")
            (root / "script.txt").write_text(paragraph + "\n", encoding="utf-8")
            (root / "words.json").write_text(json.dumps(words), encoding="utf-8")
            with patch("explainer_studio.timing.probe_duration", return_value=2):
                board = build_storyboard(root)
        self.assertEqual(board["scenes"][0]["emphasis"], ["Open-source"])
