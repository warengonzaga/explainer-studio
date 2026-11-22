"""Draft preview renders before storyboard approval."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.cli import default_render_name
from explainer_studio.common import ProjectError
from explainer_studio.engine import draft_mark_track, ensure_render_allowed
from explainer_studio.timing import storyboard_hash


def sample_board(*, approved: bool, current_hash: bool) -> dict:
    board = {"scenes": [{"headline": "Hi"}], "source": {"words_sha256": "abc"}, "approved": approved}
    board["approval_hash"] = storyboard_hash(board) if current_hash else "stale"
    return board


class RenderPreviewTest(unittest.TestCase):
    def test_preview_skips_approval_and_final_render_keeps_the_gate(self):
        unapproved = sample_board(approved=False, current_hash=False)
        ensure_render_allowed(unapproved, preview=True)
        with self.assertRaisesRegex(ProjectError, "storyboard is not approved"):
            ensure_render_allowed(unapproved, preview=False)
        stale = sample_board(approved=True, current_hash=False)
        with self.assertRaisesRegex(ProjectError, "storyboard is not approved"):
            ensure_render_allowed(stale, preview=False)
        ensure_render_allowed(stale, preview=True)
        ensure_render_allowed(sample_board(approved=True, current_hash=True), preview=False)

    def test_draft_output_is_named_and_labeled_as_a_draft(self):
        self.assertEqual(default_render_name(preview=True, portrait=False), "draft-engine.mp4")
        self.assertEqual(default_render_name(preview=True, portrait=True), "draft-portrait-engine.mp4")
        self.assertEqual(default_render_name(preview=False, portrait=False), "final-engine.mp4")
        clip = draft_mark_track(4.5, portrait=True, type_scale=1)["clips"][0]
        self.assertEqual(clip["text"], "DRAFT")
        self.assertEqual(clip["durationSeconds"], 4.5)
        self.assertEqual(draft_mark_track(4.5, portrait=False, type_scale=0.5)["clips"][0]["text"], "DRAFT")
