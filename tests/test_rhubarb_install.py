import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.cli import main
from explainer_studio.common import ProjectError
from explainer_studio.rhubarb import RHUBARB_RELEASES, RHUBARB_VERSION, install_rhubarb


def _archive(root: str = "Rhubarb/") -> tuple[bytes, str]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo(f"{root}rhubarb")
        info.external_attr = 0o755 << 16
        archive.writestr(info, "#!/bin/sh\necho 'Rhubarb Lip Sync version 1.14.0'\n")
        archive.writestr(f"{root}res/readme.txt", "models")
        archive.writestr(f"{root}extras/skip.txt", "not installed")
    payload = buffer.getvalue()
    return payload, hashlib.sha256(payload).hexdigest()


class _Body:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size: int) -> bytes:
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class RhubarbInstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.previous = os.environ.get("RHUBARB_PATH")
        os.environ.pop("RHUBARB_PATH", None)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("RHUBARB_PATH", None)
        else:
            os.environ["RHUBARB_PATH"] = self.previous
        self.temp.cleanup()

    def test_install_extracts_binary_and_wires_rhubarb_path(self):
        payload, digest = _archive()
        release = {
            "url": "https://example.invalid/rhubarb.zip",
            "sha256": digest,
            "root": "Rhubarb/",
        }
        with patch.dict(RHUBARB_RELEASES, {("Linux", "x86_64"): release}):
            binary = install_rhubarb(self.home, system="Linux", machine="x86_64", opener=lambda *_args, **_kwargs: _Body(payload))
        self.assertEqual(binary, self.home / "rhubarb" / RHUBARB_VERSION / "rhubarb")
        self.assertTrue(os.access(binary, os.X_OK))
        self.assertEqual((binary.parent / "res" / "readme.txt").read_text(encoding="utf-8"), "models")
        self.assertFalse((binary.parent / "extras").exists())
        self.assertEqual(os.environ["RHUBARB_PATH"], str(binary))
        self.assertIn("1.14.0", subprocess.check_output([str(binary), "--version"], text=True))

    def test_second_install_reuses_the_verified_binary(self):
        payload, digest = _archive()
        release = {"url": "https://example.invalid/rhubarb.zip", "sha256": digest, "root": "Rhubarb/"}
        calls = []

        def opener(*_args, **_kwargs):
            calls.append("download")
            return _Body(payload)

        with patch.dict(RHUBARB_RELEASES, {("Linux", "x86_64"): release}):
            install_rhubarb(self.home, system="Linux", machine="x86_64", opener=opener)
            install_rhubarb(self.home, system="Linux", machine="x86_64", opener=opener)
        self.assertEqual(calls, ["download"])

    def test_checksum_mismatch_leaves_no_binary(self):
        payload, _digest = _archive()
        release = {"url": "https://example.invalid/rhubarb.zip", "sha256": "0" * 64, "root": "Rhubarb/"}
        with patch.dict(RHUBARB_RELEASES, {("Linux", "x86_64"): release}):
            with self.assertRaisesRegex(ProjectError, "checksum"):
                install_rhubarb(self.home, system="Linux", machine="x86_64", opener=lambda *_args, **_kwargs: _Body(payload))
        self.assertFalse((self.home / "rhubarb" / RHUBARB_VERSION).exists())
        self.assertNotIn("RHUBARB_PATH", os.environ)

    def test_unsafe_archive_path_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Rhubarb/../../evil", "nope")
            archive.writestr("Rhubarb/rhubarb", "#!/bin/sh\necho 1.14.0\n")
        payload = buffer.getvalue()
        release = {
            "url": "https://example.invalid/rhubarb.zip",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "root": "Rhubarb/",
        }
        with patch.dict(RHUBARB_RELEASES, {("Linux", "x86_64"): release}):
            with self.assertRaisesRegex(ProjectError, "unsafe path"):
                install_rhubarb(self.home, system="Linux", machine="x86_64", opener=lambda *_args, **_kwargs: _Body(payload))
        self.assertFalse((self.home / "evil").exists())

    def test_other_platforms_do_not_download(self):
        def opener(*_args, **_kwargs):
            raise AssertionError("download")

        with self.assertRaisesRegex(ProjectError, "x86_64 Linux and macOS"):
            install_rhubarb(self.home, system="Windows", machine="x86_64", opener=opener)
        with self.assertRaisesRegex(ProjectError, "x86_64 Linux and macOS"):
            install_rhubarb(self.home, system="Linux", machine="aarch64", opener=opener)

    def test_download_failure_is_a_project_error(self):
        release = {"url": "https://example.invalid/rhubarb.zip", "sha256": "ab", "root": "Rhubarb/"}

        def opener(*_args, **_kwargs):
            raise URLError("offline")

        with patch.dict(RHUBARB_RELEASES, {("Darwin", "x86_64"): release}):
            with self.assertRaisesRegex(ProjectError, "could not download"):
                install_rhubarb(self.home, system="Darwin", machine="x86_64", opener=opener)

    def test_bootstrap_flag_is_optional(self):
        def fake_run(args, **_kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        with (
            patch.dict(os.environ, {"EXPLAINER_STUDIO_HOME": str(self.home)}),
            patch("explainer_studio.cli.subprocess.run", side_effect=fake_run),
            patch("explainer_studio.rhubarb.install_rhubarb", return_value=self.home / "rhubarb-bin") as install,
        ):
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = main(["bootstrap", "--json"])
            self.assertEqual(code, 0)
            install.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertNotIn("rhubarb", payload["data"])

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = main(["bootstrap", "--json", "--rhubarb"])
            self.assertEqual(code, 0)
            install.assert_called_once_with()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["data"]["rhubarb"], str(self.home / "rhubarb-bin"))
            self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
