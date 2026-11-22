"""Tests for timestamp-based frame exports."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.cli import main, parse_still_times
from explainer_studio.common import ProjectError
from explainer_studio.quality import export_stills


def png_bytes(color):
    image = Image.new("RGB", (12, 8), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class StillsTest(unittest.TestCase):
    def test_parse_still_times_requires_unique_finite_seconds(self):
        self.assertEqual(parse_still_times("0.6, 4.9"), [0.6, 4.9])
        for value in ("", "nan", "-1", "0.6,0.6", ",,", ",".join(["1"] * 101)):
            with self.subTest(value=value[:20]), self.assertRaises(ProjectError):
                parse_still_times(value)

    def test_export_stills_writes_frames_and_optional_sheet(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            first, second = png_bytes("red"), png_bytes("blue")
            with patch("explainer_studio.quality.command", return_value="ffmpeg"), patch(
                "explainer_studio.quality.subprocess.run",
                side_effect=[SimpleNamespace(returncode=0, stdout=first), SimpleNamespace(returncode=0, stdout=second)],
            ) as run:
                result = export_stills(video, [0.6, 4.9], root / "stills", make_sheet=True)
            self.assertEqual(len(result["frames"]), 2)
            self.assertTrue(Path(result["frames"][0]["path"]).is_file())
            self.assertTrue(Path(result["contact_sheet"]).is_file())
            with Image.open(result["frames"][1]["path"]) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            self.assertEqual(run.call_args_list[0].args[0][run.call_args_list[0].args[0].index("-ss") + 1], "0.600000")

    def test_export_stills_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "stills"
            output.mkdir()
            existing = output / "frame-01-at-0.600s.png"
            existing.write_bytes(b"keep")
            with patch("explainer_studio.quality.subprocess.run") as run:
                with self.assertRaises(ProjectError):
                    export_stills(Path("video.mp4"), [0.6], output)
            run.assert_not_called()
            self.assertEqual(existing.read_bytes(), b"keep")

    def test_failed_export_removes_its_partial_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "stills"
            with patch("explainer_studio.quality.command", return_value="ffmpeg"), patch(
                "explainer_studio.quality.subprocess.run",
                side_effect=[SimpleNamespace(returncode=0, stdout=png_bytes("red")), SimpleNamespace(returncode=1, stdout=b"")],
            ):
                with self.assertRaises(ProjectError):
                    export_stills(root / "video.mp4", [0.6, 4.9], output)
            self.assertFalse(output.exists())

    def test_stills_cli_uses_latest_final_render_and_reports_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            renders = root / "renders"
            renders.mkdir()
            (renders / "draft-engine.mp4").write_bytes(b"draft")
            final = renders / "final-portrait-engine.mp4"
            final.write_bytes(b"final")
            report = {"video": str(final), "frames": [], "contact_sheet": None}
            stdout = io.StringIO()
            with patch("explainer_studio.cli.probe_duration", return_value=10), patch(
                "explainer_studio.quality.export_stills", return_value=report,
            ) as export, patch("sys.stdout", stdout):
                self.assertEqual(main(["stills", str(root), "--at", "0.6,4.9", "--json"]), 0)
            self.assertEqual(export.call_args.args[0], final.resolve())
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["command"], "stills")
            self.assertEqual(payload["data"]["video"], str(final))


if __name__ == "__main__":
    unittest.main()
