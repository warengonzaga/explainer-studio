import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from explainer_studio.captions import (
    DEFAULT_CAPTION_STYLE,
    caption_options,
    emphasis_words_for_scene,
    font_stack,
    format_caption_defaults,
    keyword_emphasis_enabled,
    pick_emphasis_keywords,
    prepare_caption_emphasis,
    warn_missing_fonts,
)
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

    def test_vertical_defaults_use_shorter_lines_than_landscape(self):
        vertical = format_caption_defaults(portrait=True)
        landscape = format_caption_defaults(portrait=False)
        self.assertEqual(vertical["wordsPerLine"], 2)
        self.assertEqual(vertical["wordsPerCaption"], 6)
        self.assertEqual(vertical["fontSize"], 32)
        self.assertEqual(vertical["paddingPixels"], 22)
        self.assertEqual(landscape["wordsPerLine"], 3)
        self.assertGreater(landscape["fontSize"], vertical["fontSize"])

    def test_keyword_pick_keeps_the_longest_hyphenated_word(self):
        words = pick_emphasis_keywords("Use the open-source timeline", "timeline tools")
        self.assertEqual(words, ["open-source"])

    def test_keyword_pick_breaks_length_ties_by_earlier_word(self):
        self.assertEqual(pick_emphasis_keywords("alpha gamma", "delta"), ["alpha"])

    def test_keyword_pick_skips_short_words(self):
        self.assertEqual(pick_emphasis_keywords("to be or"), [])

    def test_explicit_emphasis_list_overrides_automatic_picking(self):
        scene = {"headline": "open-source timeline", "emphasis": ["AI", "timeline"]}
        self.assertEqual(emphasis_words_for_scene(scene), ["AI", "timeline"])
        self.assertEqual(emphasis_words_for_scene({"headline": "timeline tools", "emphasis": []}), [])
        self.assertEqual(emphasis_words_for_scene({"headline": "Ignored headline", "emphasis": "kept"}), ["kept"])

    def test_missing_emphasis_uses_the_headline_before_the_body(self):
        scene = {"headline": "Short hook", "body": "A much-longer-word follows later"}
        self.assertEqual(emphasis_words_for_scene(scene), ["Short"])

    def test_emphasis_can_be_turned_off_at_each_level(self):
        profile = {"caption": {"keywordEmphasis": False}}
        project = {"caption": {"keywordEmphasis": True}}
        scene = {"caption": {"keywordEmphasis": False}, "headline": "timeline"}
        self.assertFalse(keyword_emphasis_enabled(profile, {}))
        self.assertTrue(keyword_emphasis_enabled(profile, project))
        self.assertFalse(keyword_emphasis_enabled(profile, project, scene))
        options = prepare_caption_emphasis(
            {"wordHighlightColor": "#FFE45C", "keywordEmphasis": False, "emphasisColor": "#FF00AA"},
            {"headline": "timeline"},
            enabled=False,
        )
        self.assertNotIn("emphasisWords", options)
        self.assertNotIn("keywordEmphasis", options)

    def test_prepare_sends_emphasis_color_with_the_keyword(self):
        options = prepare_caption_emphasis(
            {"wordHighlightColor": "#FFE45C", "emphasisColor": "#00AAFF"},
            {"headline": "open-source tools"},
            enabled=True,
        )
        self.assertEqual(options["emphasisWords"], ["open-source"])
        self.assertEqual(options["emphasisColor"], "#00AAFF")

    def test_caption_options_do_not_leak_the_emphasis_switch(self):
        options = caption_options({}, {"caption": {"keywordEmphasis": False, "fontWeight": 700}})
        self.assertNotIn("keywordEmphasis", options)
        self.assertEqual(options["fontWeight"], 700)


if __name__ == "__main__":
    unittest.main()
