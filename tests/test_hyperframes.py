"""Unit tests for the optional HTML/GSAP export path."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from explainer_studio.hyperframes import export_hyperframes
from explainer_studio.render import storyboard_hash
from explainer_studio.common import ProjectError


class HyperFramesExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "assets" / "voice.wav").write_bytes(b"dummy")
        (self.root / "project.json").write_text(json.dumps({
            "voice": "assets/voice.wav", "width": 1920, "height": 1080,
            "colors": {"background": "#ffffff", "ink": "#111111", "accent": "#3355ff"}
        }))
        board = {"scenes": [
            {"start": 0, "end": 2, "headline": "<Safe> & sound", "body": "A simple example"},
            {"start": 2, "end": 4, "headline": "Next", "body": "A second scene"}
        ]}
        board["approved"] = True
        board["approval_hash"] = storyboard_hash(board)
        (self.root / "storyboard.json").write_text(json.dumps(board))
        (self.root / "words.json").write_text(json.dumps([
            {"start": 0, "end": 1, "text": "Hello"},
            {"start": 2, "end": 3, "text": "world"}
        ]))

    @patch("explainer_studio.hyperframes.validate_words")
    @patch("explainer_studio.hyperframes.validate_storyboard")
    @patch("explainer_studio.hyperframes.probe_duration", return_value=4)
    def test_export_preserves_timing_and_escapes_content(self, *_):
        target = export_hyperframes(self.root, portrait=True)
        html = (target / "index.html").read_text()
        package = json.loads((target / "package.json").read_text())
        self.assertIn("data-width=\"1080\"", html)
        self.assertIn("&lt;Safe&gt; &amp; sound", html)
        self.assertIn('data-start="2.0000"', html)
        self.assertIn('window.__timelines["explainer-studio"]', html)
        self.assertIn('gsap.timeline({paused:true})', html)
        self.assertEqual(package["dependencies"]["hyperframes"], "0.7.109")
        self.assertEqual(package["dependencies"]["gsap"], "3.14.2")
        with self.assertRaises(ProjectError):
            export_hyperframes(self.root, portrait=True)

    def test_unapproved_storyboard_rejected(self):
        board = json.loads((self.root / "storyboard.json").read_text())
        board["approved"] = False
        (self.root / "storyboard.json").write_text(json.dumps(board))
        with self.assertRaisesRegex(ProjectError, "not approved"):
            export_hyperframes(self.root)
