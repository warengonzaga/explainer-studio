"""Launcher detection for a managed virtual environment."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "explainer.py"
sys.path.insert(0, str(ROOT / "src"))


def load_launcher():
    spec = importlib.util.spec_from_file_location("explainer_launcher", LAUNCHER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {LAUNCHER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load_launcher()


class LauncherVenvTest(unittest.TestCase):
    def make_symlinked_venv(self, home: Path) -> Path:
        venv = home / "venv"
        interpreter = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        interpreter.parent.mkdir(parents=True)
        base = Path(sys.executable).resolve().parent
        (venv / "pyvenv.cfg").write_text(
            f"home = {base}\ninclude-system-site-packages = false\n",
            encoding="utf-8",
        )
        try:
            interpreter.symlink_to(Path(sys.executable).resolve())
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        return interpreter

    def test_symlinked_interpreter_reexecs_once_into_the_managed_venv(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "home"
            interpreter = self.make_symlinked_venv(home)
            self.assertEqual(interpreter.resolve(), Path(sys.executable).resolve())
            child_prefix = Path(subprocess.check_output(
                [str(interpreter), "-c", "import sys; print(sys.prefix)"],
                text=True,
            ).strip())
            self.assertFalse(launcher.in_managed_venv(home, Path(sys.prefix)))
            self.assertTrue(launcher.in_managed_venv(home, child_prefix))
            linked = base / "linked-home"
            linked.symlink_to(home, target_is_directory=True)
            self.assertTrue(launcher.in_managed_venv(linked, child_prefix))

            calls = []

            def fake_run(args, **kwargs):
                calls.append(list(args))
                return subprocess.CompletedProcess(args, 0)

            with (
                patch.dict(os.environ, {"EXPLAINER_STUDIO_HOME": str(home)}),
                patch.object(launcher.sys, "prefix", sys.prefix),
                patch.object(launcher.sys, "argv", ["explainer.py", "transcribe", "demo"]),
                patch.object(launcher.subprocess, "run", side_effect=fake_run),
            ):
                with self.assertRaises(SystemExit) as raised:
                    launcher.launch()
            self.assertEqual(raised.exception.code, 0)
            self.assertEqual(calls, [
                [str(interpreter), "-c", "import explainer_studio"],
                [str(interpreter), str(LAUNCHER.resolve()), "transcribe", "demo"],
            ])

            with (
                patch.dict(os.environ, {"EXPLAINER_STUDIO_HOME": str(home)}),
                patch.object(launcher.sys, "prefix", str(child_prefix)),
                patch.object(launcher.subprocess, "run", side_effect=AssertionError("re-exec loop")),
                patch("explainer_studio.cli.main", return_value=0),
            ):
                with self.assertRaises(SystemExit) as raised:
                    launcher.launch()
            self.assertEqual(raised.exception.code, 0)

    def test_incomplete_managed_env_keeps_text_and_json_apart(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            self.make_symlinked_venv(home)

            def fake_run(args, **kwargs):
                return subprocess.CompletedProcess(args, 1)

            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, {"EXPLAINER_STUDIO_HOME": str(home)}),
                patch.object(launcher.sys, "prefix", sys.prefix),
                patch.object(launcher.sys, "argv", ["explainer.py", "doctor"]),
                patch.object(launcher.subprocess, "run", side_effect=fake_run),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as raised:
                    launcher.launch()
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("explainer bootstrap", stderr.getvalue())

            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, {"EXPLAINER_STUDIO_HOME": str(home)}),
                patch.object(launcher.sys, "prefix", sys.prefix),
                patch.object(launcher.sys, "argv", ["explainer.py", "doctor", "--json"]),
                patch.object(launcher.subprocess, "run", side_effect=fake_run),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                with self.assertRaises(SystemExit) as raised:
                    launcher.launch()
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(set(payload), {"ok", "command", "data", "next_steps", "error"})
            self.assertIs(payload["ok"], False)
            self.assertEqual(payload["command"], "doctor")
            self.assertEqual(payload["data"], {})
            self.assertEqual(payload["next_steps"], ["explainer bootstrap --json"])
            self.assertIn("bootstrap", payload["error"])
