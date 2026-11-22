import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.audio import mouth_states


def _flips(states: list[str]) -> int:
    return sum(left != right for left, right in zip(states, states[1:]))


def _raw_state(level: float) -> str:
    return "rest" if level < .10 else "closed" if level < .22 else "small" if level < .42 else "open" if level < .72 else "wide"


class MouthTrackTest(unittest.TestCase):
    def test_boundary_chatter_flips_less_than_raw_thresholds(self):
        levels = [0.30, 0.18] * 24
        raw = [_raw_state(level) for level in levels]
        smooth = mouth_states(levels)
        self.assertGreater(_flips(raw), 40)
        self.assertLess(_flips(smooth), _flips(raw) // 4)
        self.assertEqual(len(smooth), len(levels))

    def test_speech_onset_and_silence_stay_within_one_sample(self):
        silence, speech, bound = 6, 8, 1
        levels = [0.0] * silence + [0.80] * speech + [0.0] * silence
        states = mouth_states(levels)
        spoken = [index for index, state in enumerate(states) if state != "rest"]
        self.assertTrue(spoken)
        self.assertGreaterEqual(spoken[0], silence - bound)
        self.assertLessEqual(spoken[0], silence + bound)
        last_speech = silence + speech - 1
        self.assertGreaterEqual(spoken[-1], last_speech - bound)
        self.assertLessEqual(spoken[-1], last_speech + bound)
        self.assertTrue(all(state != "rest" for state in states[spoken[0] : spoken[-1] + 1]))
        self.assertTrue(all(state == "rest" for state in states[spoken[-1] + 1 :]))
