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
from explainer_studio.common import ProjectError, file_hash
from explainer_studio.engine import _register_render_asset, avatar_intervals, avatar_keyframes, custom_scene_clips
from explainer_studio.timing import validate_words


class EngineTimelineTest(unittest.TestCase):
    def test_custom_scene_compositions_keep_storyboard_timing(self):
        scenes = [
            {"start": 0, "end": 2.5, "composition": "compositions/scenes/one/index.html"},
            {"start": 2.5, "end": 5},
            {"start": 5, "end": 9, "composition": "compositions/scenes/three/index.html"},
        ]
        self.assertEqual(custom_scene_clips(scenes), [
            {"id": "custom-scene-01", "composition": "compositions/scenes/one/index.html", "timelineStart": 0.0, "durationSeconds": 2.5},
            {"id": "custom-scene-03", "composition": "compositions/scenes/three/index.html", "timelineStart": 5.0, "durationSeconds": 4.0},
        ])

    def test_render_assets_reuse_stable_ids_and_relink_changed_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / "avatar.png"
            source.write_bytes(b"first render")
            assets = {}

            def engine_cli(_command, _cwd, args):
                asset_id = args[-1] if args[1] == "register" else args[-2]
                media_path = args[-2] if args[1] == "register" else args[-1]
                return json.dumps({"id": asset_id, "sha256": file_hash(Path(media_path))})

            with patch("explainer_studio.engine._engine_cli", side_effect=engine_cli) as cli:
                first = _register_render_asset(["node", "aivee"], project, source, "avatar-id", assets, set())
                same = _register_render_asset(["node", "aivee"], project, source, "avatar-id", assets, set())
                source.write_bytes(b"revised render")
                with self.assertRaisesRegex(ProjectError, "conflicts with existing project media"):
                    _register_render_asset(["node", "aivee"], project, source, "avatar-id", assets, set())
                revised = _register_render_asset(
                    ["node", "aivee"], project, source, "avatar-id", assets,
                    {"studio-render-avatar-id-png"},
                )

        expected_id = "studio-render-avatar-id-png"
        self.assertEqual(first["id"], expected_id)
        self.assertEqual(same["id"], expected_id)
        self.assertEqual(revised["id"], expected_id)
        self.assertEqual([call.args[2][1] for call in cli.call_args_list], ["register", "relink"])

    def test_word_timing_validation_rejects_negative_nonfinite_and_out_of_range(self):
        for word in (
            {"text": "hello", "start": -0.1, "end": 0.2},
            {"text": "hello", "start": float("nan"), "end": 0.2},
            {"text": "hello", "start": 2.8, "end": 3.1},
        ):
            with self.subTest(word=word), self.assertRaises(ProjectError):
                validate_words([word], 3)

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

    def test_closed_lip_shapes_include_puckered_f_and_follow_project_fps(self):
        cues = [
            {"start": 0.00, "end": 0.10, "value": "A"},
            {"start": 0.10, "end": 0.20, "value": "F"},
            {"start": 0.20, "end": 0.30, "value": "B"},
            {"start": 0.30, "end": 0.40, "value": "E"},
        ]
        states = map_phonetic_cues(cues, 0.4, rate=30)
        self.assertEqual(states[:3], ["closed"] * 3)
        self.assertEqual(states[3:6], ["closed"] * 3)
        self.assertEqual(states[6:9], ["small"] * 3)
        self.assertEqual(states[9:12], ["small"] * 3)
        # A 50 ms cue is one 15 Hz bucket, but it starts a frame later at 30 fps.
        late = [{"start": 0.05, "end": 0.10, "value": "D"}]
        self.assertEqual(map_phonetic_cues(late, 0.2)[0], "wide")
        self.assertEqual(map_phonetic_cues(late, 0.2, rate=30)[0], "rest")
        self.assertEqual(map_phonetic_cues(late, 0.2, rate=30)[1], "wide")

    def test_avatar_keyframes_sample_mouth_tracks_at_project_fps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "voice.wav").write_bytes(b"voice")
            with patch("explainer_studio.engine.phonetic_mouth_track", return_value=None) as phonetic, patch(
                "explainer_studio.engine.mouth_track", return_value=["small"] * 30,
            ) as loudness:
                keys = avatar_keyframes(
                    root, {"voice": "voice.wav"}, {"scenes": [{"end": 1.0, "pose": "idle"}]}, {}, 1.0, 30, root,
                )
        phonetic.assert_called_once()
        self.assertEqual(phonetic.call_args.kwargs["rate"], 30)
        loudness.assert_called_once_with(root / "voice.wav", 30, 1.0)
        self.assertEqual(len(keys), 30)
        self.assertTrue(all(mouth == "small" for _pose, mouth, _blink in keys))

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
                "explainer_studio.audio.command", return_value="ffmpeg",
            ), patch(
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
