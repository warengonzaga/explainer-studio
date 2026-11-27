import math
import random
import sys
import unittest
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.audio import amplitude_mouth_states, frame_levels
from explainer_studio.common import ProjectError


def _speech_stats(states: list[str], levels: list[float], rate: int, floor: float = 0.02) -> dict:
    """Mouth mix during speech, in the same shape as the v0.3.0 narration report."""
    speech = [index for index, level in enumerate(levels) if level >= floor]
    window = states[speech[0] : speech[-1] + 1]
    total = len(window)
    longest = current = 0
    for state in states:
        if state in {"open", "wide"}:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return {
        "open_wide": sum(state in {"open", "wide"} for state in window) / total,
        "small": sum(state == "small" for state in window) / total,
        "closed_rest": sum(state in {"closed", "rest"} for state in window) / total,
        "longest_frames": longest,
        "longest_seconds": longest / rate,
    }


def _synthetic_pcm(
    seconds: float = 12,
    sample_rate: int = 16000,
    syllables: float = 4.5,
    pulse: float = 0.16,
    valley_ratio: float = 0.78,
    peak: float = 0.5,
    pause_every: int = 10,
    pause: float = 0.12,
    flat: bool = False,
    seed: int = 3,
) -> array:
    """Close-mic compressed speech: syllable peaks sit only a little above the valleys."""
    rng = random.Random(seed)
    count = int(seconds * sample_rate)
    envelope = [0.0] * count
    if flat:
        for index in range(int(0.2 * sample_rate), int((seconds - 0.2) * sample_rate)):
            envelope[index] = 1.0
    else:
        cursor = 0.05
        syllable = 0
        while cursor < seconds - 0.05:
            if syllable and syllable % pause_every == 0:
                cursor += pause
            start = int((cursor - pulse / 2) * sample_rate)
            end = int((cursor + pulse / 2) * sample_rate)
            for index in range(max(0, start), min(count, end)):
                position = (index / sample_rate - (cursor - pulse / 2)) / pulse
                hump = 0.5 - 0.5 * math.cos(2 * math.pi * position)
                envelope[index] = max(envelope[index], valley_ratio + (1 - valley_ratio) * hump)
            cursor += 1 / syllables
            syllable += 1
    samples = array("h")
    for index in range(count):
        noise = rng.uniform(-1, 1)
        samples.append(max(-32767, min(32767, int(peak * envelope[index] * 32767 * noise))))
    return samples


def _track(samples: array, rate: int, sample_rate: int = 16000) -> tuple[list[str], list[float]]:
    frame_count = max(1, math.ceil(len(samples) / sample_rate * rate))
    levels = frame_levels(samples, frame_count, rate, sample_rate)
    return amplitude_mouth_states(levels, rate), levels


class MouthTrackTest(unittest.TestCase):
    def test_compressed_speech_opens_less_than_the_old_global_gate(self):
        states, levels = _track(_synthetic_pcm(), 30)
        stats = _speech_stats(states, levels, 30)
        self.assertLess(stats["open_wide"], 0.50)
        self.assertGreater(stats["open_wide"], 0.05)
        self.assertLessEqual(stats["longest_frames"], 4)
        self.assertLess(stats["longest_seconds"], 0.5)
        self.assertGreater(stats["small"] + stats["closed_rest"], 0.40)

    def test_flat_loud_region_does_not_stay_open(self):
        states, levels = _track(_synthetic_pcm(seconds=3, flat=True), 30)
        stats = _speech_stats(states, levels, 30)
        self.assertLess(stats["open_wide"], 0.25)
        self.assertLessEqual(stats["longest_frames"], 4)
        self.assertLess(stats["longest_seconds"], 0.5)

    def test_envelope_valleys_drop_to_closed_or_small(self):
        levels = [0.0] * 6 + [0.08, 0.16, 0.22, 0.16, 0.09, 0.16, 0.22, 0.16, 0.08] + [0.0] * 6
        states = amplitude_mouth_states(levels, 30)
        for index in (10, 14):
            self.assertIn(states[index], {"closed", "small"})
            self.assertNotIn(states[index], {"open", "wide"})
        self.assertIn(states[8], {"open", "wide"})
        self.assertIn(states[12], {"open", "wide"})

    def test_open_runs_stop_at_four_frames(self):
        states = amplitude_mouth_states([0.2] * 30, 30)
        run = current = 0
        for state in states:
            if state in {"open", "wide"}:
                current += 1
                run = max(run, current)
            else:
                current = 0
        self.assertLessEqual(run, 4)
        self.assertGreater(sum(state in {"open", "wide"} for state in states), 0)
        self.assertGreater(sum(state == "small" for state in states), 4)

    def test_one_frame_spike_does_not_hold_the_mouth_open(self):
        levels = [0.005] * 12 + [0.25] + [0.005] * 12
        states = amplitude_mouth_states(levels, 30)
        self.assertLessEqual(sum(state in {"open", "wide"} for state in states), 1)
        self.assertGreater(sum(state == "rest" for state in states), 20)

    def test_speech_onset_and_silence_stay_within_one_sample(self):
        silence, speech, bound = 6, 8, 1
        levels = [0.0] * silence + [0.20] * speech + [0.0] * silence
        states = amplitude_mouth_states(levels, 30)
        spoken = [index for index, state in enumerate(states) if state != "rest"]
        self.assertTrue(spoken)
        self.assertGreaterEqual(spoken[0], silence - bound)
        self.assertLessEqual(spoken[0], silence + bound)
        last_speech = silence + speech - 1
        self.assertGreaterEqual(spoken[-1], last_speech - bound)
        self.assertLessEqual(spoken[-1], last_speech + bound)
        self.assertTrue(all(state != "rest" for state in states[spoken[0] : spoken[-1] + 1]))
        self.assertTrue(all(state == "rest" for state in states[spoken[-1] + 1 :]))

    def test_rate_must_be_a_project_frame_rate(self):
        with self.assertRaises(ProjectError):
            amplitude_mouth_states([0.2], True)  # type: ignore[arg-type]
        with self.assertRaises(ProjectError):
            amplitude_mouth_states([0.2], 0)


if __name__ == "__main__":
    unittest.main()
