from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explainer_studio.cli import main
from explainer_studio.theme import _contrast, extract_theme


class ThemeFromImagesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.previous_home = os.environ.get("EXPLAINER_STUDIO_HOME")
        os.environ["EXPLAINER_STUDIO_HOME"] = str(self.root / "studio")
        self.addCleanup(self.restore_home)
        self.image = self.root / "brand.png"
        image = Image.new("RGBA", (64, 64), "white")
        ImageDraw.Draw(image).rectangle((0, 0, 31, 63), fill="#0866CC")
        ImageDraw.Draw(image).rectangle((32, 0, 63, 31), fill="#F2C400")
        image.save(self.image)

    def restore_home(self):
        if self.previous_home is None:
            os.environ.pop("EXPLAINER_STUDIO_HOME", None)
        else:
            os.environ["EXPLAINER_STUDIO_HOME"] = self.previous_home

    def test_extracts_project_colors_with_readable_accent(self):
        colors = extract_theme([self.image])

        self.assertEqual(set(colors), {"background", "ink", "accent"})
        self.assertTrue(all(len(value) == 7 and value.startswith("#") for value in colors.values()))
        accent = tuple(int(colors["accent"][index:index + 2], 16) for index in (1, 3, 5))
        background = tuple(int(colors["background"][index:index + 2], 16) for index in (1, 3, 5))
        self.assertGreaterEqual(_contrast(accent, background), 4.5)

    def test_init_applies_palette_without_changing_profile(self):
        profile_path = Path(os.environ["EXPLAINER_STUDIO_HOME"]) / "profile.json"
        profile_path.parent.mkdir(parents=True)
        profile = {
            "brand": "Acme", "language": "en", "aivee_home": str(self.root / "aivee"),
            "colors": {"background": "#FFFFFF", "ink": "#111111", "accent": "#3366CC"},
        }
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        project = self.root / "film"
        data = project / "studio-data" / "explainer"
        data.mkdir(parents=True)
        created = {"project": str(project), "studioData": str(data)}
        with patch("explainer_studio.engine.create_aivee_project", return_value=created):
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["init", "film", "--theme-from", str(self.image)]), 0)

        saved = json.loads((data / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["colors"], extract_theme([self.image]))
        self.assertEqual(json.loads(profile_path.read_text(encoding="utf-8")), profile)

    def test_missing_image_fails_before_project_creation(self):
        profile_path = Path(os.environ["EXPLAINER_STUDIO_HOME"]) / "profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(json.dumps({"colors": {}}), encoding="utf-8")
        with patch("explainer_studio.engine.create_aivee_project") as create:
            with redirect_stdout(StringIO()):
                result = main(["init", "film", "--theme-from", str(self.root / "missing.png"), "--json"])
            self.assertEqual(result, 1)
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
