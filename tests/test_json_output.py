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
    _aivee_can_be_installed,
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
        self.assertEqual(
            command_step("render", "/tmp/my project", "--preview"),
            "explainer render --json '/tmp/my project' --preview",
        )

    def test_next_steps_never_cross_review_gates(self):
        blocked = (
            "explainer approve /tmp/film",
            "explainer init demo",
            "explainer init <project>",
            "explainer render /tmp/film",
            "explainer render /tmp/film --portrait",
            "explainer render-engine /tmp/film",
            "explainer setup --avatar-pack /tmp/pack",
            command_step("setup", "--avatar-pack", "/tmp/pack"),
        )
        for step in blocked:
            self.assertTrue(_step_crosses_review_gate(step), step)
            with self.assertRaises(RuntimeError):
                _ungated(step)
        safe = _ungated(
            "explainer setup",
            command_step("setup"),
            "explainer doctor",
            "explainer render /tmp/film --preview",
            "explainer render-engine /tmp/film --portrait --preview",
            command_step("contact-sheet", "/tmp/film", "/tmp/draft.mp4"),
            command_step("check", "/tmp/film", "/tmp/final.mp4"),
        )
        self.assertEqual(len(safe), 7)
        self.assertEqual(_doctor_steps([], True), [])
        self.assertEqual(_doctor_steps([], False), [command_step("setup")])
        self.assertEqual(
            _doctor_steps(["Pillow", "AIVEE (run `explainer install-engine`)"], False, install_aivee=True),
            [command_step("bootstrap"), command_step("install-engine")],
        )
        self.assertEqual(_doctor_steps(["AIVEE (run `explainer install-engine`)"], True), [])
        self.assertEqual(
            _doctor_steps(["Node.js 22+", "AIVEE (run `explainer install-engine`)"], False, install_aivee=True),
            [],
        )
        self.assertTrue(_aivee_can_be_installed("AIVEE is not installed; run `explainer install-engine` to install it globally"))
        self.assertFalse(_aivee_can_be_installed("The global AIVEE installation is incompatible or missing render requirements"))
        self.assertEqual(_doctor_steps(["Python 3.11+", "Pillow"], False), [])
        self.assertEqual(_doctor_steps(["Node.js 22+", "npm", "AIVEE (run `explainer install-engine`)"], False), [])

    def test_every_command_accepts_json(self):
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
        self.assertIn("status", names)
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
        self.assertEqual(payload["next_steps"], [command_step("setup")])

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

    def test_setup_saves_caption_preset_and_hook_font_to_profile(self):
        workspace = {key: str(self.home / key) for key in ("root", "studio", "library", "avatarPacks", "projects")}
        with patch("explainer_studio.engine.setup_aivee_home", return_value=workspace), patch("explainer_studio.captions.warn_missing_fonts"):
            code, out, err = self.invoke(
                "setup", "--home", str(self.home / "AIVEE"), "--caption-font", "Arial",
                "--caption-keyword-color", "#FFD500", "--caption-x", "0.2", "--caption-y", "0.4",
                "--caption-width", "0.6", "--caption-height", "0.1", "--hook-font", "Bebas Neue",
            )

        self.assertEqual((code, err), (0, ""))
        profile = json.loads((self.home / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["caption"]["fontFamily"], "Arial")
        self.assertEqual(profile["caption"]["wordHighlightColor"], "#FFD500")
        self.assertEqual(profile["caption"]["placement"], {"x": 0.2, "y": 0.4, "width": 0.6, "height": 0.1})
        self.assertEqual(profile["caption"]["textShadow"]["blurPixels"], 4)
        self.assertEqual(profile["hook_font_family"], "Bebas Neue")

    def test_setup_json_reports_font_warnings_as_data(self):
        workspace = {key: str(self.home / key) for key in ("root", "studio", "library", "avatarPacks", "projects")}
        warning = "hook font 'Bebas Neue' is not installed"
        with patch("explainer_studio.engine.setup_aivee_home", return_value=workspace), patch(
            "explainer_studio.captions.warn_missing_fonts", return_value=[warning],
        ):
            code, out, err = self.invoke("setup", "--json", "--home", str(self.home / "AIVEE"))

        self.assertEqual((code, err), (0, ""))
        payload = json.loads(out)
        self.assert_result(payload, "setup", True)
        self.assertEqual(payload["data"]["warnings"], [warning])

    def test_scene_composition_invalidates_approval_and_tracks_all_local_files(self):
        from explainer_studio.common import ProjectError, file_hash
        from explainer_studio.timing import scene_composition_hash, validate_storyboard

        root = self.home / "film"
        data = root / "studio-data" / "explainer"
        data.mkdir(parents=True)
        voice = root / "assets" / "voice.mp3"
        voice.parent.mkdir()
        voice.write_bytes(b"voice")
        (data / "project.json").write_text(json.dumps({"voice": "assets/voice.mp3"}), encoding="utf-8")
        (data / "script.txt").write_text("Hello", encoding="utf-8")
        words = data / "words.json"
        words.write_text(json.dumps([{"text": "Hello", "start": 0.1, "end": 0.5}]), encoding="utf-8")
        composition_dir = root / "compositions" / "scenes" / "scene-01"
        composition_dir.mkdir(parents=True)
        html = composition_dir / "index.html"
        html.write_text("<div>Scene</div>", encoding="utf-8")
        (composition_dir / "shape.svg").write_text("<svg/>", encoding="utf-8")
        board = {
            "version": 1, "approved": True,
            "approval_hash": "stale",
            "scenes": [{"start": 0, "end": 1, "headline": "Hello"}],
            "source": {"script_sha256": file_hash(data / "script.txt"), "voice_sha256": file_hash(voice), "words_sha256": file_hash(words)},
        }
        (data / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
        with patch("explainer_studio.timing.probe_duration", return_value=1):
            code, out, err = self.invoke("scene-composition", str(root), "1", "compositions/scenes/scene-01/index.html", "--json")
            self.assertEqual(code, 0, err or out)
            payload = json.loads(out)
            self.assert_result(payload, "scene-composition", True)
            self.assertEqual(payload["data"]["review_gate"], "storyboard")
            self.assertEqual(payload["next_steps"], [])
            updated = json.loads((data / "storyboard.json").read_text(encoding="utf-8"))
            self.assertFalse(updated["approved"])
            self.assertNotIn("approval_hash", updated)
            self.assertEqual(updated["scenes"][0]["composition_sha256"], scene_composition_hash(html))
            validate_storyboard(root, updated, 1)
            (composition_dir / "shape.svg").write_text("<svg><circle/></svg>", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "composition is missing or changed"):
                validate_storyboard(root, updated, 1)

    def test_doctor_json_uses_the_schema(self):
        code, out, err = self.invoke("doctor", "--json")
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "doctor", code == 0)
        self.assertIn("python", payload["data"])
        self.assertIn("missing", payload["data"])
        self.assertNotEqual(payload["data"]["node"], "MISSING")
        self.assertTrue(all(not _step_crosses_review_gate(step) for step in payload["next_steps"]))
        if payload["data"]["missing"]:
            self.assertNotEqual(code, 0)
            self.assertTrue(payload["error"])
        else:
            self.assertEqual(code, 0)

    def test_doctor_json_installs_aivee_only_when_it_is_absent(self):
        import subprocess

        from explainer_studio.common import ProjectError

        def which(name):
            return f"/usr/bin/{name}"

        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="v22.0.0\n")

        cases = (
            (
                "AIVEE is not installed; run `explainer install-engine` to install it globally",
                [command_step("install-engine")],
            ),
            (
                "The global AIVEE installation is incompatible or missing render requirements; run `npm install --global aivee@latest` and retry",
                [],
            ),
            (
                "A global AIVEE package exists but its CLI is invalid: /tmp/aivee; repair or remove it before installing AIVEE again",
                [],
            ),
        )
        for message, steps in cases:
            with (
                patch("explainer_studio.cli.shutil.which", side_effect=which),
                patch("explainer_studio.cli.subprocess.run", side_effect=run),
                patch("explainer_studio.engine.resolve_aivee", side_effect=ProjectError(message)),
                patch("explainer_studio.engine._browser_env", return_value={"HYPERFRAMES_BROWSER_PATH": "/usr/bin/chrome"}),
            ):
                code, out, err = self.invoke("doctor", "--json")
            self.assertEqual(code, 1, message)
            self.assertEqual(err, "", message)
            payload = json.loads(out)
            self.assert_result(payload, "doctor", False)
            self.assertEqual(payload["next_steps"], steps, message)

    def _healthy_doctor(self, version="1.2.3", **env):
        import subprocess

        package = self.home / "aivee"
        package.mkdir(exist_ok=True)
        (package / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")

        def which(name):
            if name in {"ffmpeg", "ffprobe", "node", "npm"}:
                return f"/usr/bin/{name}"
            return None

        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="v22.0.0\n")

        with (
            patch.dict(os.environ, env, clear=False),
            patch("explainer_studio.cli.shutil.which", side_effect=which),
            patch("explainer_studio.cli.subprocess.run", side_effect=run),
            patch("explainer_studio.engine.resolve_aivee", return_value=(["aivee"], str(package))),
            patch("explainer_studio.engine._browser_env", return_value={"HYPERFRAMES_BROWSER_PATH": "/usr/bin/chrome"}),
        ):
            return self.invoke("doctor", "--json")

    def test_doctor_reports_an_aivee_older_than_caption_emphasis(self):
        code, out, err = self._healthy_doctor(version="0.2.0")
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "doctor", False)
        self.assertEqual(code, 1)
        self.assertIn("0.3.0", payload["error"])
        self.assertIn("npm install --global aivee@latest", payload["error"])
        self.assertIn("caption keyword emphasis", payload["error"])

    def test_doctor_still_suggests_setup_when_rhubarb_path_is_set(self):
        binary = self.home / "custom-rhubarb"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        code, out, err = self._healthy_doctor(RHUBARB_PATH=str(binary))
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "doctor", True)
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["rhubarb"], str(binary.resolve()))
        self.assertIn(command_step("setup"), payload["next_steps"])

    def test_doctor_reports_a_missing_rhubarb_path_instead_of_amplitude(self):
        code, out, err = self._healthy_doctor(RHUBARB_PATH="/missing/rhubarb")
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "doctor", False)
        self.assertEqual(code, 1)
        self.assertIsNone(payload["data"]["rhubarb"])
        self.assertIn("/missing/rhubarb", payload["error"])
        self.assertNotIn("amplitude", json.dumps(payload))
        self.assertIn(command_step("setup"), payload["next_steps"])

    def test_doctor_prefers_the_profile_rhubarb_path_over_the_environment(self):
        profile_binary = self.home / "profile-rhubarb"
        env_binary = self.home / "env-rhubarb"
        profile_binary.write_text("#!/bin/sh\n", encoding="utf-8")
        env_binary.write_text("#!/bin/sh\n", encoding="utf-8")
        (self.home / "profile.json").write_text(json.dumps({
            "brand": "Acme", "rhubarb_path": str(profile_binary),
        }), encoding="utf-8")
        code, out, err = self._healthy_doctor(RHUBARB_PATH=str(env_binary))
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "doctor", True)
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["rhubarb"], str(profile_binary.resolve()))
        self.assertNotIn(command_step("setup"), payload["next_steps"])

    def test_unexpected_error_with_json_returns_the_error_object(self):
        self.write_profile()
        root = self.home / "film"
        root.mkdir()
        with patch("explainer_studio.engine.render_with_engine", side_effect=RuntimeError("render boom")):
            code, out, err = self.invoke("render", "--json", "--preview", str(root))
            self.assertEqual((code, err), (1, ""))
            payload = json.loads(out)
            self.assert_result(payload, "render", False)
            self.assertEqual(payload["error"], "render boom")
            self.assertNotIn("Traceback", out)
            with self.assertRaises(RuntimeError):
                self.invoke("render", "--preview", str(root))
        with patch("explainer_studio.engine.render_with_engine", side_effect=RuntimeError()):
            code, out, err = self.invoke("render", "--json", str(root))
        self.assertEqual((code, err), (1, ""))
        payload = json.loads(out)
        self.assert_result(payload, "render", False)
        self.assertEqual(payload["error"], "RuntimeError")

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

    def test_init_json_does_not_invent_a_voice_path(self):
        profile = {
            "brand": "Acme",
            "language": "en",
            "aivee_home": str(self.home / "aivee"),
            "colors": {"background": "#F6F8FC", "ink": "#172236", "accent": "#426BEB"},
        }
        (self.home / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        root = self.home / "film"
        data = root / "studio-data" / "explainer"
        data.mkdir(parents=True)
        created = {"project": str(root), "studioData": str(data)}
        with patch("explainer_studio.engine.create_aivee_project", return_value=created):
            code, out, err = self.invoke("init", str(root.name))
            self.assertEqual(code, 0, err or out)
            self.assertIn(f"project created: {root.resolve()}", out)
            self.assertNotIn('"ok"', out)
            code, out, err = self.invoke("init", "--json", str(root.name))
        self.assertEqual(code, 0, err or out)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assert_result(payload, "init", True)
        self.assertFalse(payload["data"]["voice_attached"])
        self.assertEqual(payload["next_steps"], [])
        voice = self.home / "take.mp3"
        voice.write_bytes(b"voice")
        with (
            patch("explainer_studio.engine.create_aivee_project", return_value=created),
            patch("explainer_studio.engine.register_asset", return_value={"path": "assets/narration.mp3"}),
            patch("explainer_studio.cli.probe_duration", return_value=3.0),
        ):
            code, out, err = self.invoke("init", "--json", "retake", "--voice", str(voice))
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assert_result(payload, "init", True)
        self.assertTrue(payload["data"]["voice_attached"])
        self.assertEqual(payload["next_steps"], [command_step("transcribe", payload["data"]["project"])])
        self.assertNotIn("<", payload["next_steps"][0])

    def test_init_reel_format_sets_portrait_canvas_for_studio_and_aivee(self):
        profile = {
            "brand": "Acme", "language": "en", "aivee_home": str(self.home / "aivee"),
            "colors": {"background": "#F6F8FC", "ink": "#172236", "accent": "#426BEB"},
        }
        (self.home / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        root = self.home / "reel"
        data = root / "studio-data" / "explainer"
        data.mkdir(parents=True)
        created = {"project": str(root), "studioData": str(data)}
        with patch("explainer_studio.engine.create_aivee_project", return_value=created) as create:
            code, out, err = self.invoke("init", "--json", "--format", "reel", root.name)

        self.assertEqual((code, err), (0, ""))
        self.assert_result(json.loads(out), "init", True)
        project = json.loads((data / "project.json").read_text(encoding="utf-8"))
        self.assertEqual((project["format"], project["width"], project["height"], project["fps"]), ("reel", 1080, 1920, 30))
        create.assert_called_once_with(
            Path(profile["aivee_home"]), root.name, 10,
            width=1080, height=1920, fps=30,
        )

    def test_export_avatar_has_stable_json_result(self):
        result = {
            "output": "/tmp/native/studio-data/explainer/avatar-exports/film",
            "timing": "/tmp/native/studio-data/explainer/avatar-exports/film/timing.json",
            "sprites": 2, "intervals": 8, "voice_asset": "assets/studio-narration.wav",
            "words": "/tmp/native/studio-data/explainer/avatar-exports/film/words.json",
        }
        with patch("explainer_studio.avatar_export.export_avatar", return_value=result) as export, patch(
            "explainer_studio.cli.load_profile", return_value={"brand": "Acme"},
        ):
            code, out, err = self.invoke("export-avatar", "--json", "/tmp/studio", "/tmp/native")

        self.assertEqual((code, err), (0, ""))
        payload = json.loads(out)
        self.assert_result(payload, "export-avatar", True)
        self.assertEqual(payload["data"], result)
        self.assertEqual(payload["next_steps"], [])
        export.assert_called_once_with(Path("/tmp/studio"), Path("/tmp/native"), {"brand": "Acme"}, scale=1.0)

    def test_render_infers_portrait_from_project_format(self):
        self.write_profile()
        root = self.home / "reel"
        data = root / "studio-data" / "explainer"
        data.mkdir(parents=True)
        (data / "project.json").write_text(json.dumps({"format": "reel", "width": 1080, "height": 1920, "fps": 30}), encoding="utf-8")
        video = root / "renders" / "draft-portrait-engine.mp4"
        with patch("explainer_studio.engine.render_with_engine", return_value=video) as render:
            code, out, err = self.invoke("render", "--json", "--preview", str(root))

        self.assertEqual((code, err), (0, ""))
        payload = json.loads(out)
        self.assertTrue(payload["data"]["portrait"])
        self.assertEqual(payload["data"]["video"], str(video))
        self.assertTrue(render.call_args.kwargs["portrait"])

    def test_avatar_pack_json_waits_for_approval(self):
        pack = self.home / "pack"
        pack.mkdir()
        preview = pack / "preview.png"
        with patch("explainer_studio.avatar.validate_pack", return_value={"name": "Emo", "id": "emo", "version": "1"}):
            code, out, err = self.invoke("avatar-validate", "--json", str(pack))
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assert_result(payload, "avatar-validate", True)
        self.assertEqual(payload["next_steps"], [])
        with patch("explainer_studio.avatar.preview_pack", return_value=preview):
            code, out, err = self.invoke("avatar-preview-pack", "--json", str(pack), "--output", str(preview))
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assert_result(payload, "avatar-preview-pack", True)
        self.assertEqual(payload["data"]["output"], str(preview))
        self.assertEqual(payload["next_steps"], [])

    def test_contact_sheet_json_skips_sync_check_without_faster_whisper(self):
        root = self.home / "film"
        root.mkdir()
        video = root / "draft.mp4"
        video.write_bytes(b"video")
        sheet = root / "sheet.jpg"
        with (
            patch("explainer_studio.quality.contact_sheet", return_value=sheet),
            patch("explainer_studio.cli._sync_check_available", return_value=False),
        ):
            code, out, err = self.invoke("contact-sheet", "--json", str(root), str(video))
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assert_result(payload, "contact-sheet", True)
        self.assertEqual(payload["next_steps"], [])
        with (
            patch("explainer_studio.quality.contact_sheet", return_value=sheet),
            patch("explainer_studio.cli._sync_check_available", return_value=True),
        ):
            code, out, err = self.invoke("contact-sheet", "--json", str(root), str(video))
        self.assertEqual(code, 0, err or out)
        payload = json.loads(out)
        self.assertEqual(
            payload["next_steps"],
            [command_step("sync-check", str(root.resolve()), str(video.resolve()))],
        )


if __name__ == "__main__":
    unittest.main()
