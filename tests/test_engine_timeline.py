import json
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.audio import map_phonetic_cues, phonetic_mouth_track
from explainer_studio.common import ProjectError
from explainer_studio.engine import avatar_intervals


class EngineTimelineTest(unittest.TestCase):
    def test_phonetic_cues_map_to_the_sample_pack_states(self):
        cues = [
            {"start": 0.0, "end": 0.2, "value": "A"},
            {"start": 0.2, "end": 0.4, "value": "D"},
            {"start": 0.4, "end": 0.6, "value": "X"},
        ]

        self.assertEqual(map_phonetic_cues(cues, 0.6), ["closed"] * 3 + ["wide"] * 3 + ["rest"] * 3)
        with self.assertRaises(ProjectError):
            map_phonetic_cues([{"start": 0, "end": 0.1, "value": "Y"}], 0.2)
        with self.assertRaises(ProjectError):
            map_phonetic_cues(cues, 0)

    def test_phonetic_adapter_converts_audio_and_maps_rhubarb_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)

            def generate_cues(arguments, **_):
                cue_path = Path(arguments[arguments.index("--output") + 1])
                cue_path.write_text(json.dumps({"mouthCues": [
                    {"start": 0, "end": 0.2, "value": "A"},
                    {"start": 0.2, "end": 0.4, "value": "X"},
                ]}), encoding="utf-8")

            with patch("explainer_studio.audio.TemporaryDirectory", return_value=nullcontext(str(work))), patch(
                "explainer_studio.audio.run",
            ) as convert_audio, patch(
                "explainer_studio.audio.subprocess.run", side_effect=generate_cues,
            ) as run_rhubarb:
                states = phonetic_mouth_track(work / "voice.mp3", 0.4, work, "rhubarb")

        convert_audio.assert_called_once()
        self.assertEqual(states, ["closed"] * 3 + ["rest"] * 3)
        self.assertIn("--recognizer", run_rhubarb.call_args.args[0])

    def test_avatar_intervals_merge_matching_frames_and_trim_final_frame(self):
        keys = [
            ("idle", "rest", False),
            ("idle", "rest", False),
            ("idle", "open", False),
            ("idle", "open", False),
            ("point", "rest", True),
        ]

        self.assertEqual(
            avatar_intervals(keys, 10, 0.43),
            [
                {"pose": "idle", "mouth": "rest", "blink": False, "start": 0.0, "end": 0.2},
                {"pose": "idle", "mouth": "open", "blink": False, "start": 0.2, "end": 0.4},
                {"pose": "point", "mouth": "rest", "blink": True, "start": 0.4, "end": 0.43},
            ],
        )


if __name__ == "__main__":
    unittest.main()
