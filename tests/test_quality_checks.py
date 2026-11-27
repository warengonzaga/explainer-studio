"""Regression tests for encoded-frame and portrait composition QA."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from importlib.resources import as_file, files
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.common import ProjectError
from explainer_studio.quality import flicker_check, frame_diff, region_qa, region_qa_plan, safe_zone_check, safe_zone_preset
from explainer_studio.templates import avatar_region, caption_region
from explainer_studio.cli import command_step, main


class FrameProcess:
    def __init__(self, frames):
        self.stdout = io.BytesIO(b"".join(frames))

    def wait(self):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


class QualityChecksTest(unittest.TestCase):
    def test_frame_diff_normalizes_gray_frame_changes(self):
        self.assertEqual(frame_diff(bytes([0, 255]), bytes([255, 0])), 1)
        self.assertEqual(frame_diff(b"same", b"same"), 0)

    def test_flicker_check_finds_single_frame_strobe(self):
        dark = bytes([20]) * (96 * 96)
        bright = bytes([255]) * (96 * 96)
        with patch("explainer_studio.quality.command", return_value="ffmpeg"), patch(
            "explainer_studio.quality.subprocess.Popen", return_value=FrameProcess([dark, bright, dark, dark]),
        ):
            report = flicker_check(Path("render.mp4"))
        self.assertEqual(report["frames_scanned"], 4)
        self.assertFalse(report["pass"])
        self.assertEqual(report["findings"][0]["frame"], 1)

    def test_flicker_check_finds_a_localized_one_frame_blink(self):
        dark = bytes([20]) * (96 * 96)
        blink = bytearray(dark)
        blink[:100] = bytes([255]) * 100
        with patch("explainer_studio.quality.command", return_value="ffmpeg"), patch(
            "explainer_studio.quality.subprocess.Popen", return_value=FrameProcess([dark, bytes(blink), dark]),
        ):
            report = flicker_check(Path("render.mp4"))
        self.assertFalse(report["pass"])
        self.assertGreater(report["findings"][0]["changed_pixels_percent"], 1)

    def test_static_cut_is_not_reported_as_one_frame_flicker(self):
        dark = bytes([20]) * (96 * 96)
        bright = bytes([255]) * (96 * 96)
        with patch("explainer_studio.quality.command", return_value="ffmpeg"), patch(
            "explainer_studio.quality.subprocess.Popen", return_value=FrameProcess([dark, dark, bright]),
        ):
            report = flicker_check(Path("render.mp4"))
        self.assertTrue(report["pass"])

    def test_safe_zone_check_skips_without_custom_compositions(self):
        report = safe_zone_check(Path("/project"), {"width": 1080, "height": 1920}, {"scenes": []})
        self.assertEqual(report, {"applicable": False, "compositions": 0, "findings": [], "pass": True})

    def test_safe_check_command_returns_json_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "project.json").write_text('{"voice":"voice.wav"}', encoding="utf-8")
            (root / "voice.wav").write_bytes(b"voice")
            (root / "storyboard.json").write_text('{"scenes":[]}', encoding="utf-8")
            previous = os.environ.get("EXPLAINER_STUDIO_HOME")
            os.environ["EXPLAINER_STUDIO_HOME"] = temporary
            output = io.StringIO()
            try:
                with patch("explainer_studio.cli.probe_duration", return_value=1), patch(
                    "explainer_studio.timing.validate_storyboard",
                ), patch("explainer_studio.quality.safe_zone_check", return_value={
                    "applicable": False, "compositions": 0, "findings": [], "pass": True,
                }), patch("sys.stdout", output):
                    self.assertEqual(main(["safe-check", str(root), "--json"]), 0)
            finally:
                if previous is None:
                    os.environ.pop("EXPLAINER_STUDIO_HOME", None)
                else:
                    os.environ["EXPLAINER_STUDIO_HOME"] = previous
            result = json.loads(output.getvalue())
            self.assertEqual(result["command"], "safe-check")
            self.assertTrue(result["ok"])

    def test_check_command_keeps_media_summary_and_reports_quality_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "final.mp4"
            voice = root / "voice.wav"
            video.write_bytes(b"video")
            voice.write_bytes(b"voice")
            (root / "project.json").write_text(json.dumps({"voice": "voice.wav", "width": 1080, "height": 1920}), encoding="utf-8")
            (root / "storyboard.json").write_text('{"scenes":[]}', encoding="utf-8")
            ffprobe = {"streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ], "format": {"duration": "10", "format_name": "mp4"}}
            completed = SimpleNamespace(stdout=json.dumps(ffprobe))
            output = io.StringIO()
            previous = os.environ.get("EXPLAINER_STUDIO_HOME")
            os.environ["EXPLAINER_STUDIO_HOME"] = temporary
            try:
                with patch("explainer_studio.cli.probe_duration", return_value=10), patch(
                    "explainer_studio.cli.subprocess.run", return_value=completed,
                ), patch("explainer_studio.cli.command", return_value="ffprobe"), patch(
                    "explainer_studio.timing.validate_storyboard",
                ), patch("explainer_studio.cli._sync_check_available", return_value=False), patch(
                    "explainer_studio.quality.flicker_check", return_value={"frames_scanned": 300, "findings": [], "pass": True},
                ), patch("explainer_studio.quality.safe_zone_check", return_value={"applicable": False, "compositions": 0, "findings": [], "pass": True}), patch(
                    "explainer_studio.quality.region_qa", return_value={
                        "pass": True, "preset": "vertical-social", "regions": [{"id": "avatar"}],
                        "flicker": {"passed": True}, "safe_zone": {"passed": True},
                    },
                ), patch(
                    "sys.stdout", output,
                ):
                    self.assertEqual(main(["check", str(root), str(video), "--json"]), 0)
            finally:
                if previous is None:
                    os.environ.pop("EXPLAINER_STUDIO_HOME", None)
                else:
                    os.environ["EXPLAINER_STUDIO_HOME"] = previous
            result = json.loads(output.getvalue())
            self.assertEqual(result["data"]["video"], str(video))
            self.assertEqual(result["data"]["video_codec"], "h264")
            self.assertEqual(result["data"]["flicker"]["frames_scanned"], 300)
            self.assertTrue(result["data"]["region_qa"]["pass"])
            self.assertEqual(result["data"]["region_qa"]["preset"], "vertical-social")
            self.assertFalse(result["data"]["sync"]["checked"])
            self.assertEqual(result["next_steps"], [command_step("contact-sheet", str(root), str(video))])

    def test_safe_zone_check_runs_native_composition_sampler(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = {"applicable": True, "sample_rate": 15, "compositions": 1, "findings": [], "pass": True}
            completed = SimpleNamespace(returncode=0, stdout=json.dumps(expected), stderr="")
            seen = {}
            def run_sampler(args, **kwargs):
                seen["manifest"] = json.loads(Path(args[2]).read_text(encoding="utf-8"))
                seen["runner"] = Path(args[1])
                return completed
            with patch("explainer_studio.engine.resolve_aivee", return_value=(["node", "aivee.mjs"], temporary)), patch(
                "explainer_studio.engine._browser_env", return_value={"HYPERFRAMES_BROWSER_PATH": "chrome.exe"},
            ), patch("explainer_studio.quality.subprocess.run", side_effect=run_sampler):
                report = safe_zone_check(root, {"width": 1080, "height": 1920}, {"scenes": [
                    {"start": 0, "end": 1, "composition": "compositions/scenes/one/index.html"},
                ]})
            self.assertEqual(report, expected)
            manifest = seen["manifest"]
            self.assertEqual(manifest["width"], 1080)
            self.assertEqual(manifest["compositions"][0]["scene"], 1)
            self.assertEqual(manifest["compositions"][0]["duration"], 1)
            self.assertTrue(seen["runner"].is_file())
            self.assertEqual(seen["runner"].name, "safe_check.mjs")

    def test_safe_zone_preset_uses_vertical_social_for_nine_by_sixteen(self):
        self.assertEqual(safe_zone_preset(1080, 1920), "vertical-social")
        self.assertEqual(safe_zone_preset(540, 960), "vertical-social")
        self.assertEqual(safe_zone_preset(1920, 1080), "title-safe")
        self.assertEqual(safe_zone_preset(1080, 1350), "title-safe")

    def test_region_plan_uses_avatar_and_caption_layout(self):
        project = {"width": 1080, "height": 1920, "fps": 30, "caption": {"placement": {"x": 0.4, "width": 0.4}}}
        scenes = [
            {"start": 0, "end": 1, "headline": "One"},
            {"start": 1, "end": 2, "headline": "Two", "caption": {"y": 0.7, "height": 0.08}},
        ]
        plan = region_qa_plan(project, {"scenes": scenes}, 1080, 1920, fps="30/1")
        avatar = {key: round(value, 6) for key, value in avatar_region(1080, 1920).items()}
        first = {key: round(value, 6) for key, value in caption_region(project, 1080, 1920, scene=scenes[0]).items()}
        second = {key: round(value, 6) for key, value in caption_region(project, 1080, 1920, scene=scenes[1]).items()}
        self.assertEqual(plan["preset"], "vertical-social")
        self.assertEqual(plan["flicker"]["regions"][0], {"id": "avatar", **avatar})
        self.assertEqual(plan["flicker"]["regions"][1], {"id": "caption-1", **first})
        self.assertEqual(plan["flicker"]["regions"][2], {"id": "caption-2", **second})
        self.assertEqual(plan["boxes"]["fps"], "30/1")
        self.assertEqual(plan["boxes"]["boxes"][1]["id"], "caption-1")
        self.assertEqual(plan["boxes"]["boxes"][1]["timeSeconds"], 0)
        self.assertEqual(plan["boxes"]["boxes"][2]["durationSeconds"], 1)
        self.assertNotEqual(first, second)

    def test_region_qa_reports_pass_and_fail_from_aivee(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"version":"0.3.0"}', encoding="utf-8")
            project = {"width": 1920, "height": 1080, "fps": 30}
            board = {"scenes": [{"start": 0, "end": 1.5, "headline": "Open"}]}
            seen = {}

            def run_qa(args, **kwargs):
                if args[2] == "flicker":
                    seen["flicker"] = json.loads(Path(args[4]).read_text(encoding="utf-8"))
                    return SimpleNamespace(returncode=0, stdout=json.dumps({"passed": True, "regions": []}), stderr="")
                seen["boxes"] = json.loads(Path(args[3]).read_text(encoding="utf-8"))
                seen["safe"] = json.loads(Path(args[4]).read_text(encoding="utf-8"))
                return SimpleNamespace(returncode=1, stdout=json.dumps({"passed": False, "violations": [{"id": "caption"}]}), stderr="")

            with patch("explainer_studio.engine.resolve_aivee", return_value=(["aivee"], temporary)), patch(
                "explainer_studio.quality.subprocess.run", side_effect=run_qa,
            ), patch.dict(os.environ, {"EXPLAINER_STUDIO_HOME": temporary}):
                report = region_qa(root, project, board, root / "final.mp4", 1920, 1080, fps=30)
        self.assertFalse(report["pass"])
        self.assertEqual(report["preset"], "title-safe")
        self.assertEqual(seen["safe"], {"preset": "title-safe"})
        self.assertEqual(seen["flicker"]["regions"][0]["id"], "avatar")
        self.assertEqual(seen["boxes"]["width"], 1920)
        self.assertEqual(seen["boxes"]["boxes"][1]["id"], "caption")
        avatar = {key: round(value, 6) for key, value in avatar_region(1920, 1080).items()}
        self.assertEqual({key: seen["flicker"]["regions"][0][key] for key in avatar}, avatar)
        self.assertEqual(report["safe_zone"]["passed"], False)

    def test_region_qa_requires_aivee_0_3_0(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "package.json").write_text('{"version":"0.2.0"}', encoding="utf-8")
            with patch("explainer_studio.engine.resolve_aivee", return_value=(["aivee"], temporary)):
                with self.assertRaisesRegex(ProjectError, "region flicker and safe-zone checks"):
                    region_qa(
                        Path(temporary), {"fps": 30}, {"scenes": [{"start": 0, "end": 1}]},
                        Path(temporary) / "final.mp4", 1080, 1920,
                    )

    def test_check_command_fails_when_region_qa_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "final.mp4"
            video.write_bytes(b"video")
            (root / "voice.wav").write_bytes(b"voice")
            (root / "project.json").write_text(json.dumps({"voice": "voice.wav", "width": 1080, "height": 1920}), encoding="utf-8")
            (root / "storyboard.json").write_text('{"scenes":[]}', encoding="utf-8")
            ffprobe = {"streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ], "format": {"duration": "10", "format_name": "mp4"}}
            output = io.StringIO()
            previous = os.environ.get("EXPLAINER_STUDIO_HOME")
            os.environ["EXPLAINER_STUDIO_HOME"] = temporary
            try:
                with patch("explainer_studio.cli.probe_duration", return_value=10), patch(
                    "explainer_studio.cli.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(ffprobe)),
                ), patch("explainer_studio.cli.command", return_value="ffprobe"), patch(
                    "explainer_studio.timing.validate_storyboard",
                ), patch("explainer_studio.cli._sync_check_available", return_value=False), patch(
                    "explainer_studio.quality.flicker_check", return_value={"frames_scanned": 4, "findings": [], "pass": True},
                ), patch("explainer_studio.quality.safe_zone_check", return_value={"applicable": False, "findings": [], "pass": True}), patch(
                    "explainer_studio.quality.region_qa", return_value={"pass": False, "preset": "vertical-social", "flicker": {"passed": False}, "safe_zone": {"passed": True}},
                ), patch("sys.stdout", output):
                    self.assertEqual(main(["check", str(root), str(video), "--json"]), 1)
            finally:
                if previous is None:
                    os.environ.pop("EXPLAINER_STUDIO_HOME", None)
                else:
                    os.environ["EXPLAINER_STUDIO_HOME"] = previous
        result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("avatar or caption regions", result["error"])
        self.assertFalse(result["data"]["region_qa"]["pass"])
        self.assertTrue(result["data"]["flicker"]["pass"])

    def test_safe_check_runner_resolves_from_the_package(self):
        with as_file(files("explainer_studio").joinpath("scripts", "safe_check.mjs")) as path:
            script = Path(path)
            self.assertTrue(script.is_file())
            self.assertEqual(script.name, "safe_check.mjs")
            self.assertIn("puppeteer-core", script.read_text(encoding="utf-8"))

    def test_built_wheel_includes_safe_check_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", temporary, str(ROOT)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            wheels = list(Path(temporary).glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = [name for name in archive.namelist() if name.endswith("safe_check.mjs")]
                self.assertEqual(names, ["explainer_studio/scripts/safe_check.mjs"])
                script = archive.read(names[0]).decode("utf-8")
        self.assertIn("puppeteer-core", script)


if __name__ == "__main__":
    unittest.main()
