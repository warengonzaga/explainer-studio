"""Sound-effect packs, cue derivation, Openverse import, and the AIVEE mix."""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from explainer_studio.common import ProjectError, write_json
from explainer_studio.sfx import (
    add_openverse_result,
    apply_sfx,
    derive_cues,
    install_default_pack,
    load_mapping,
    require_sfx_aivee,
    resolve_render_sfx,
    search_openverse,
    sfx_doctor_status,
    validate_pack,
    version_at_least,
    write_cues,
)
from explainer_studio.cli import main


class Response:
    def __init__(self, body: bytes):
        self.body = body
        self.offset = 0

    def read(self, amount=None):
        if self.offset >= len(self.body):
            return b""
        if amount is None:
            amount = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset + amount]
        self.offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def tiny_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00")
    return buffer.getvalue()


class SoundEffectTest(unittest.TestCase):
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

    def profile(self, library: Path | None = None) -> dict:
        avatar_packs = library or (self.home / "Library" / "Avatar Packs")
        avatar_packs.mkdir(parents=True, exist_ok=True)
        profile = {"aivee_workspace": {"avatarPacks": str(avatar_packs), "library": str(avatar_packs.parent)}}
        write_json(self.home / "profile.json", profile)
        return profile

    def project(self) -> tuple[Path, Path]:
        root = self.home / "film"
        data = root / "studio-data" / "explainer"
        data.mkdir(parents=True)
        (root / "compositions" / "scenes" / "ui").mkdir(parents=True)
        (root / "graphics").mkdir()
        (root / "graphics" / "badge.png").write_bytes(b"png")
        (root / "graphics" / "diagram.png").write_bytes(b"png")
        (root / "graphics" / "staple.png").write_bytes(b"png")
        html = """
        <script>
          const at = (fraction) => duration * fraction;
          const timeline = gsap.timeline({ paused: true });
          const reveal = (selector, fraction) => {
            timeline.fromTo(selector, { autoAlpha: 0 }, { autoAlpha: 1, duration: at(0.1) }, at(fraction));
          };
          reveal(".step-1", 0.2);
          timeline.to(".click-target", { scale: 0.9, duration: 0.05 }, 1.5);
          timeline.to(".typing-caret", { autoAlpha: 1, duration: 0.05 }, at(0.7));
          timeline.to({}, { duration }, 0);
        </script>
        """
        (root / "compositions" / "scenes" / "ui" / "index.html").write_text(html, encoding="utf-8")
        write_json(data / "project.json", {"version": 1, "title": "film"})
        write_json(data / "storyboard.json", {
            "version": 1,
            "scenes": [
                {
                    "start": 0, "end": 10, "headline": "Open",
                    "visual_cues": [
                        {"asset": "graphics/badge.png", "start": 1.25, "duration": 2},
                        {"asset": "graphics/diagram.png", "start": 3, "duration": 2},
                        {"asset": "graphics/staple.png", "start": 4, "duration": 2},
                    ],
                    "composition": "compositions/scenes/ui/index.html",
                },
                {"start": 10, "end": 20, "headline": "Next", "transition": {"type": "fade"}},
            ],
        })
        write_json(root / "timeline.json", {
            "project": {"durationSeconds": 20},
            "tracks": [
                {"id": "studio-visuals", "kind": "video", "clips": [
                    {"id": "visual-01", "timelineStart": 1.25, "durationSeconds": 2},
                ]},
                {"id": "broll", "kind": "video", "clips": [
                    {"id": "intro", "timelineStart": 0, "durationSeconds": 10, "transitionOut": {"durationSeconds": 0.4}},
                    {"id": "badge-card", "timelineStart": 12, "durationSeconds": 2},
                    {"id": "precursor", "timelineStart": 14, "durationSeconds": 2},
                ]},
            ],
        })
        return root, data

    def test_version_gate_and_doctor_hint(self):
        self.assertFalse(version_at_least("0.2.9"))
        self.assertTrue(version_at_least("0.3.0"))
        self.assertTrue(version_at_least("0.3.1"))
        self.assertTrue(version_at_least("0.10.0"))
        self.assertFalse(version_at_least("unknown"))
        self.assertFalse(sfx_doctor_status(None)["available"])
        self.assertIn("0.3.0", sfx_doctor_status("0.2.9")["line"])
        self.assertTrue(sfx_doctor_status("0.3.0")["available"])
        self.assertFalse(sfx_doctor_status("0.2.9")["available"])

    def test_default_pack_is_synthesized_beside_avatar_packs(self):
        profile = self.profile()
        library = Path(profile["aivee_workspace"]["avatarPacks"]).parent / "Sound Packs"
        first = install_default_pack(library)
        manifest = validate_pack(first)
        self.assertEqual(manifest["id"], "default-tones")
        self.assertEqual(manifest["license"], "CC0-1.0")
        self.assertEqual(set(manifest["roles"]), {"whoosh", "pop", "click", "ding"})
        tones = {}
        for role, entry in manifest["roles"].items():
            path = first / entry["file"]
            with wave.open(str(path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertGreater(handle.getnframes(), 0)
            tones[role] = path.read_bytes()
        self.assertEqual(len(set(tones.values())), 4)
        note = first / "README.md"
        note.write_text(note.read_text(encoding="utf-8") + "\nKept.\n", encoding="utf-8")
        second = install_default_pack(library)
        self.assertEqual(second, first)
        self.assertIn("Kept.", note.read_text(encoding="utf-8"))
        again = install_default_pack(self.home / "other-library")
        self.assertEqual((again / "whoosh.wav").read_bytes(), tones["whoosh"])

    def test_cues_follow_timeline_events_and_stay_editable(self):
        root, data = self.project()
        pack = install_default_pack(self.home / "Sound Packs")
        document = derive_cues(root, pack)
        by_label = {cue["label"]: cue for cue in document["cues"]}
        self.assertEqual(by_label["scene-1:badge.png"]["role"], "pop")
        self.assertEqual(by_label["scene-1:badge.png"]["event"], "badge")
        self.assertEqual(by_label["scene-1:badge.png"]["at"], 1.25)
        self.assertEqual(by_label["scene-1:diagram.png"]["event"], "element")
        self.assertEqual(by_label["scene-1:staple.png"]["event"], "element")
        self.assertNotIn("precursor", by_label)
        self.assertEqual(by_label["scene-1:.step-1"]["event"], "step")
        self.assertEqual(by_label["scene-1:.step-1"]["at"], 2.0)
        self.assertEqual(by_label["scene-1:.click-target"]["role"], "click")
        self.assertEqual(by_label["scene-1:.click-target"]["at"], 1.5)
        self.assertEqual(by_label["scene-1:.typing-caret"]["event"], "typing")
        self.assertEqual(by_label["scene-1:.typing-caret"]["at"], 7.0)
        self.assertEqual(by_label["scene-2"]["event"], "transition")
        self.assertEqual(by_label["scene-2"]["role"], "whoosh")
        self.assertEqual(by_label["scene-2"]["at"], 10.0)
        self.assertEqual(by_label["intro:out"]["at"], 9.6)
        self.assertEqual(by_label["badge-card"]["event"], "badge")
        self.assertNotIn("visual-01", by_label)
        self.assertNotIn("scene-1", by_label)
        self.assertEqual(document, derive_cues(root, pack))

        path = write_cues(root, document)
        with self.assertRaises(ProjectError):
            write_cues(root, document)
        edited = json.loads(path.read_text(encoding="utf-8"))
        edited["cues"][0]["at"] = 1.75
        path.write_text(json.dumps(edited), encoding="utf-8")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["cues"][0]["at"], 1.75)
        write_cues(root, document, force=True)
        self.assertEqual(json.loads((data / "sfx-cues.json").read_text(encoding="utf-8"))["cues"][0]["at"], document["cues"][0]["at"])

    def test_mapping_override_changes_roles(self):
        root, _data = self.project()
        pack = install_default_pack(self.home / "Sound Packs")
        mapping = load_mapping(project_mapping={"badge": "ding", "transition": "ding"})
        document = derive_cues(root, pack, mapping)
        roles = {cue["label"]: cue["role"] for cue in document["cues"]}
        self.assertEqual(roles["scene-1:badge.png"], "ding")
        self.assertEqual(roles["scene-2"], "ding")
        self.assertEqual(roles["scene-1:.step-1"], "pop")

    def test_bundled_scene_starters_produce_pops(self):
        root = self.home / "starters"
        scenes = []
        templates = sorted(path for path in (ROOT / "library" / "templates").iterdir() if (path / "scene.html").is_file())
        for index, directory in enumerate(templates):
            relative = f"compositions/scenes/{directory.name}/index.html"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(directory / "scene.html", target)
            start = index * 10
            scenes.append({"start": start, "end": start + 10, "headline": directory.name, "composition": relative})
        write_json(root / "storyboard.json", {"version": 1, "scenes": scenes})
        pack = install_default_pack(self.home / "Sound Packs")
        document = derive_cues(root, pack)
        pops = [cue for cue in document["cues"] if cue["role"] == "pop"]
        self.assertGreaterEqual(len(pops), 8)
        step_scene = templates.index(next(path for path in templates if path.name == "numbered-steps"))
        start = step_scene * 10
        steps = [cue["at"] for cue in document["cues"] if ".step-" in cue["label"]]
        self.assertEqual(steps, [round(start + fraction * 10, 3) for fraction in (0.1, 0.28, 0.46)])

    def test_openverse_search_records_cc_attribution_and_skips_the_network_in_tests(self):
        calls = []

        def opener(request, timeout=30):
            calls.append(request.full_url)
            if request.full_url.startswith("https://api.openverse.org/"):
                payload = {"results": [
                    {"id": "skip", "title": "Reserved", "url": "https://cdn.example/nope.wav", "license": "all-rights-reserved", "filetype": "wav"},
                    {
                        "id": "whoosh-1", "title": "Soft whoosh", "url": "https://cdn.example/whoosh.wav",
                        "license": "by", "license_version": "4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
                        "creator": "A. Maker", "creator_url": "https://example.com/maker",
                        "foreign_landing_url": "https://example.com/whoosh", "filetype": "wav",
                        "attribution": "Soft whoosh by A. Maker is licensed under CC BY 4.0",
                    },
                ]}
                return Response(json.dumps(payload).encode())
            if request.full_url == "https://cdn.example/whoosh.wav":
                return Response(tiny_wav())
            raise AssertionError(request.full_url)

        results = search_openverse("whoosh", opener=opener)
        self.assertEqual([item["id"] for item in results], ["whoosh-1"])
        self.assertEqual(results[0]["license"], "CC-BY-4.0")
        pack = install_default_pack(self.home / "Sound Packs")
        entry = add_openverse_result(pack, "whoosh", "whoosh", opener=opener)
        manifest = validate_pack(pack)
        self.assertEqual(manifest["roles"]["whoosh"]["source"], "openverse")
        self.assertEqual(manifest["roles"]["whoosh"]["attribution"], entry["attribution"])
        self.assertTrue((pack / entry["file"]).is_file())
        self.assertFalse((pack / "whoosh.wav").exists())
        self.assertTrue(any(url.startswith("https://api.openverse.org/v1/audio/?") for url in calls))
        self.assertTrue(all(not url.startswith("http://") for url in calls))

    def test_mix_calls_aivee_sfx_without_changing_the_source(self):
        root, data = self.project()
        profile = self.profile()
        pack = install_default_pack(Path(profile["aivee_workspace"]["avatarPacks"]).parent / "Sound Packs")
        write_cues(root, derive_cues(root, pack))
        video = root / "renders" / "final-engine.mp4"
        video.parent.mkdir()
        video.write_bytes(b"original-video")
        package = self.home / "aivee"
        package.mkdir()
        write_json(package / "package.json", {"name": "aivee", "version": "0.3.0", "bin": {"aivee": "cli.mjs"}})

        def run(_command, _cwd, args):
            self.assertEqual(args[0], "sfx")
            self.assertEqual(Path(args[1]).read_bytes(), b"original-video")
            cues = json.loads(Path(args[2]).read_text(encoding="utf-8"))
            self.assertTrue(all(item["file"].endswith(".wav") for item in cues))
            self.assertTrue(all((Path(args[2]).parent / item["file"]).is_file() for item in cues))
            options = json.loads(Path(args[4]).read_text(encoding="utf-8"))
            self.assertEqual(options, {"duckUnderSpeech": {"thresholdDb": -20, "ratio": 4}, "gainCapDb": -6})
            Path(args[3]).write_bytes(b"mixed")
            return ""

        with patch("explainer_studio.sfx.resolve_aivee", return_value=(["node", "aivee"], str(package))), patch(
            "explainer_studio.sfx._engine_cli", side_effect=run,
        ):
            output = apply_sfx(
                root, video, profile,
                options={"duckUnderSpeech": {"thresholdDb": -20, "ratio": 4}, "gainCapDb": -6},
            )
        self.assertEqual(video.read_bytes(), b"original-video")
        self.assertEqual(output, video.with_name("final-engine-sfx.mp4"))
        self.assertEqual(output.read_bytes(), b"mixed")
        write_json(package / "package.json", {"name": "aivee", "version": "0.2.9"})
        with patch("explainer_studio.sfx.resolve_aivee", return_value=(["node", "aivee"], str(package))):
            with self.assertRaises(ProjectError) as raised:
                require_sfx_aivee()
        self.assertIn("0.3.0", str(raised.exception))

    def test_render_flag_is_opt_in(self):
        root, data = self.project()
        profile = self.profile()
        pack = install_default_pack(Path(profile["aivee_workspace"]["avatarPacks"]).parent / "Sound Packs")
        write_cues(root, derive_cues(root, pack))
        target = root / "renders" / "draft-engine.mp4"

        def fake_render(_root, output, _profile, preview=False, portrait=False):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"draft")
            return output

        with patch("explainer_studio.engine.render_with_engine", side_effect=fake_render), patch(
            "explainer_studio.sfx.apply_sfx",
        ) as mix, patch("explainer_studio.captions.warn_missing_fonts", return_value=[]):
            code, out, err = self.invoke("render", str(root), "--preview", "--output", str(target), "--json")
        self.assertEqual((code, err), (0, ""))
        mix.assert_not_called()
        self.assertEqual(json.loads(out)["data"]["video"], str(target))

        def fake_mix(_root, video, _profile, pack=None, options=None, command=None):
            mixed = video.with_name(f"{video.stem}-sfx{video.suffix}")
            mixed.write_bytes(b"mixed")
            self.assertEqual(options, {"duckUnderSpeech": True, "gainCapDb": -3})
            return mixed

        package = self.home / "aivee-render"
        package.mkdir()
        write_json(package / "package.json", {"name": "aivee", "version": "0.3.0"})
        sfx_target = root / "renders" / "with-sfx.mp4"
        with patch("explainer_studio.engine.render_with_engine", side_effect=fake_render), patch(
            "explainer_studio.sfx.apply_sfx", side_effect=fake_mix,
        ), patch("explainer_studio.sfx.resolve_aivee", return_value=(["node", "aivee"], str(package))), patch(
            "explainer_studio.captions.warn_missing_fonts", return_value=[],
        ):
            code, out, err = self.invoke(
                "render", str(root), "--preview", "--output", str(sfx_target), "--json",
                "--sfx", "--duck-under-speech", "--gain-cap-db=-3",
            )
        self.assertEqual((code, err), (0, ""))
        payload = json.loads(out)
        self.assertTrue(payload["data"]["sfx"])
        self.assertEqual(payload["data"]["source_video"], str(sfx_target))
        self.assertTrue(payload["data"]["video"].endswith("with-sfx-sfx.mp4"))
        enabled = resolve_render_sfx(argparse_namespace(sfx=None), {"enabled": True, "gainCapDb": -2})
        self.assertEqual(enabled["options"], {"gainCapDb": -2})
        self.assertIsNone(resolve_render_sfx(argparse_namespace(sfx=False), {"enabled": True}))

        missing = root / "renders" / "missing-file.mp4"
        (pack / "pop.wav").unlink()
        with patch("explainer_studio.engine.render_with_engine", side_effect=fake_render), patch(
            "explainer_studio.sfx.resolve_aivee", return_value=(["node", "aivee"], str(package))), patch(
            "explainer_studio.captions.warn_missing_fonts", return_value=[],
        ):
            code, out, err = self.invoke("render", str(root), "--preview", "--output", str(missing), "--json", "--sfx")
        self.assertNotEqual(code, 0)
        self.assertFalse(missing.exists())
        self.assertIn("missing", json.loads(out)["error"])

    def test_cli_installs_pack_and_searches_without_a_real_network(self):
        self.profile()
        code, out, err = self.invoke("sound-pack-install", "--json")
        self.assertEqual((code, err), (0, ""))
        pack = Path(json.loads(out)["data"]["pack"])
        self.assertTrue((pack / "manifest.json").is_file())
        code, out, err = self.invoke("sound-pack-validate", str(pack), "--json")
        self.assertEqual(json.loads(out)["data"]["id"], "default-tones")

        def opener(request, timeout=30):
            payload = {"results": [{
                "id": "pop-9", "title": "Pop", "url": "https://cdn.example/pop.wav",
                "license": "cc0", "license_version": "1.0", "filetype": "wav",
                "creator": "A. Maker", "attribution": "Pop by A. Maker, CC0",
            }]}
            if "api.openverse.org" in request.full_url:
                return Response(json.dumps(payload).encode())
            return Response(tiny_wav())

        with patch("explainer_studio.sfx._default_open", side_effect=opener):
            code, out, err = self.invoke("sound-pack-search", "--query", "pop", "--json")
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(out)["data"]["results"][0]["license"], "CC0-1.0")
            code, out, err = self.invoke("sound-pack-add", str(pack), "pop", "--query", "pop", "--json")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["data"]["attribution"], "Pop by A. Maker, CC0")
        self.assertEqual(validate_pack(pack)["roles"]["pop"]["source_id"], "pop-9")

    def invoke(self, *argv: str):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()


def argparse_namespace(**values):
    class Namespace:
        pass

    item = Namespace()
    item.sfx = values.get("sfx")
    item.duck_under_speech = values.get("duck_under_speech")
    item.gain_cap_db = values.get("gain_cap_db")
    item.sfx_pack = values.get("sfx_pack")
    return item


if __name__ == "__main__":
    unittest.main()
