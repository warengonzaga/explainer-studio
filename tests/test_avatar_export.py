from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.avatar_export import export_avatar
from explainer_studio.common import ProjectError, file_hash


class AvatarExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "studio-project"
        self.data = self.source / "studio-data" / "explainer"
        self.voice = self.source / "assets" / "voice.wav"
        self.target = self.root / "native-engine"
        self.data.mkdir(parents=True)
        self.voice.parent.mkdir()
        self.target.mkdir()
        self.registered = []
        self.voice.write_bytes(b"studio narration")
        (self.data / "project.json").write_text(json.dumps({
            "voice": "assets/voice.wav", "width": 1080, "height": 1920, "fps": 30, "avatar_pack": None,
        }), encoding="utf-8")
        (self.data / "storyboard.json").write_text(json.dumps({
            "approved": True, "scenes": [{"start": 0, "end": 1, "pose": "idle"}],
        }), encoding="utf-8")
        (self.data / "words.json").write_text(json.dumps([{"text": "hello", "start": 0, "end": 0.5}]), encoding="utf-8")
        (self.target / "meta.json").write_text("{}", encoding="utf-8")
        (self.target / "timeline.json").write_text("{}", encoding="utf-8")
        self.keys = [("idle", "rest", False)] * 15 + [("idle", "open", False)] * 15
        self.patches = [
            patch("explainer_studio.avatar_export.probe_duration", return_value=1.0),
            patch("explainer_studio.avatar_export.validate_storyboard"),
            patch("explainer_studio.avatar_export.ensure_render_allowed"),
            patch("explainer_studio.avatar_export.validate_words"),
            patch("explainer_studio.avatar_export.avatar_keyframes", return_value=self.keys),
            patch("explainer_studio.avatar_export.list_project_assets", side_effect=lambda _target: {"assets": self.registered}),
            patch("explainer_studio.avatar_export.register_asset", side_effect=self.register_asset),
            patch("explainer_studio.avatar_export.draw_avatar", side_effect=self.draw_avatar),
        ]
        self.mocks = [item.start() for item in self.patches]

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    @staticmethod
    def draw_avatar(canvas, *_args):
        canvas.putpixel((0, 0), (255, 0, 0, 255))

    def register_asset(self, _target, source, asset_id):
        asset = {
            "id": asset_id,
            "path": f"assets/{asset_id}{source.suffix}",
            "sha256": file_hash(source),
        }
        self.registered.append(asset)
        return asset

    def test_export_writes_timed_crops_and_registers_voice_and_sprites(self):
        result = export_avatar(self.source, self.target, {})
        output = Path(result["output"])
        timing = json.loads((output / "timing.json").read_text(encoding="utf-8"))

        self.assertEqual(result["sprites"], 2)
        self.assertEqual(result["intervals"], 2)
        self.assertEqual((output / "narration.wav").read_bytes(), self.voice.read_bytes())
        self.assertEqual(json.loads((output / "words.json").read_text(encoding="utf-8"))[0]["text"], "hello")
        self.assertEqual(timing["canvas"], {"width": 1080, "height": 1920, "fps": 30})
        self.assertEqual(len(timing["intervals"]), 2)
        self.assertEqual(timing["intervals"][0]["end"], timing["intervals"][1]["start"])
        self.assertEqual(timing["intervals"][0]["asset_path"], timing["sprites"][0]["asset_path"])
        self.assertTrue(all(record["asset_id"] for record in timing["sprites"]))
        with Image.open(output / timing["sprites"][0]["file"]) as sprite:
            self.assertLess(sprite.width, timing["canvas"]["width"])
            self.assertLess(sprite.height, timing["canvas"]["height"])
            self.assertEqual(sprite.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(self.mocks[6].call_count, 2)  # identical sprite files share one registered AIVEE asset

    def test_export_requires_approved_storyboard_before_writing(self):
        self.mocks[2].side_effect = ProjectError("storyboard is not approved")
        with self.assertRaisesRegex(ProjectError, "not approved"):
            export_avatar(self.source, self.target, {})
        self.assertFalse((self.target / "studio-data" / "explainer" / "avatar-exports").exists())
        self.mocks[6].assert_not_called()

    def test_export_refuses_to_overwrite_an_existing_export(self):
        export_avatar(self.source, self.target, {})
        with self.assertRaisesRegex(ProjectError, "already exists"):
            export_avatar(self.source, self.target, {})

    def test_export_can_retry_after_aivee_registers_media_then_fails(self):
        def register_then_fail(target, source, asset_id):
            self.register_asset(target, source, asset_id)
            raise ProjectError("AIVEE lost the response after registering the asset")

        self.mocks[6].side_effect = register_then_fail
        with self.assertRaisesRegex(ProjectError, "lost the response"):
            export_avatar(self.source, self.target, {})
        exports = self.target / "studio-data" / "explainer" / "avatar-exports"
        self.assertFalse(list(exports.glob("*/")))

        self.mocks[6].side_effect = self.register_asset
        result = export_avatar(self.source, self.target, {})
        self.assertTrue((Path(result["output"]) / "timing.json").is_file())


if __name__ == "__main__":
    unittest.main()
