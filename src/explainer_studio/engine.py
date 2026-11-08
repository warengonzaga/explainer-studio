"""Export Studio-owned explainer layers to the generic Engine timeline."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from bisect import bisect_right
from pathlib import Path
from uuid import uuid4

from PIL import Image

from .audio import mouth_at, mouth_track, phonetic_mouth_track
from .avatar import _is_blinking, draw_avatar
from .common import ProjectError, probe_duration, project_file, read_json, write_json
from .render import avatar_box, render_background, storyboard_hash
from .timing import validate_storyboard, validate_words


def resolve_engine_root(profile: dict) -> Path:
    configured = os.environ.get("AI_VIDEO_ENGINE_PATH") or profile.get("engine_path")
    if not configured:
        raise ProjectError("AI Video Editing Engine path is missing; set it during `explainer setup`")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir() or not (root / "src" / "cli.mjs").is_file():
        raise ProjectError(f"Engine path must contain src/cli.mjs: {root}")
    if not (root / "node_modules" / "hyperframes" / "package.json").is_file() or not (root / "node_modules" / "gsap" / "package.json").is_file():
        raise ProjectError(f"Engine dependencies are missing; run `npm install` in {root}")
    if not shutil.which("node"):
        raise ProjectError("Node.js is required to render through the AI Video Editing Engine")
    return root


def avatar_intervals(keys: list[tuple[str, str, bool]], fps: int, duration: float) -> list[dict]:
    intervals = []
    start = 0
    for index in range(1, len(keys) + 1):
        if index < len(keys) and keys[index] == keys[start]:
            continue
        end = min(duration, index / fps)
        begin = start / fps
        if end > begin:
            pose, mouth, blink = keys[start]
            intervals.append({"pose": pose, "mouth": mouth, "blink": blink, "start": begin, "end": end})
        start = index
    return intervals


def _engine_cli(root: Path, args: list[str], env: dict | None = None) -> str:
    cli = root / "src" / "cli.mjs"
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    result = subprocess.run(
        ["node", str(cli), *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=process_env,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ProjectError(f"Engine command failed: {detail[-1200:]}")
    return result.stdout.strip()


def _browser_env(cache_dir: Path) -> dict[str, str]:
    environment = {"HYPERFRAMES_CACHE_DIR": str(cache_dir)}
    configured = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    browsers = [configured] if configured else [shutil.which(name) for name in ("chrome", "google-chrome", "chromium", "msedge")]
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            browsers.extend((
                str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            ))
    browser = next((path for path in browsers if path and Path(path).is_file()), None)
    if browser:
        environment["HYPERFRAMES_BROWSER_PATH"] = browser
    return environment


def _write_engine_timeline(root: Path, path: Path, timeline: dict) -> None:
    write_json(path, timeline)
    canonicalize = (
        "const fs=require('node:fs');const path=process.argv[1];"
        "fs.writeFileSync(path,JSON.stringify(JSON.parse(fs.readFileSync(path,'utf8')),null,2)+'\\n')"
    )
    result = subprocess.run(["node", "-e", canonicalize, str(path)], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise ProjectError(f"Could not normalize Engine timeline JSON: {(result.stderr or result.stdout).strip()}")


def render_with_engine(root: Path, output: Path, profile: dict, preview: bool = False, portrait: bool = False) -> Path:
    root = root.resolve()
    project = read_json(root / "project.json")
    board = read_json(root / "storyboard.json")
    if not board.get("approved") or board.get("approval_hash") != storyboard_hash(board):
        raise ProjectError("storyboard is not approved; review it in chat, then run `explainer approve <project>`")
    voice = project_file(root, project["voice"])
    duration = probe_duration(voice)
    validate_storyboard(root, board, duration)
    words = read_json(root / "words.json")
    validate_words(words, duration)
    if output.exists():
        raise ProjectError(f"output already exists: {output}")

    engine_root = resolve_engine_root(profile)
    width, height = (1080, 1920) if portrait else (int(project.get("width", 1920)), int(project.get("height", 1080)))
    fps = int(project.get("fps", 60))
    if preview:
        width, height = round(width / 2), round(height / 2)
        fps = min(fps, 20)
    if width < 320 or height < 240 or fps < 1 or fps > 60:
        raise ProjectError("invalid project resolution or frame rate")

    scratch_root = root / ".work"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engine-export-", dir=scratch_root) as temporary:
        temporary = Path(temporary)
        background = render_background(root, temporary / "studio-background.mp4", preview, portrait)
        scenes = board["scenes"]
        ends = [float(scene["end"]) for scene in scenes]
        states = phonetic_mouth_track(voice, duration, temporary, profile.get("rhubarb_path")) or mouth_track(voice)
        keys = []
        for frame in range(math.ceil(duration * fps)):
            time = min(duration - 1e-6, frame / fps)
            scene_index = min(len(scenes) - 1, bisect_right(ends, time))
            keys.append((scenes[scene_index].get("pose", "idle"), mouth_at(states, time), _is_blinking(time)))
        intervals = avatar_intervals(keys, fps, duration)

        avatar_paths = {}
        size = (width, height)
        for pose, mouth, blinking in {key for key in keys}:
            time = 0.05 if blinking else 1.0
            filename = f"avatar-{pose}-{mouth}-{'blink' if blinking else 'open'}.png"
            sprite = Image.new("RGBA", size, (0, 0, 0, 0))
            draw_avatar(sprite, root, project, pose, mouth, time, avatar_box(size))
            path = temporary / filename
            sprite.save(path)
            avatar_paths[(pose, mouth, blinking)] = path

        slug = f"studio-{uuid4().hex[:12]}"
        project_path = engine_root / "video-projects" / slug
        _engine_cli(engine_root, ["project", "create", slug, f"{width}x{height}", str(fps), f"{duration:.6f}"])
        narration = temporary / f"studio-narration{voice.suffix.lower()}"
        shutil.copy2(voice, narration)
        assets = [background, narration, *avatar_paths.values()]
        music = project.get("music")
        if music:
            music_path = project_file(root, music)
            if not music_path.is_file():
                raise ProjectError(f"music not found: {music_path}")
            music_copy = temporary / f"studio-music{music_path.suffix.lower()}"
            shutil.copy2(music_path, music_copy)
            assets.append(music_copy)
        for path in dict.fromkeys(assets):
            _engine_cli(engine_root, ["asset", "register", str(project_path), str(path), path.stem.lower()])

        timeline_path = project_path / "timeline.json"
        timeline = read_json(timeline_path)
        timeline["tracks"] = [
            {"id": "studio-background", "kind": "video", "order": 0, "clips": [
                {"id": "background", "assetId": "studio-background", "sourceIn": 0, "sourceOut": duration, "timelineStart": 0, "durationSeconds": duration, "x": 0, "y": 0, "width": 1, "height": 1, "fit": "fill"},
            ]},
            {"id": "studio-avatar", "kind": "video", "order": 1, "clips": [
                {"id": f"avatar-{index + 1}", "assetId": f"avatar-{item['pose']}-{item['mouth']}-{'blink' if item['blink'] else 'open'}", "sourceIn": 0, "sourceOut": item["end"] - item["start"], "timelineStart": item["start"], "durationSeconds": item["end"] - item["start"], "x": 0, "y": 0, "width": 1, "height": 1, "fit": "fill"}
                for index, item in enumerate(intervals)
            ]},
            {"id": "studio-voice", "kind": "audio", "order": 2, "clips": [
                {"id": "narration", "assetId": "studio-narration", "sourceIn": 0, "sourceOut": duration, "timelineStart": 0, "durationSeconds": duration},
            ]},
        ]
        if music:
            music_duration = probe_duration(music_copy)
            music_clip_duration = min(duration, music_duration)
            timeline["tracks"].append({"id": "studio-music", "kind": "audio", "order": 3, "clips": [
                {"id": "music-bed", "assetId": "studio-music", "sourceIn": 0, "sourceOut": music_clip_duration, "timelineStart": 0, "durationSeconds": music_clip_duration, "volume": 0.1},
            ]})
            timeline["audioMix"] = {"sidechain": [{"sourceTrackId": "studio-voice", "targetTrackId": "studio-music", "thresholdDb": -34, "ratio": 5, "attackSeconds": 0.02, "releaseSeconds": 0.4}]}
        timeline["audioMastering"] = {"integratedLoudnessLUFS": -16, "truePeakDBTP": -1.5, "loudnessRangeLU": 11}
        timeline["project"]["durationSeconds"] = duration
        _write_engine_timeline(engine_root, timeline_path, timeline)
        relative_timeline = timeline_path.relative_to(engine_root)
        _engine_cli(engine_root, ["timeline", "validate", str(relative_timeline)])
        output.parent.mkdir(parents=True, exist_ok=True)
        _engine_cli(
            engine_root,
            ["timeline", "render", str(project_path), str(relative_timeline), str(output.resolve()), "draft" if preview else "standard"],
            _browser_env(temporary / "hyperframes-cache"),
        )
    return output
