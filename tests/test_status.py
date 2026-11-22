"""Status reports project stage, file paths, and a gated next command."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.cli import _step_crosses_review_gate, command_step, default_render_name, main
from explainer_studio.common import file_hash
from explainer_studio.status import FINAL_RENDERS, PREVIEW_RENDERS
from explainer_studio.timing import storyboard_hash


KEYS = {"ok", "command", "data", "next_steps", "error"}


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.previous = os.environ.get("EXPLAINER_STUDIO_HOME")
        os.environ["EXPLAINER_STUDIO_HOME"] = str(self.home)
        self.root = self.home / "film"
        self.data = self.root / "studio-data" / "explainer"
        self.data.mkdir(parents=True)
        self.voice = self.root / "assets" / "narration.mp3"
        self.voice.parent.mkdir()
        self.script = self.data / "script.txt"
        self.words = self.data / "words.json"

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

    def assert_result(self, payload, ok):
        self.assertEqual(set(payload), KEYS)
        self.assertIs(payload["ok"], ok)
        self.assertEqual(payload["command"], "status")
        self.assertIsInstance(payload["data"], dict)
        self.assertIsInstance(payload["next_steps"], list)
        self.assertTrue(all(not _step_crosses_review_gate(step) for step in payload["next_steps"]))
        joined = " ".join(payload["next_steps"])
        self.assertNotIn(" approve ", f" {joined} ")
        self.assertNotIn(" init ", f" {joined} ")
        if ok:
            self.assertIsNone(payload["error"])
        else:
            self.assertTrue(payload["error"])

    def write_project(self, voice="assets/narration.mp3"):
        (self.data / "project.json").write_text(json.dumps({"version": 1, "voice": voice}), encoding="utf-8")

    def write_voice(self):
        self.voice.write_bytes(b"voice")

    def write_words(self, text="Hello"):
        self.words.write_text(json.dumps([{"text": text, "start": 0.1, "end": 0.4}]), encoding="utf-8")

    def write_script(self, text="Hello there."):
        self.script.write_text(text, encoding="utf-8")

    def write_board(self, *, approved=False, words_hash=None, script_hash=None):
        self.write_script()
        if not self.words.is_file():
            self.write_words()
        if not self.voice.is_file():
            self.write_voice()
        board = {
            "version": 1,
            "approved": False,
            "scenes": [{"start": 0, "end": 1, "headline": "Hello"}],
            "source": {
                "script_sha256": file_hash(self.script) if script_hash is None else script_hash,
                "voice_sha256": file_hash(self.voice),
                "words_sha256": file_hash(self.words) if words_hash is None else words_hash,
            },
        }
        if approved:
            board["approved"] = True
            board["approval_hash"] = storyboard_hash(board)
        (self.data / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
        return board

    def render(self, name: str):
        path = self.root / "renders" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"mp4")
        return path

    def status(self, *extra: str):
        code, out, err = self.invoke("status", "--json", str(self.root), *extra)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, code == 0)
        return code, payload

    def test_default_render_names_match_the_renderer(self):
        self.assertEqual(PREVIEW_RENDERS, (
            default_render_name(preview=True, portrait=False),
            default_render_name(preview=True, portrait=True),
        ))
        self.assertEqual(FINAL_RENDERS, (
            default_render_name(preview=False, portrait=False),
            default_render_name(preview=False, portrait=True),
        ))

    def test_missing_project_is_a_json_error(self):
        missing = self.home / "missing"
        code, out, err = self.invoke("status", "--json", str(missing))
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, False)
        self.assertIn("project not found", payload["error"])
        self.assertEqual(payload["next_steps"], [])
        code, out, err = self.invoke("status", str(missing))
        self.assertEqual(code, 1)
        self.assertIn("error:", err)
        self.assertNotIn('"ok"', out)

    def test_empty_project_waits_for_narration(self):
        self.write_project()
        code, payload = self.status()
        self.assertEqual(code, 0)
        stages = payload["data"]["stages"]
        self.assertEqual(list(stages), ["voice", "words", "storyboard", "approved", "preview", "final"])
        self.assertTrue(all(stage["done"] is False and stage["paths"] == [] for stage in stages.values()))
        self.assertFalse(payload["data"]["voice_attached"])
        self.assertNotIn("review_gate", payload["data"])
        self.assertEqual(payload["next_steps"], [])
        code, out, err = self.invoke("status", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("voice: not done", out)
        self.assertIn("next: attach narration", out)
        self.assertNotIn('"ok"', out)
        self.assertNotIn("explainer approve", out)
        self.assertNotIn("explainer init", out)

    def test_each_stage_names_the_next_safe_command(self):
        self.write_project()
        self.write_voice()
        code, payload = self.status()
        self.assertEqual(code, 0)
        self.assertTrue(payload["data"]["stages"]["voice"]["done"])
        self.assertEqual(payload["data"]["stages"]["voice"]["paths"], [str(self.voice)])
        self.assertEqual(payload["next_steps"], [command_step("transcribe", str(self.root.resolve()))])

        self.write_words()
        _, payload = self.status()
        self.assertTrue(payload["data"]["stages"]["words"]["done"])
        self.assertEqual(payload["data"]["stages"]["words"]["paths"], [str(self.words)])
        self.assertEqual(payload["next_steps"], [command_step("storyboard", str(self.root.resolve()))])

        self.write_board(approved=False)
        _, payload = self.status()
        board = str(self.data / "storyboard.json")
        self.assertTrue(payload["data"]["stages"]["storyboard"]["done"])
        self.assertEqual(payload["data"]["stages"]["storyboard"]["paths"], [board])
        self.assertFalse(payload["data"]["stages"]["approved"]["done"])
        self.assertEqual(payload["data"]["stages"]["approved"]["paths"], [board])
        self.assertEqual(payload["data"]["review_gate"], "storyboard")
        self.assertEqual(payload["next_steps"], [])
        _, out, _ = self.invoke("status", str(self.root))
        self.assertIn("next: review the storyboard in chat", out)
        self.assertNotIn("explainer approve", out)
        self.assertNotIn("explainer render", out)

        self.write_board(approved=True)
        _, payload = self.status()
        self.assertTrue(payload["data"]["stages"]["approved"]["done"])
        self.assertNotIn("review_gate", payload["data"])
        self.assertEqual(payload["next_steps"], [command_step("render", str(self.root.resolve()), "--preview")])

        draft = self.render("draft-engine.mp4")
        portrait = self.render("draft-portrait-engine.mp4")
        _, payload = self.status()
        self.assertEqual(payload["data"]["stages"]["preview"]["paths"], [str(draft), str(portrait)])
        self.assertEqual(payload["data"]["review_gate"], "preview")
        self.assertEqual(
            payload["next_steps"],
            [command_step("contact-sheet", str(self.root.resolve()), str(draft))],
        )
        self.assertEqual(payload["next_steps"][0].split()[1], "contact-sheet")

        final = self.render("final-engine.mp4")
        self.render("final-portrait-engine.mp4")
        self.render("previous.mp4")
        _, payload = self.status()
        self.assertEqual(payload["data"]["stages"]["final"]["paths"], [
            str(final), str(self.root / "renders" / "final-portrait-engine.mp4"),
        ])
        self.assertNotIn(str(self.root / "renders" / "previous.mp4"), payload["data"]["stages"]["final"]["paths"])
        self.assertNotIn("review_gate", payload["data"])
        self.assertEqual(payload["next_steps"], [command_step("check", str(self.root.resolve()), str(final))])

    def test_preview_before_approval_does_not_open_a_final_render(self):
        self.write_project()
        self.write_voice()
        self.write_words()
        self.write_board(approved=False)
        self.render("draft-engine.mp4")
        _, payload = self.status()
        self.assertTrue(payload["data"]["stages"]["preview"]["done"])
        self.assertFalse(payload["data"]["stages"]["approved"]["done"])
        self.assertEqual(payload["data"]["review_gate"], "storyboard")
        self.assertEqual(payload["next_steps"], [])

    def test_changed_words_wait_for_review_and_a_changed_script_rebuilds(self):
        self.write_project()
        self.write_voice()
        self.write_words()
        self.write_board(approved=True, words_hash="stale")
        _, payload = self.status()
        self.assertTrue(payload["data"]["stages"]["storyboard"]["done"])
        self.assertFalse(payload["data"]["stages"]["approved"]["done"])
        self.assertEqual(payload["data"]["review_gate"], "storyboard")
        self.assertEqual(payload["next_steps"], [])

        self.write_board(approved=True)
        board = json.loads((self.data / "storyboard.json").read_text(encoding="utf-8"))
        board["approval_hash"] = "stale"
        (self.data / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
        _, payload = self.status()
        self.assertFalse(payload["data"]["stages"]["approved"]["done"])
        self.assertEqual(payload["data"]["review_gate"], "storyboard")
        self.assertEqual(payload["next_steps"], [])

        self.write_board(approved=True, script_hash="stale")
        _, payload = self.status()
        self.assertFalse(payload["data"]["stages"]["storyboard"]["done"])
        self.assertFalse(payload["data"]["stages"]["approved"]["done"])
        self.assertEqual(payload["next_steps"], [command_step("storyboard", str(self.root.resolve()))])
        self.assertNotIn("review_gate", payload["data"])

    def test_a_final_file_without_a_draft_is_checked(self):
        self.write_project()
        self.write_voice()
        self.write_words()
        self.write_board(approved=True)
        final = self.render("final-portrait-engine.mp4")
        _, payload = self.status()
        self.assertFalse(payload["data"]["stages"]["preview"]["done"])
        self.assertEqual(payload["data"]["stages"]["final"]["paths"], [str(final)])
        self.assertEqual(payload["next_steps"], [command_step("check", str(self.root.resolve()), str(final))])

    def test_legacy_project_files_live_at_the_root(self):
        legacy = self.home / "legacy"
        legacy.mkdir()
        voice = legacy / "assets" / "voice.mp3"
        voice.parent.mkdir()
        voice.write_bytes(b"voice")
        (legacy / "project.json").write_text(json.dumps({"voice": "assets/voice.mp3"}), encoding="utf-8")
        code, out, err = self.invoke("status", "--json", str(legacy))
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assert_result(payload, True)
        self.assertEqual(payload["data"]["stages"]["voice"]["paths"], [str(voice)])
        self.assertEqual(payload["next_steps"], [command_step("transcribe", str(legacy.resolve()))])

    def test_invalid_words_are_not_done(self):
        self.write_project()
        self.write_voice()
        self.words.write_text("{", encoding="utf-8")
        _, payload = self.status()
        self.assertEqual(payload["data"]["stages"]["words"]["paths"], [str(self.words)])
        self.assertFalse(payload["data"]["stages"]["words"]["done"])
        self.assertEqual(payload["next_steps"], [command_step("transcribe", str(self.root.resolve()))])

    def test_usage_error_uses_the_schema(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(["status", "--json"])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assert_result(payload, False)


if __name__ == "__main__":
    unittest.main()
