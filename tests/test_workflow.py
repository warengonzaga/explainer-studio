"""Exercise the user-visible film path with a short synthetic narration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "explainer.py"


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class WorkflowTest(unittest.TestCase):
    def test_doctor_runs_without_installed_python_packages(self):
        proc = subprocess.run(
            [sys.executable, "-S", str(CLI), "doctor"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertIn("pillow: MISSING", proc.stdout)
        self.assertNotIn("ModuleNotFoundError", proc.stderr)

    def test_word_timing_changes_require_reapproval_without_losing_scenes(self):
        scratch = ROOT / "projects"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            base = Path(temp)
            env = os.environ.copy()
            env["EXPLAINER_STUDIO_HOME"] = str(base / "home")
            project = base / "film"

            def cli(*args: str, success: bool = True):
                proc = subprocess.run([sys.executable, str(CLI), *map(str, args)], cwd=ROOT, env=env, capture_output=True, text=True)
                self.assertEqual(proc.returncode == 0, success, proc.stderr or proc.stdout)
                return proc

            cli("setup", "--brand", "Test Brand")
            cli("init", project)
            (project / "script.txt").write_text("Hello world.\n\nThis is a test.", encoding="utf-8")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "libmp3lame", str(project / "assets" / "voice.mp3")],
                check=True,
            )
            words = [
                {"text": value, "start": start, "end": start + .2}
                for value, start in zip(("Hello", "world", "This", "is", "a", "test"), (.2, .6, 1.3, 1.6, 1.9, 2.2))
            ]
            timing = base / "words.json"
            timing.write_text(json.dumps(words), encoding="utf-8")
            cli("import-words", project, timing)
            cli("storyboard", project)
            cli("approve", project)
            board_path = project / "storyboard.json"
            board = json.loads(board_path.read_text(encoding="utf-8"))
            board["scenes"][0]["headline"] = "Revised headline"
            board_path.write_text(json.dumps(board), encoding="utf-8")
            cli("approve", project)
            changed_words = [*words]
            changed_words[0] = {**changed_words[0], "text": "Hey"}
            timing.write_text(json.dumps(changed_words), encoding="utf-8")
            cli("import-words", project, timing)
            board = json.loads(board_path.read_text(encoding="utf-8"))
            self.assertFalse(board["approved"])
            self.assertEqual(board["scenes"][0]["headline"], "Revised headline")
            render = cli("render", project, "--preview", success=False)
            self.assertIn("storyboard is not approved", render.stderr)
            cli("approve", project)
            board = json.loads(board_path.read_text(encoding="utf-8"))
            self.assertTrue(board["approved"])

            self.assertFalse(list((project / "renders").glob("*.mp4")))

            Image.new("RGBA", (200, 100), "blue").save(project / "assets" / "diagram.png")
            board = json.loads(board_path.read_text(encoding="utf-8"))
            first = board["scenes"][0]
            first["visual_cues"] = [{
                "asset": "assets/diagram.png", "start": first["start"] + .1,
                "duration": .8, "x": .2, "y": .2, "width": .4, "height": .2,
            }]
            board_path.write_text(json.dumps(board), encoding="utf-8")
            cli("approve", project)
            old_scene = json.loads(board_path.read_text(encoding="utf-8"))["scenes"][0]
            old_duration = old_scene["end"] - old_scene["start"]
            (project / "engine" / "video-projects" / "old").mkdir(parents=True)
            (project / "engine" / "video-projects" / "old" / "timeline.json").write_text("{}", encoding="utf-8")
            (project / "renders" / "previous.mp4").write_bytes(b"keep")
            new_voice = base / "new-voice.mp3"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=550:duration=3", "-c:a", "libmp3lame", str(new_voice)],
                check=True,
            )
            shifted_words = [{**word, "start": word["start"] + .1, "end": word["end"] + .1} for word in changed_words]
            timing.write_text(json.dumps(shifted_words), encoding="utf-8")
            retimed = base / "retimed"
            cli("retime", project, retimed, "--voice", new_voice, "--words", timing)
            new_board = json.loads((retimed / "storyboard.json").read_text(encoding="utf-8"))
            new_scene = new_board["scenes"][0]
            new_duration = new_scene["end"] - new_scene["start"]
            old_cue = old_scene["visual_cues"][0]
            new_cue = new_scene["visual_cues"][0]
            expected_start = new_scene["start"] + (old_cue["start"] - old_scene["start"]) / old_duration * new_duration
            self.assertAlmostEqual(new_cue["start"], expected_start)
            self.assertNotIn("engine", [path.name for path in retimed.iterdir()])
            self.assertFalse((retimed / "renders" / "previous.mp4").exists())
            self.assertTrue((project / "renders" / "previous.mp4").is_file())


if __name__ == "__main__":
    unittest.main()
