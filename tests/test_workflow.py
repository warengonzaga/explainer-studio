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


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "explainer.py"


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class WorkflowTest(unittest.TestCase):
    def test_approved_storyboard_renders_and_changes_invalidate_approval(self):
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
            cli("render", project, "--preview", success=False)
            cli("approve", project)
            cli("render", project, "--preview")
            video = project / "renders" / "preview.mp4"
            self.assertTrue(video.is_file())
            cli("check", project, video)
            cli("contact-sheet", project, video)
            self.assertTrue((project / "renders" / "contact-sheet.jpg").is_file())
            cli("sync-check", project, video, "--render-words", timing)


if __name__ == "__main__":
    unittest.main()
