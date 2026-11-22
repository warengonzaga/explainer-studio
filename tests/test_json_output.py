"""Stable --json results for explainer commands."""

import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.cli import (
    _doctor_steps,
    _step_crosses_review_gate,
    _ungated,
    command_payload,
    command_step,
    main,
)


KEYS = {"ok", "command", "data", "next_steps", "error"}


class JsonOutputTest(unittest.TestCase):
    def invoke(self, *argv: str):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

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

    def write_profile(self):
        path = self.home / "profile.json"
        path.write_text(json.dumps({"brand": "Acme", "language": "en"}), encoding="utf-8")

    def assert_result(self, payload, command, ok):
        self.assertEqual(set(payload), KEYS)
        self.assertIs(payload["ok"], ok)
        self.assertEqual(payload["command"], command)
        self.assertIsInstance(payload["data"], dict)
        self.assertIsInstance(payload["next_steps"], list)
        self.assertTrue(all(isinstance(step, str) for step in payload["next_steps"]))
        if ok:
            self.assertIsNone(payload["error"])
        else:
            self.assertTrue(payload["error"])

    def test_payload_keeps_the_documented_fields(self):
        payload = command_payload("transcribe", {"words": 2}, ["explainer storyboard /tmp/film"])
        self.assertEqual(list(payload), ["ok", "command", "data", "next_steps", "error"])
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["error"])
        self.assertEqual(command_step("render", "/tmp/my project", "--preview"), "explainer render '/tmp/my project' --preview")

    def test_next_steps_never_cross_review_gates(self):
        blocked = (
            "explainer approve /tmp/film",
            "explainer init demo",
            "explainer init <project>",
            "explainer render /tmp/film",
            "explainer render /tmp/film --portrait",
            "explainer render-engine /tmp/film",
        )
        for step in blocked:
            self.assertTrue(_step_crosses_review_gate(step), step)
            with self.assertRaises(RuntimeError):
                _ungated(step)
        safe = _ungated(
            "explainer setup",
            "explainer doctor",
            "explainer render /tmp/film --preview",
            "explainer render-engine /tmp/film --portrait --preview",
            command_step("contact-sheet", "/tmp/film", "/tmp/draft.mp4"),
            command_step("check", "/tmp/film", "/tmp/final.mp4"),
        )
        self.assertEqual(len(safe), 6)
        self.assertEqual(_doctor_steps([], True), [])
        self.assertEqual(_doctor_steps([], False), ["explainer setup"])
        self.assertEqual(
            _doctor_steps(["Pillow", "AIVEE (run `explainer install-engine`)"], False),
            ["explainer bootstrap", "explainer install-engine"],
        )

    def test_every_command_accepts_json_and_status_is_absent(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        names = re.search(r"\{([^{}]+)\}", stdout.getvalue()).group(1).split(",")
        self.assertIn("doctor", names)
        self.assertIn("profile", names)
        self.assertIn("storyboard", names)
        self.assertIn("render", names)
        self.assertNotIn("status", names)
        for name in names:
            help_out = io.StringIO()
            with redirect_stdout(help_out):
                with self.assertRaises(SystemExit) as raised:
                    main([name, "--help"])
            self.assertEqual(raised.exception.code, 0, name)
            self.assertIn("--json", help_out.getvalue(), name)

    def test_profile_json_reports_a_missing_profile(self):
        code, out, err = self.invoke("profile", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "profile", False)
        self.assertIn("explainer setup", payload["next_steps"])

    def test_profile_json_returns_saved_settings(self):
        self.write_profile()
        code, out, err = self.invoke("profile", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "profile", True)
        self.assertEqual(payload["data"]["brand"], "Acme")
        self.assertEqual(payload["next_steps"], [])

    def test_profile_without_json_stays_plain_text(self):
        code, out, err = self.invoke("profile")
        self.assertEqual(code, 1)
        self.assertIn("error:", err)
        self.assertNotIn('"ok"', out)
        self.write_profile()
        code, out, err = self.invoke("profile")
        self.assertEqual(code, 0)
        self.assertIn("Acme", out)
        self.assertNotIn('"command"', out)

    def test_doctor_json_uses_the_schema(self):
        code, out, err = self.invoke("doctor", "--json")
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "doctor", code == 0)
        self.assertIn("python", payload["data"])
        self.assertIn("missing", payload["data"])
        self.assertTrue(all(not _step_crosses_review_gate(step) for step in payload["next_steps"]))
        if payload["data"]["missing"]:
            self.assertNotEqual(code, 0)
            self.assertTrue(payload["error"])
        else:
            self.assertEqual(code, 0)

    def test_storyboard_and_render_json_errors_exit_nonzero(self):
        missing = str(self.home / "missing-project")
        for command in ("storyboard", "render"):
            if command == "render":
                self.write_profile()
            code, out, err = self.invoke(command, "--json", missing)
            self.assertEqual(code, 1, command)
            self.assertEqual(err, "", command)
            payload = json.loads(out)
            self.assert_result(payload, command, False)

    def test_engine_json_requires_an_aivee_command(self):
        code, out, err = self.invoke("engine", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "engine", False)
        self.assertIn("AIVEE command", payload["error"])

    def test_engine_json_after_the_command_stays_json(self):
        code, out, err = self.invoke("engine", "capabilities", "--json")
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "engine", code == 0)
        self.assertEqual(payload["next_steps"], [])

    def test_usage_errors_with_json_use_the_schema(self):
        cases = (
            (["storyboard", "--json"], "storyboard"),
            (["render", "--json"], "render"),
            (["profile", "--json", "--nope"], "profile"),
        )
        for argv, command in cases:
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(list(argv))
            self.assertEqual(raised.exception.code, 2, argv)
            self.assertEqual(stderr.getvalue(), "", argv)
            payload = json.loads(stdout.getvalue())
            self.assert_result(payload, command, False)

    def test_usage_errors_without_json_stay_plain(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(["storyboard"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("required", stderr.getvalue())
        self.assertNotIn('"ok"', stdout.getvalue())

    def test_storyboard_json_waits_for_review_and_plain_text_stays(self):
        root = self.home / "film"
        root.mkdir()
        with patch("explainer_studio.timing.build_storyboard", return_value={"scenes": [{}, {}]}):
            code, out, err = self.invoke("storyboard", str(root))
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            self.assertIn("review storyboard.json before approval", out)
            self.assertNotIn('"next_steps"', out)
            code, out, err = self.invoke("storyboard", "--json", str(root))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "storyboard", True)
        self.assertEqual(payload["data"]["scenes"], 2)
        self.assertEqual(payload["data"]["review_gate"], "storyboard")
        self.assertEqual(payload["next_steps"], [])

    def test_preview_json_reviews_before_a_final_render(self):
        self.write_profile()
        root = self.home / "film"
        root.mkdir()
        video = root / "renders" / "draft-engine.mp4"
        with patch("explainer_studio.engine.render_with_engine", return_value=video):
            code, out, err = self.invoke("render", "--preview", str(root))
            self.assertEqual(code, 0, err)
            self.assertEqual(out.strip(), str(video))
            self.assertNotIn('"ok"', out)
            code, out, err = self.invoke("render", "--json", "--preview", "--portrait", str(root))
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "render", True)
        self.assertEqual(payload["data"]["review_gate"], "preview")
        self.assertTrue(payload["data"]["preview"])
        self.assertTrue(payload["data"]["portrait"])
        self.assertEqual(payload["next_steps"], [command_step("contact-sheet", str(root.resolve()), str(video))])
        with patch("explainer_studio.engine.render_with_engine", return_value=root / "renders" / "final-engine.mp4"):
            code, out, err = self.invoke("render", "--json", str(root))
        payload = json.loads(out)
        self.assertEqual(code, 0, err)
        self.assert_result(payload, "render", True)
        self.assertNotIn("review_gate", payload["data"])
        self.assertFalse(payload["data"]["preview"])
        self.assertEqual(
            payload["next_steps"],
            [command_step("check", str(root.resolve()), str(root / "renders" / "final-engine.mp4"))],
        )

    def test_attach_avatar_json_previews_the_project(self):
        library = self.home / "library"
        library.mkdir()
        profile = {"brand": "Acme", "language": "en", "aivee_workspace": {"avatarPacks": str(library)}}
        (self.home / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        project = self.home / "film"
        data = project / "studio-data" / "explainer"
        data.mkdir(parents=True)
        (data / "project.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
        pack = self.home / "pack"
        pack.mkdir()
        import explainer_studio.avatar as avatar_module

        with patch.object(avatar_module, "validate_pack", return_value={"id": "emo", "name": "Emo"}), patch(
            "explainer_studio.cli._replace_avatar_pack", return_value=None,
        ):
            code, out, err = self.invoke("attach-avatar", str(project), str(pack))
            self.assertEqual(code, 0, err)
            self.assertIn("avatar attached:", out)
            self.assertNotIn('"avatar_pack"', out)
            code, out, err = self.invoke("attach-avatar", "--json", str(project), str(pack))
        self.assertEqual(code, 0, err or out)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "attach-avatar", True)
        pack_path = str((library / "emo").resolve())
        self.assertEqual(payload["data"]["avatar_pack"], pack_path)
        self.assertEqual(payload["next_steps"], [command_step("avatar-preview", str(project.resolve()))])
        self.assertNotIn(pack_path, payload["next_steps"][0])


if __name__ == "__main__":
    unittest.main()
