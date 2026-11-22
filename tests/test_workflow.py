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
sys.path.insert(0, str(ROOT / "src"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("node") and shutil.which("npm"), "FFmpeg and Node.js/npm are required")
class WorkflowTest(unittest.TestCase):
    @staticmethod
    def fake_aivee_dir(prefix: Path) -> Path:
        """Match `npm root -g`: Windows uses <prefix>/node_modules, others <prefix>/lib/node_modules."""
        root = prefix if os.name == "nt" else prefix / "lib"
        return root / "node_modules" / "aivee"

    @staticmethod
    def install_fake_aivee(prefix: Path) -> None:
        package = WorkflowTest.fake_aivee_dir(prefix)
        (package / "src").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({
            "name": "aivee", "version": "0.1.0", "bin": {"aivee": "src/cli.mjs"},
        }), encoding="utf-8")
        (package / "src" / "cli.mjs").write_text('''
import { copyFileSync, existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
if (args[0] === 'capabilities') {
  console.log(JSON.stringify({ schemaVersion: 1, node: { supported: true }, render: { requirementsAvailable: true, outputs: { mp4: { defaultCodecAvailable: true } } } }));
} else if (args[0] === 'studio' && args[1] === 'setup') {
  const home = resolve(args[args.indexOf('--home') + 1]);
  const studio = join(home, 'Studios', 'Explainer');
  const paths = { root: home, studio, library: join(studio, 'Library'), avatarPacks: join(studio, 'Library', 'Avatar Packs'), projects: join(studio, 'Projects') };
  mkdirSync(paths.avatarPacks, { recursive: true }); mkdirSync(paths.projects, { recursive: true });
  console.log(JSON.stringify(paths));
} else if (args[0] === 'studio' && args[1] === 'project' && args[2] === 'create') {
  const slug = args[4], home = resolve(args[args.indexOf('--home') + 1]);
  const [width, height] = args.at(-3).split('x').map(Number), fps = Number(args.at(-2));
  const project = join(home, 'Studios', 'Explainer', 'Projects', slug);
  const studioData = join(project, 'studio-data', 'explainer');
  if (existsSync(project)) throw new Error(`Project already exists: ${slug}`);
  for (const dir of ['assets', 'renders', 'transcripts', 'edits', 'compositions']) mkdirSync(join(project, dir), { recursive: true });
  mkdirSync(studioData, { recursive: true });
  writeFileSync(join(project, 'meta.json'), JSON.stringify({ schemaVersion: 1, id: slug, name: slug, width, height, fps, durationSeconds: Number(args.at(-1)) }));
  writeFileSync(join(project, 'timeline.json'), JSON.stringify({ project: { durationSeconds: Number(args.at(-1)) }, tracks: [], assets: [] }));
  console.log(JSON.stringify({ project, studioData }));
} else if (args[0] === 'asset' && args[1] === 'register') {
  const project = resolve(args[2]), source = resolve(args[3]), id = args[4];
  const catalog = join(project, 'test-assets.json');
  if (existsSync(join(packageRoot, 'fail-register'))) {
    unlinkSync(join(packageRoot, 'fail-register'));
    throw new Error('injected registration failure');
  }
  const path = `assets/${id}${source.slice(source.lastIndexOf('.'))}`;
  copyFileSync(source, join(project, path));
  const asset = { id, path, sha256: createHash('sha256').update(readFileSync(source)).digest('hex') };
  const assets = existsSync(catalog) ? JSON.parse(readFileSync(catalog, 'utf8')) : [];
  assets.push(asset); writeFileSync(catalog, JSON.stringify(assets));
  console.log(JSON.stringify(asset));
} else if (args[0] === 'asset' && args[1] === 'list') {
  const project = resolve(args[2]), catalog = join(project, 'test-assets.json');
  console.log(JSON.stringify({ assets: existsSync(catalog) ? JSON.parse(readFileSync(catalog, 'utf8')) : [] }));
} else throw new Error(`unsupported test command: ${args.join(' ')}`);
''', encoding="utf-8")

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
            env["NPM_CONFIG_PREFIX"] = str(base / "npm-global")
            env["PYTHONPATH"] = str(ROOT / "src")
            WorkflowTest.install_fake_aivee(Path(env["NPM_CONFIG_PREFIX"]))
            aivee_home = base / "AIVEE"
            project_slug = "film"
            project = aivee_home / "Studios" / "Explainer" / "Projects" / project_slug
            data = project / "studio-data" / "explainer"

            def cli(*args: str, success: bool = True):
                proc = subprocess.run([sys.executable, str(CLI), *map(str, args)], cwd=ROOT, env=env, capture_output=True, text=True)
                self.assertEqual(proc.returncode == 0, success, proc.stderr or proc.stdout)
                return proc

            cli("setup", "--home", aivee_home, "--brand", "Test Brand")
            cli("init", project_slug, "--format", "reel")
            studio_project = json.loads((data / "project.json").read_text(encoding="utf-8"))
            aivee_meta = json.loads((project / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual((studio_project["format"], studio_project["width"], studio_project["height"], studio_project["fps"]), ("reel", 1080, 1920, 30))
            self.assertEqual((aivee_meta["width"], aivee_meta["height"], aivee_meta["fps"]), (1080, 1920, 30))
            (data / "script.txt").write_text("Hello world.\n\nThis is a test.", encoding="utf-8")
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
            board_path = data / "storyboard.json"
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
            render = cli("render", project, success=False)
            self.assertIn("storyboard is not approved", render.stderr)
            cli("approve", project)
            board = json.loads(board_path.read_text(encoding="utf-8"))
            self.assertTrue(board["approved"])

            native_project = aivee_home / "Studios" / "Explainer" / "Projects" / "native-export"
            cli("init", "native-export")
            exported = json.loads(cli("export-avatar", project, native_project, "--json").stdout)
            self.assertTrue(exported["ok"], exported["error"])
            export_dir = Path(exported["data"]["output"])
            export_timing = json.loads((export_dir / "timing.json").read_text(encoding="utf-8"))
            self.assertEqual(export_timing["canvas"], {"width": 1080, "height": 1920, "fps": 30})
            self.assertTrue((export_dir / "words.json").is_file())
            self.assertTrue((export_dir / "narration.mp3").is_file())
            self.assertTrue(all((export_dir / item["file"]).is_file() for item in export_timing["sprites"]))
            registered = json.loads((native_project / "test-assets.json").read_text(encoding="utf-8"))
            registered_ids = {asset["id"] for asset in registered}
            self.assertIn(export_timing["narration"]["asset_id"], registered_ids)
            self.assertTrue({sprite["asset_id"] for sprite in export_timing["sprites"]} <= registered_ids)

            self.assertFalse(list((project / "renders").glob("*.mp4")))

            Image.new("RGBA", (200, 100), "blue").save(project / "assets" / "diagram.png")
            board = json.loads(board_path.read_text(encoding="utf-8"))
            first = board["scenes"][0]
            first["visual_cues"] = [{
                "asset": "assets/diagram.png", "start": first["start"] + .1,
                "duration": .8, "x": .2, "y": .2, "width": .4, "height": .2,
            }]
            board_path.write_text(json.dumps(board), encoding="utf-8")
            composition_dir = project / "compositions" / "scenes" / "scene-01"
            composition_dir.mkdir(parents=True)
            (composition_dir / "index.html").write_text("<div>Custom scene</div>", encoding="utf-8")
            (composition_dir / "visual.svg").write_text("<svg/>", encoding="utf-8")
            cli("scene-composition", project, "1", "compositions/scenes/scene-01/index.html")
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
            rejected = cli("retime", project, project_slug, "--voice", new_voice, "--words", timing, success=False)
            self.assertIn("already exists", rejected.stderr)
            invalid_timing = base / "invalid-words.json"
            invalid_timing.write_text("{}", encoding="utf-8")
            failed = cli("retime", project, "failed-retime", "--voice", new_voice, "--words", invalid_timing, success=False)
            self.assertIn("word timings must be a nonempty JSON array", failed.stderr)
            self.assertFalse((aivee_home / "Studios" / "Explainer" / "Projects" / "failed-retime").exists())
            package = WorkflowTest.fake_aivee_dir(Path(env["NPM_CONFIG_PREFIX"]))
            (package / "fail-register").write_text("fail once", encoding="utf-8")
            interrupted = cli("retime", project, "retry-retime", "--voice", new_voice, "--words", timing, success=False)
            self.assertIn("injected registration failure", interrupted.stderr)
            retry_project = aivee_home / "Studios" / "Explainer" / "Projects" / "retry-retime"
            retry_data = retry_project / "studio-data" / "explainer"
            self.assertTrue((retry_data / ".explainer-retime.json").is_file())
            cli("retime", project, "retry-retime", "--voice", new_voice, "--words", timing)
            self.assertFalse((retry_data / ".explainer-retime.json").exists())
            shifted_words = [{**word, "start": word["start"] + .1, "end": word["end"] + .1} for word in changed_words]
            timing.write_text(json.dumps(shifted_words), encoding="utf-8")
            retimed = aivee_home / "Studios" / "Explainer" / "Projects" / "retimed"
            cli("retime", project, "retimed", "--voice", new_voice, "--words", timing)
            retimed_data = retimed / "studio-data" / "explainer"
            retimed_meta = json.loads((retimed / "meta.json").read_text(encoding="utf-8"))
            retimed_project = json.loads((retimed_data / "project.json").read_text(encoding="utf-8"))
            self.assertEqual((retimed_project["format"], retimed_meta["width"], retimed_meta["height"], retimed_meta["fps"]), ("reel", 1080, 1920, 30))
            new_board = json.loads((retimed_data / "storyboard.json").read_text(encoding="utf-8"))
            new_scene = new_board["scenes"][0]
            self.assertEqual(new_scene["composition"], "compositions/scenes/scene-01/index.html")
            self.assertTrue((retimed / new_scene["composition"]).is_file())
            self.assertTrue((retimed / "compositions" / "scenes" / "scene-01" / "visual.svg").is_file())
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
