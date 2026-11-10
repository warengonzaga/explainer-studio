import json
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.engine import AIVEE_VERSION, UNDICI_VERSION, ensure_aivee


class AiveeRuntimeTest(unittest.TestCase):
    def test_uses_compatible_global_npm_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            global_root = Path(temporary) / "global" / "node_modules"
            package = global_root / "aivee"
            (package / "src").mkdir(parents=True)
            (package / "src" / "cli.mjs").write_text("", encoding="utf-8")
            (package / "package.json").write_text(json.dumps({
                "name": "aivee", "version": AIVEE_VERSION, "bin": {"aivee": "src/cli.mjs"},
            }), encoding="utf-8")

            def run(args, **_):
                if args[1:] == ["--version"]:
                    return CompletedProcess(args, 0, "v22.22.2\n", "")
                if args[1:] == ["root", "-g"]:
                    return CompletedProcess(args, 0, f"{global_root}\n", "")
                self.fail(f"unexpected command: {args}")

            with patch("explainer_studio.engine.studio_home", return_value=Path(temporary) / "studio"), patch(
                "explainer_studio.engine.shutil.which", side_effect=lambda name: f"{name}.exe",
            ), patch("explainer_studio.engine.subprocess.run", side_effect=run) as run_mock:
                command, package_root = ensure_aivee()

        self.assertEqual(command, ["node.exe", str(package / "src" / "cli.mjs")])
        self.assertEqual(package_root, str(package))
        self.assertEqual(run_mock.call_count, 2)

    def test_installs_published_package_to_studio_home_when_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            studio_home = Path(temporary) / "studio"
            package = studio_home / "runtime" / "node_modules" / "aivee"
            install_manifest = None

            def run(args, **_):
                nonlocal install_manifest
                if args[1:] == ["--version"]:
                    return CompletedProcess(args, 0, "v22.22.2\n", "")
                if args[1:] == ["root", "-g"]:
                    return CompletedProcess(args, 1, "", "not installed")
                if args[1] == "install":
                    install_manifest = json.loads((studio_home / "runtime" / "package.json").read_text(encoding="utf-8"))
                    (package / "src").mkdir(parents=True)
                    (package / "src" / "cli.mjs").write_text("", encoding="utf-8")
                    (package / "package.json").write_text(json.dumps({
                        "name": "aivee", "version": AIVEE_VERSION, "bin": {"aivee": "src/cli.mjs"},
                    }), encoding="utf-8")
                    return CompletedProcess(args, 0, "added package", "")
                self.fail(f"unexpected command: {args}")

            with patch("explainer_studio.engine.studio_home", return_value=studio_home), patch(
                "explainer_studio.engine.shutil.which", side_effect=lambda name: f"{name}.exe",
            ), patch("explainer_studio.engine.subprocess.run", side_effect=run) as run_mock:
                command, package_root = ensure_aivee()

        self.assertEqual(command, ["node.exe", str(package / "src" / "cli.mjs")])
        self.assertEqual(package_root, str(package))
        install_call = next(call for call in run_mock.call_args_list if "install" in call.args[0])
        install_args = install_call.args[0]
        runtime = studio_home / "runtime"
        self.assertEqual(install_args[1:], ["install"])
        self.assertEqual(install_call.kwargs["cwd"], runtime)
        self.assertEqual(install_manifest["dependencies"]["aivee"], AIVEE_VERSION)
        self.assertEqual(install_manifest["overrides"]["hyperframes"]["undici"], UNDICI_VERSION)


if __name__ == "__main__":
    unittest.main()
