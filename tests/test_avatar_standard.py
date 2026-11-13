import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from explainer_studio.avatar import FORMAT_V1, draw_avatar, validate_pack
from explainer_studio.common import ProjectError


class AvatarStandardTest(unittest.TestCase):
    def make_pack(self, root: Path) -> Path:
        pack = root / "sample"
        pack.mkdir()
        (pack / "README.md").write_text("Sample avatar pack\n", encoding="utf-8")
        (pack / "LICENSE").write_text("Sample terms\n", encoding="utf-8")
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(pack / "preview.png")
        manifest = {
            "format_version": 1, "id": "sample", "name": "Sample", "version": "1.0.0",
            "creator": "Test", "license": "MIT", "license_file": "LICENSE",
            "sheets": {"poses": {}, "eyes": {}, "mouth": {}},
            "face": {"eyes": [20, 25, 24, 10], "mouth": [28, 40, 8, 6]},
        }
        sizes = {"poses": (64, 96), "eyes": (24, 10), "mouth": (8, 6)}
        for group, categories in FORMAT_V1.items():
            for category, names in categories.items():
                width, height = sizes[group]
                path = f"{group}/{category}.png"
                (pack / group).mkdir(exist_ok=True)
                sheet = Image.new("RGBA", (width * len(names), height), (0, 0, 0, 0))
                frames = {}
                for index, name in enumerate(sorted(names)):
                    rect = [index * width, 0, width, height]
                    frames[name] = rect
                    sheet.paste(Image.new("RGBA", (width, height), (255, 0, 0, 255)), (rect[0], 0))
                sheet.save(pack / path)
                manifest["sheets"][group][category] = {"path": path, "frames": frames}
        (pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return pack

    def test_valid_standard_pack_renders_layers(self):
        with tempfile.TemporaryDirectory() as temp:
            pack = self.make_pack(Path(temp))
            self.assertEqual(validate_pack(pack.parent, pack.name)["format_version"], 1)
            canvas = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            draw_avatar(canvas, pack.parent, {"avatar_pack": "sample"}, "point_viewer", "rest", 1.0, (0, 0, 200, 200))
            self.assertGreater(canvas.getchannel("A").getbbox()[2], 0)
            with self.assertRaises(ProjectError):
                validate_pack(pack.parent, "missing")

    def test_missing_required_frame_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            pack = self.make_pack(Path(temp))
            manifest_path = pack / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["sheets"]["eyes"]["emotion"]["frames"]["sad"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "sad"):
                validate_pack(pack.parent, pack.name)

    def test_legacy_user_pack_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            pack = Path(temp) / "legacy"
            pack.mkdir()
            (pack / "manifest.json").write_text('{"poses":{"idle":"idle.png"}}', encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "legacy avatar pack"):
                validate_pack(pack.parent, pack.name)


if __name__ == "__main__":
    unittest.main()
