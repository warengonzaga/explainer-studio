import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.common import ProjectError, file_hash
from explainer_studio.engine import _check_reels_box, portrait_regions
from explainer_studio.cli import main
from explainer_studio.templates import (
    add_scene_starter,
    avatar_region,
    caption_region,
    list_templates,
    scene_stage,
)


STARTERS = ("badge-callout", "before-after", "hook-title", "numbered-steps")
PIXELS = re.compile(r"\d*\.?\d+px\b")
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


def _overlaps(first, second) -> bool:
    return not (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )


class SceneStarterLibraryTest(unittest.TestCase):
    def test_library_lists_generic_starters_and_the_shot_plan(self):
        rows = {item["id"]: item for item in list_templates()}
        self.assertEqual(set(rows), {*STARTERS, "reel-shot-plan"})
        self.assertEqual(rows["reel-shot-plan"]["texts"], [])
        self.assertEqual([item["key"] for item in rows["hook-title"]["texts"]], ["kicker", "title", "support"])
        self.assertEqual([item["key"] for item in rows["numbered-steps"]["texts"]], ["step-1", "step-2", "step-3"])
        self.assertIn("scene-composition", (ROOT / "library" / "templates" / "reel-shot-plan" / "README.md").read_text(encoding="utf-8"))

    def test_starter_sources_have_no_pixel_sizes_colors_or_brand_names(self):
        banned = ("waren", "ossph", "philippines", "taglish")
        for starter in STARTERS:
            directory = ROOT / "library" / "templates" / starter
            scene = (directory / "scene.html").read_text(encoding="utf-8")
            self.assertIsNone(PIXELS.search(scene), starter)
            self.assertIsNone(HEX_COLOR.search(scene), starter)
            self.assertIn("window.__timelines.root", scene)
            self.assertIn("gsap.timeline({ paused: true })", scene)
            self.assertIn("const at = (fraction) => duration * fraction", scene)
            blob = "\n".join(path.read_text(encoding="utf-8") for path in directory.iterdir() if path.is_file())
            for word in banned:
                self.assertNotIn(word, blob.casefold(), starter)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the template script syntax check")
    def test_starter_scripts_have_valid_javascript_syntax(self):
        for starter in (*STARTERS, "reel-shot-plan"):
            scene = (ROOT / "library" / "templates" / starter / "scene.html").read_text(encoding="utf-8")
            script = re.search(r"<script>\s*(.*?)\s*</script>", scene, re.DOTALL).group(1)
            script = script.replace("{{COMPOSITION_ID}}", "root")
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "scene.js"
                path.write_text(script, encoding="utf-8")
                subprocess.run([shutil.which("node"), "--check", str(path)], check=True, capture_output=True, text=True)

    def test_stage_stays_clear_of_the_avatar_and_captions_for_both_formats(self):
        sizes = ((1920, 1080), (1080, 1920), (1080, 1080), (540, 960))
        for width, height in sizes:
            project = {"width": width, "height": height}
            caption = caption_region(project, width, height)
            stage = scene_stage(width, height, caption)
            avatar = avatar_region(width, height)
            self.assertFalse(_overlaps(stage, avatar), (width, height))
            self.assertFalse(_overlaps(stage, caption), (width, height))
            self.assertGreater(stage["width"], 0)
            self.assertGreater(stage["height"], 0)
            if height > width:
                self.assertEqual(stage, portrait_regions()["visual"])
                _check_reels_box(stage["x"], stage["y"], stage["width"], stage["height"], "scene stage")
            else:
                self.assertGreaterEqual(stage["height"], 0.3)

    def test_portrait_stage_rejects_a_caption_that_covers_it(self):
        visual = portrait_regions()["visual"]
        with self.assertRaisesRegex(ProjectError, "overlaps the avatar or captions"):
            scene_stage(1080, 1920, visual)


class SceneStarterCommandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.previous = os.environ.get("EXPLAINER_STUDIO_HOME")
        os.environ["EXPLAINER_STUDIO_HOME"] = str(self.home)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("EXPLAINER_STUDIO_HOME", None)
        else:
            os.environ["EXPLAINER_STUDIO_HOME"] = self.previous
        self.temp.cleanup()

    def invoke(self, *argv: str):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_result(self, payload, command, ok):
        self.assertEqual(set(payload), {"ok", "command", "data", "next_steps", "error"})
        self.assertIs(payload["ok"], ok)
        self.assertEqual(payload["command"], command)
        if ok:
            self.assertIsNone(payload["error"])
        else:
            self.assertTrue(payload["error"])

    def write_project(self, *, width=1920, height=1080, language="fil", colors=None, caption=None):
        root = self.home / "film"
        data = root / "studio-data" / "explainer"
        data.mkdir(parents=True)
        project = {
            "version": 1,
            "title": "film",
            "language": language,
            "width": width,
            "height": height,
            "colors": colors or {"background": "#112233", "ink": "#445566", "accent": "#778899"},
        }
        if caption is not None:
            project["caption"] = caption
        (data / "project.json").write_text(json.dumps(project), encoding="utf-8")
        return root, data

    def write_storyboard(self, root, data, *, words_sha=None):
        voice = root / "assets" / "voice.mp3"
        voice.parent.mkdir(parents=True, exist_ok=True)
        voice.write_bytes(b"voice")
        (data / "project.json").write_text(
            json.dumps({**json.loads((data / "project.json").read_text(encoding="utf-8")), "voice": "assets/voice.mp3"}),
            encoding="utf-8",
        )
        script = data / "script.txt"
        script.write_text("Hello", encoding="utf-8")
        words = data / "words.json"
        words.write_text(json.dumps([{"text": "Hello", "start": 0.1, "end": 0.5}]), encoding="utf-8")
        board = {
            "version": 1,
            "approved": True,
            "approval_hash": "stale",
            "scenes": [{"start": 0, "end": 1, "headline": "Hello"}],
            "source": {
                "script_sha256": file_hash(script),
                "voice_sha256": file_hash(voice),
                "words_sha256": words_sha if words_sha is not None else file_hash(words),
            },
        }
        (data / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
        return voice

    def test_templates_json_lists_starters(self):
        code, out, err = self.invoke("templates", "--json")
        self.assertEqual((code, err), (0, ""))
        payload = json.loads(out)
        self.assert_result(payload, "templates", True)
        self.assertEqual([item["id"] for item in payload["data"]["templates"]], [*STARTERS, "reel-shot-plan"])

    def test_add_template_fills_theme_duration_and_escapes_text(self):
        root, _ = self.write_project()
        code, out, err = self.invoke(
            "add-template", "--json", str(root), "hook-title", "--duration", "4.5",
            "--set", "title=<North & south>", "--set", "support=オープン",
        )
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assert_result(payload, "add-template", True)
        self.assertEqual(payload["data"]["path"], "compositions/scenes/hook-title/index.html")
        self.assertEqual(payload["data"]["duration"], 4.5)
        self.assertNotIn("review_gate", payload["data"])
        scene = (root / payload["data"]["path"]).read_text(encoding="utf-8")
        self.assertIn("lang=\"fil\"", scene)
        self.assertIn('data-duration="4.5"', scene)
        self.assertIn('data-width="1920"', scene)
        self.assertIn('data-height="1080"', scene)
        self.assertIn("#112233", scene)
        self.assertIn("#445566", scene)
        self.assertIn("#778899", scene)
        self.assertIn("&lt;North &amp; south&gt;", scene)
        self.assertIn("オープン", scene)
        self.assertNotIn("{{", scene)
        self.assertIsNone(PIXELS.search(scene))
        stage = scene_stage(1920, 1080, caption_region({"width": 1920, "height": 1080}, 1920, 1080))
        self.assertIn(f"--stage-x: {stage['x'] * 100:.4f}".rstrip("0").rstrip("."), scene[: scene.index("</main>")])

    def test_add_template_uses_the_portrait_stage(self):
        root, _ = self.write_project(width=1080, height=1920)
        code, out, err = self.invoke("add-template", "--json", str(root), "numbered-steps", "--duration", "3")
        self.assertEqual(code, 0, err or out)
        scene = (root / "compositions/scenes/numbered-steps/index.html").read_text(encoding="utf-8")
        visual = portrait_regions()["visual"]
        self.assertIn(f"--stage-y: {visual['y'] * 100:.4f}".rstrip("0").rstrip("."), scene)
        self.assertIn("First step", scene)
        self.assertNotIn("{{", scene)

    def test_add_template_attaches_a_storyboard_scene_and_refuses_to_overwrite_it(self):
        root, data = self.write_project()
        self.write_storyboard(root, data)
        with patch("explainer_studio.timing.probe_duration", return_value=1):
            code, out, err = self.invoke(
                "add-template", "--json", str(root), "badge-callout", "--scene", "1", "--set", "callout=Look here",
            )
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assert_result(payload, "add-template", True)
        self.assertEqual(payload["data"]["review_gate"], "storyboard")
        self.assertEqual(payload["data"]["duration"], 1)
        self.assertEqual(payload["next_steps"], [])
        board = json.loads((data / "storyboard.json").read_text(encoding="utf-8"))
        self.assertFalse(board["approved"])
        self.assertNotIn("approval_hash", board)
        self.assertEqual(board["scenes"][0]["composition"], "compositions/scenes/badge-callout/index.html")
        scene = (root / board["scenes"][0]["composition"]).read_text(encoding="utf-8")
        self.assertIn("Look here", scene)
        code, out, err = self.invoke("add-template", "--json", str(root), "badge-callout", "--duration", "2")
        self.assertEqual(code, 1)
        self.assertIn("already exists", json.loads(out)["error"])
        self.assertIn("Look here", scene)

    def test_failed_attach_removes_the_new_scene_file(self):
        root, data = self.write_project()
        self.write_storyboard(root, data, words_sha="stale")
        with patch("explainer_studio.timing.probe_duration", return_value=1):
            code, out, err = self.invoke("add-template", "--json", str(root), "before-after", "--scene", "1")
        self.assertEqual(code, 1, out)
        self.assertIn("word timings changed", json.loads(out)["error"])
        self.assertFalse((root / "compositions" / "scenes" / "before-after" / "index.html").exists())

    def test_add_template_rejects_conflicts_and_unknown_starters(self):
        root, _ = self.write_project(language="not a language")
        code, out, err = self.invoke("add-template", "--json", str(root), "missing", "--duration", "1")
        self.assertEqual(code, 1)
        self.assertIn("unknown scene starter", json.loads(out)["error"])
        code, out, err = self.invoke("add-template", "--json", str(root), "hook-title", "--duration", "1", "--scene", "1")
        self.assertEqual(code, 1)
        self.assertIn("omit --duration", json.loads(out)["error"])
        self.assertFalse((root / "compositions").exists())
        code, out, err = self.invoke("add-template", "--json", str(root), "hook-title", "--duration", "1", "--set", "brand=Acme")
        self.assertEqual(code, 1)
        self.assertIn("unknown text field", json.loads(out)["error"])
        code, out, err = self.invoke("add-template", "--json", str(root), "hook-title", "--duration", "1", "--name", "opener")
        self.assertEqual(code, 0, err or out)
        opener = (root / "compositions" / "scenes" / "opener" / "index.html").read_text(encoding="utf-8")
        self.assertIn('lang=""', opener)
        code, out, err = self.invoke("add-template", "--json", str(root), "reel-shot-plan", "--duration", "2", "--name", "shot")
        self.assertEqual(code, 0, err or out)
        scene = (root / "compositions" / "scenes" / "shot" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="root"', scene)
        self.assertIn('data-duration="2"', scene)
        self.assertIn('data-width="1920"', scene)
        self.assertNotIn("{{", scene)

    def test_direct_add_refuses_a_symlink_scene_path(self):
        root, _ = self.write_project()
        outside = self.home / "outside"
        outside.mkdir()
        (root / "compositions").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ProjectError, "symlink"):
            add_scene_starter(root, "hook-title", name=None, duration=1, texts={})
        self.assertFalse(any(outside.iterdir()))


if __name__ == "__main__":
    unittest.main()
