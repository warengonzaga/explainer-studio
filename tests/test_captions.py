import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explainer_studio.captions import DEFAULT_CAPTION_STYLE, caption_options, font_stack, warn_missing_fonts
from explainer_studio.common import ProjectError


class CaptionStyleTest(unittest.TestCase):
    def test_profile_style_and_placement_apply_without_project_duplication(self):
        options = caption_options({
            "caption": {
                "fontFamily": "Noto Sans",
                "wordHighlightColor": "#FFDD00",
                "placement": {"x": 0.2, "y": 0.3, "width": 0.6, "height": 0.1},
            },
        }, {})

        self.assertEqual(options["fontFamily"], "Noto Sans, sans-serif")
        self.assertEqual(options["wordHighlightColor"], "#FFDD00")
        self.assertEqual(options["textShadow"], DEFAULT_CAPTION_STYLE["textShadow"])
        self.assertEqual((options["x"], options["y"], options["width"], options["height"]), (0.2, 0.3, 0.6, 0.1))

    def test_project_values_can_override_profile_style_and_placement(self):
        options = caption_options(
            {"caption": {"fontFamily": "Arial", "placement": {"x": 0.2, "width": 0.7}}},
            {"caption": {"fontFamily": "Noto Sans", "placement": {"x": 0.4}, "wordHighlightColor": "#FFDD00"}},
        )

        self.assertEqual(options["fontFamily"], "Noto Sans, sans-serif")
        self.assertEqual(options["x"], 0.4)
        self.assertEqual(options["width"], 0.7)
        self.assertEqual(options["wordHighlightColor"], "#FFDD00")

    def test_font_warning_identifies_missing_configured_families(self):
        output = io.StringIO()
        with patch("explainer_studio.captions._font_families", return_value={"arial"}):
            warnings = warn_missing_fonts({"caption": {"fontFamily": "Arial"}, "hook_font_family": "Bebas Neue"}, stream=output)

        self.assertEqual(len(warnings), 1)
        self.assertIn("hook font 'Bebas Neue' is not installed", warnings[0])
        self.assertIn("Warning:", output.getvalue())

    def test_font_stack_rejects_css_declaration_injection(self):
        with self.assertRaisesRegex(ProjectError, "font family"):
            font_stack("Arial; color: red")


if __name__ == "__main__":
    unittest.main()
