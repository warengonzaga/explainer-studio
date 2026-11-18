import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw

from explainer_studio.cli import _replace_avatar_pack
from explainer_studio.common import ProjectError, studio_data
from explainer_studio.engine import _check_reels_box, _visual_layers


class StudioSafetyTest(unittest.TestCase):
    def test_studio_data_uses_aivee_namespace_and_keeps_legacy_root_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            self.assertEqual(studio_data(root), root)
            namespace = root / "studio-data" / "explainer"
            namespace.mkdir(parents=True)
            (root / "project.json").write_text("{}", encoding="utf-8")
            self.assertEqual(studio_data(root), root)
            (namespace / "project.json").write_text("{}", encoding="utf-8")
            self.assertEqual(studio_data(root), namespace)

    def test_studio_data_rejects_a_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, outside = base / "project", base / "outside"
            root.mkdir()
            outside.mkdir()
            try:
                (root / "studio-data").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(ProjectError, "must not be symlinks"):
                studio_data(root)

    def test_transparent_layers_are_cropped_before_registering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            source = root / "diagram.png"
            Image.new("RGBA", (100, 100)).save(source)
            layers = root / "diagram.layers"
            layers.mkdir()
            layer = Image.new("RGBA", (100, 100))
            ImageDraw.Draw(layer).rectangle((25, 25, 74, 74), fill="black")
            layer.save(layers / "part.png")
            (layers / "manifest.json").write_text(json.dumps({"layers": [{"file": "part.png", "x": 0, "y": 0}]}), encoding="utf-8")
            asset_dir = root / "scratch"
            asset_dir.mkdir()

            result = _visual_layers(root, {
                "asset": "diagram.png", "start": 0, "duration": 2,
                "x": 0.2, "y": 0.2, "width": 0.5, "height": 0.5,
            }, (100, 100), asset_dir)

            path, cue = result[0]
            with Image.open(path) as cropped:
                self.assertEqual(cropped.size, (50, 50))
            self.assertAlmostEqual(cue["width"], 0.25)
            self.assertAlmostEqual(cue["x"], 0.325)

    def test_rejects_layer_directory_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, outside = base / "project", base / "outside"
            root.mkdir()
            outside.mkdir()
            Image.new("RGBA", (10, 10)).save(root / "diagram.png")
            (outside / "manifest.json").write_text(json.dumps({"layers": [{"file": "part.png", "x": 0, "y": 0}]}), encoding="utf-8")
            Image.new("RGBA", (10, 10), "black").save(outside / "part.png")
            try:
                (root / "diagram.layers").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(ProjectError, "must stay inside the project"):
                _visual_layers(root, {"asset": "diagram.png"}, (10, 10), base)

    def test_caption_and_visual_bounds_follow_reels_safe_area(self):
        _check_reels_box(0.093, 0.13, 0.727, 0.641, "test")
        with self.assertRaises(ProjectError):
            _check_reels_box(0.092, 0.2, 0.1, 0.1, "left edge")
        with self.assertRaises(ProjectError):
            _check_reels_box(0.2, 0.77, 0.1, 0.01, "bottom edge")
        with self.assertRaises(ProjectError):
            _check_reels_box(0.36, 0.4, 0.58, 0.1, "caption")

    def test_failed_avatar_copy_preserves_existing_profile_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            target = root / "assets" / "avatar"
            target.mkdir(parents=True)
            sentinel = target / "keep.txt"
            sentinel.write_text("existing pack", encoding="utf-8")
            with patch("explainer_studio.avatar.copy_pack", side_effect=OSError("copy failed")):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    _replace_avatar_pack(source, target)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing pack")

    def test_failed_avatar_copy_leaves_no_partial_library_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            target = root / "library" / "avatar"
            target.parent.mkdir()

            def fail_after_partial_copy(_source, stage):
                stage.mkdir()
                (stage / "partial.png").write_bytes(b"partial")
                raise OSError("copy failed")

            with patch("explainer_studio.avatar.copy_pack", side_effect=fail_after_partial_copy):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    _replace_avatar_pack(source, target)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob("avatar.stage-*")), [])


if __name__ == "__main__":
    unittest.main()
