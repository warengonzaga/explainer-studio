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
from explainer_studio.common import ProjectError
from explainer_studio.engine import _check_reels_box, _visual_layers


class StudioSafetyTest(unittest.TestCase):
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
        _check_reels_box(0.067, 0.13, 0.753, 0.74, "test")
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


if __name__ == "__main__":
    unittest.main()
