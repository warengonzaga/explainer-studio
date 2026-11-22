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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.cli import command_payload, command_step, main


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
        payload = command_payload("storyboard", {"scenes": 2}, ["explainer approve <project>"])
        self.assertEqual(list(payload), ["ok", "command", "data", "next_steps", "error"])
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["error"])
        self.assertEqual(command_step("render", "/tmp/my project", "--preview"), "explainer render '/tmp/my project' --preview")

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
        self.assertEqual(payload["next_steps"], ["explainer init <project>"])

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
        self.assertIsInstance(payload["next_steps"], list)

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


if __name__ == "__main__":
    unittest.main()
