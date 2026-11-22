import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.avatar import avatar_box
from explainer_studio.engine import _check_reels_box, portrait_caption, portrait_regions


def _overlaps(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


class PortraitLayoutTest(unittest.TestCase):
    def test_portrait_bubble_does_not_overlap_the_visual(self):
        regions = portrait_regions()
        bubble, visual, avatar = regions["bubble"], regions["visual"], regions["avatar"]
        self.assertFalse(_overlaps(bubble, visual))
        self.assertFalse(_overlaps(bubble, avatar))
        self.assertFalse(_overlaps(visual, avatar))
        for name, box in regions.items():
            _check_reels_box(box["x"], box["y"], box["width"], box["height"], name)

        exits = {**visual, "x": visual["x"] - 0.015}
        motions = [exits]
        for shift_x, shift_y in (
            (0.025, min(0.035, visual["height"] * 0.12)),
            (-0.028, min(0.025, visual["height"] * 0.15)),
            (0.028, min(0.025, visual["height"] * 0.15)),
        ):
            motions.append({
                "x": visual["x"] + shift_x,
                "y": visual["y"] + shift_y,
                "width": visual["width"] * 0.88,
                "height": visual["height"] * 0.88,
            })
        for box in motions:
            _check_reels_box(box["x"], box["y"], box["width"], box["height"], "visual motion")
            self.assertFalse(_overlaps(box, bubble))
            self.assertFalse(_overlaps(box, avatar))

        for size in ((1080, 1920), (540, 960)):
            x, y, width, height = avatar_box(size)
            frame_w, frame_h = size
            _check_reels_box(x / frame_w, y / frame_h, width / frame_w, height / frame_h, "avatar")

    def test_landscape_avatar_box_stays_put(self):
        self.assertEqual(avatar_box((1920, 1080)), (48, 313, 595, 626))

    def test_portrait_caption_fits_a_long_taglish_line(self):
        caption = portrait_caption()
        bubble = portrait_regions()["bubble"]
        words = "tumatakbo yung agent?".split()
        lines = [
            " ".join(words[index:index + caption["wordsPerLine"]])
            for index in range(0, len(words), caption["wordsPerLine"])
        ]
        longest = max(lines, key=len)
        # 0.66em matches a wide bold sans such as DejaVu Bold. AIVEE does not auto-fit.
        usable = bubble["width"] * 1080 - 2 * caption["paddingPixels"]
        self.assertLessEqual(len(longest) * caption["fontSize"] * 0.66, usable)
        line_count = math.ceil(caption["wordsPerCaption"] / caption["wordsPerLine"])
        line_box = caption["fontSize"] * 1.12
        gap = caption["fontSize"] * 0.08
        needed = line_count * line_box + (line_count - 1) * gap + 2 * caption["paddingPixels"]
        self.assertLessEqual(needed, bubble["height"] * 1920)
