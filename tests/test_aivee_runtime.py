import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.engine import ensure_aivee
from explainer_studio.common import ProjectError


class AiveeRuntimeTest(unittest.TestCase):
    @staticmethod
    def write_package(package: Path, version: str = "99.0.0") -> None:
        (package / "src").mkdir(parents=True, exist_ok=True)
        (package / "src" / "cli.mjs").write_text("", encoding="utf-8")
        (package / "package.json").write_text(json.dumps({
            "name": "aivee", "version": version, "bin": {"aivee": "src/cli.mjs"},
        }), encoding="utf-8")

    @staticmethod
    def capabilities(args):
        if args[-1] != "capabilities":
            return None
        return CompletedProcess(args, 0, json.dumps({
            "schemaVersion": 1,
            "node": {"supported": True},
            "render": {"requirementsAvailable": True, "outputs": {"mp4": {"defaultCodecAvailable": True}}},
        }), "")

    def test_reuses_compatible_global_npm_install_independent_of_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            global_root = Path(temporary) / "global" / "node_modules"
            package = global_root / "aivee"
            self.write_package(package)

            def run(args, **_):
                if args[1:] == ["--version"]:
                    return CompletedProcess(args, 0, "v22.22.2\n", "")
                if args[1:] == ["root", "-g"]:
                    return CompletedProcess(args, 0, f"{global_root}\n", "")
                if result := self.capabilities(args):
                    return result
                self.fail(f"unexpected command: {args}")

            with patch("explainer_studio.engine.shutil.which", side_effect=lambda name: f"{name}.exe"), patch(
                "explainer_studio.engine.subprocess.run", side_effect=run,
            ) as run_mock:
                command, package_root = ensure_aivee()

        self.assertEqual(command[0], "node.exe")
        self.assertEqual(os.path.normcase(command[1]), os.path.normcase(str(package / "src" / "cli.mjs")))
        self.assertEqual(os.path.normcase(package_root), os.path.normcase(str(package)))
        self.assertEqual(run_mock.call_count, 3)

    def test_installs_latest_globally_when_aivee_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            global_root = Path(temporary) / "global" / "node_modules"
            package = global_root / "aivee"
            install_args = None

            def run(args, **_):
                nonlocal install_args
                if args[1:] == ["--version"]:
                    return CompletedProcess(args, 0, "v22.22.2\n", "")
                if args[1:] == ["root", "-g"]:
                    return CompletedProcess(args, 0, f"{global_root}\n", "")
                if args[1:] == ["install", "--global", "aivee@latest"]:
                    install_args = args[1:]
                    self.write_package(package, "1.2.3")
                    return CompletedProcess(args, 0, "added package", "")
                if result := self.capabilities(args):
                    return result
                self.fail(f"unexpected command: {args}")

            with patch("explainer_studio.engine.shutil.which", side_effect=lambda name: f"{name}.exe"), patch(
                "explainer_studio.engine.subprocess.run", side_effect=run,
            ):
                command, package_root = ensure_aivee()

        self.assertEqual(install_args, ["install", "--global", "aivee@latest"])
        self.assertEqual(os.path.normcase(package_root), os.path.normcase(str(package)))
        self.assertEqual(os.path.normcase(command[1]), os.path.normcase(str(package / "src" / "cli.mjs")))

    def test_does_not_replace_incompatible_global_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            global_root = Path(temporary) / "global" / "node_modules"
            package = global_root / "aivee"
            self.write_package(package)
            commands = []

            def run(args, **_):
                commands.append(args)
                if args[1:] == ["--version"]:
                    return CompletedProcess(args, 0, "v22.22.2\n", "")
                if args[1:] == ["root", "-g"]:
                    return CompletedProcess(args, 0, f"{global_root}\n", "")
                if args[-1] == "capabilities":
                    return CompletedProcess(args, 0, '{"schemaVersion": 0}', "")
                self.fail(f"unexpected command: {args}")

            with patch("explainer_studio.engine.shutil.which", side_effect=lambda name: f"{name}.exe"), patch(
                "explainer_studio.engine.subprocess.run", side_effect=run,
            ):
                with self.assertRaisesRegex(ProjectError, "npm install --global aivee@latest"):
                    ensure_aivee()

        self.assertFalse(any("install" in args for args in commands))


if __name__ == "__main__":
    unittest.main()
