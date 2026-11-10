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
from .common import ProjectError, probe_duration, project_file, read_json, studio_home, write_json
from .render import avatar_box, render_background, storyboard_hash
from .timing import validate_storyboard, validate_words


AIVEE_VERSION = "0.1.0"
UNDICI_VERSION = "7.30.2"


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise ProjectError("Node.js 22 or later is required for AIVEE")
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True)
    except OSError as exc:
        raise ProjectError("Could not run Node.js; repair the Node.js installation and retry") from exc
    version = result.stdout.strip().removeprefix("v").split(".", 1)[0]
    if result.returncode or not version.isdigit() or int(version) < 22:
        raise ProjectError("Node.js 22 or later is required for AIVEE")
    return node


def _package_cli(package_root: Path) -> tuple[Path, str] | None:
    manifest_path = package_root / "package.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = read_json(manifest_path)
    except ProjectError:
        return None
    if not isinstance(manifest, dict) or manifest.get("name") != "aivee" or manifest.get("version") != AIVEE_VERSION:
        return None
    entry = manifest.get("bin")
    entry = entry.get("aivee") if isinstance(entry, dict) else entry
    if not isinstance(entry, str):
        return None
    root = package_root.resolve()
    cli = (root / entry).resolve()
    if not cli.is_relative_to(root) or not cli.is_file():
        return None
    return cli, str(root)


def _installed_aivee(node: str) -> tuple[list[str], str] | None:
    npm = shutil.which("npm")
    roots = []
    if npm:
        try:
            result = subprocess.run([npm, "root", "-g"], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                roots.append(Path(result.stdout.strip()))
        except OSError:
            pass
    runtime = studio_home() / "runtime"
    try:
        manifest = read_json(runtime / "package.json")
    except ProjectError:
        manifest = None
    if (
        isinstance(manifest, dict)
        and manifest.get("dependencies", {}).get("aivee") == AIVEE_VERSION
        and manifest.get("overrides", {}).get("hyperframes", {}).get("undici") == UNDICI_VERSION
    ):
        roots.append(runtime / "node_modules")
    for modules in roots:
        resolved = _package_cli(modules / "aivee")
        if resolved:
            cli, package_root = resolved
            return [node, str(cli)], package_root
    return None


def resolve_aivee() -> tuple[list[str], str]:
    node = _node()
    checkout = os.environ.get("AI_VIDEO_ENGINE_PATH")
    if checkout:
        root = Path(checkout).expanduser().resolve()
        cli = root / "src" / "cli.mjs"
        if not cli.is_file():
            raise ProjectError(f"AI_VIDEO_ENGINE_PATH must point to an Engine checkout with src/cli.mjs: {root}")
        return [node, str(cli)], str(root)
    installed = _installed_aivee(node)
    if installed:
        return installed
    raise ProjectError(f"AIVEE {AIVEE_VERSION} is not installed; run `explainer install-engine` to install it")


def ensure_aivee() -> tuple[list[str], str]:
    node = _node()
    if os.environ.get("AI_VIDEO_ENGINE_PATH"):
        return resolve_aivee()
    installed = _installed_aivee(node)
    if installed:
        return installed
    npm = shutil.which("npm")
    if not npm:
        raise ProjectError("npm is required to install AIVEE; install Node.js 22 or later with npm")
    runtime = studio_home() / "runtime"
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        write_json(runtime / "package.json", {
            "private": True,
            "dependencies": {"aivee": AIVEE_VERSION},
            "overrides": {"hyperframes": {"undici": UNDICI_VERSION}},
        })
        result = subprocess.run(
            [npm, "install"],
            cwd=runtime,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ProjectError("Could not run npm to install AIVEE; check npm permissions and retry") from exc
    if result.returncode:
        raise ProjectError(f"Could not install AIVEE {AIVEE_VERSION} (npm exit {result.returncode}); check network access and npm configuration")
    installed = _installed_aivee(node)
    if not installed:
        raise ProjectError(f"AIVEE {AIVEE_VERSION} installation completed but the CLI could not be found")
    return installed


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


def _engine_cli(command: list[str], cwd: Path, args: list[str], env: dict | None = None) -> str:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    result = subprocess.run(
        [*command, *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=process_env,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ProjectError(f"AIVEE command failed: {detail[-1200:]}")
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


def _visual_layers(root: Path, cue: dict, frame_size: tuple[int, int]) -> list[tuple[Path, dict]]:
    source = project_file(root, cue["asset"])
    layer_dir = source.with_name(f"{source.stem}.layers")
    manifest_path = layer_dir / "manifest.json"
    if not manifest_path.is_file():
        return [(source, cue)]
    manifest = read_json(manifest_path)
    entries = manifest.get("layers") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        return [(source, cue)]
    with Image.open(source) as image:
        source_width, source_height = image.size
    frame_width, frame_height = frame_size
    cue_x, cue_y = float(cue.get("x", 0.5)), float(cue.get("y", 0.55))
    cue_width, cue_height = float(cue.get("width", 0.38)), float(cue.get("height", 0.2))
    source_aspect = source_width / source_height
    box_aspect = cue_width * frame_width / (cue_height * frame_height)
    if source_aspect > box_aspect:
        display_width = cue_width
        display_height = display_width * frame_width / source_aspect / frame_height
    else:
        display_height = cue_height
        display_width = display_height * frame_height * source_aspect / frame_width
    display_y = cue_y + (cue_height - display_height) / 2
    stagger = min(0.22, float(cue["duration"]) / max(6, len(entries) * 2))
    result = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ProjectError(f"invalid graphic layer entry in {manifest_path}")
        path = layer_dir / entry["file"]
        if path.resolve().parent != layer_dir.resolve() or not path.is_file():
            raise ProjectError(f"graphic layer file not found in {manifest_path}: {entry['file']}")
        try:
            origin_x, origin_y = int(entry["x"]), int(entry["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"graphic layer origin is invalid in {manifest_path}") from exc
        with Image.open(path) as image:
            bounds = image.getbbox() or (0, 0, image.width, image.height)
            left, top, right, bottom = bounds[0] + origin_x, bounds[1] + origin_y, bounds[2] + origin_x, bounds[3] + origin_y
        if left < 0 or top < 0 or right > source_width or bottom > source_height:
            raise ProjectError(f"graphic layer bounds exceed the source image in {manifest_path}")
        result.append((path, {
            **cue,
            "start": float(cue["start"]) + index * stagger,
            "duration": float(cue["duration"]) - index * stagger,
            "x": cue_x + left / source_width * display_width,
            "y": display_y + top / source_height * display_height,
            "width": (right - left) / source_width * display_width,
            "height": (bottom - top) / source_height * display_height,
            "layered": True,
            "layer_index": index,
        }))
    return result


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

    engine_command, _ = resolve_aivee()
    width, height = (1080, 1920) if portrait else (int(project.get("width", 1920)), int(project.get("height", 1080)))
    fps = int(project.get("fps", 60))
    if preview:
        width, height = round(width / 2), round(height / 2)
        fps = min(fps, 20)
    if width < 320 or height < 240 or fps < 1 or fps > 60:
        raise ProjectError("invalid project resolution or frame rate")

    scratch_root = root / ".work"
    scratch_root.mkdir(parents=True, exist_ok=True)
    engine_workspace = root / "engine"
    engine_workspace.mkdir(parents=True, exist_ok=True)
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
        project_path = engine_workspace / "video-projects" / slug
        _engine_cli(engine_command, engine_workspace, ["project", "create", slug, f"{width}x{height}", str(fps), f"{duration:.6f}"])
        narration = temporary / f"studio-narration{voice.suffix.lower()}"
        shutil.copy2(voice, narration)
        visual_records = []
        visual_index = 0
        for scene in scenes:
            for cue in scene.get("visual_cues", []):
                for visual_path, visual_cue in _visual_layers(root, cue, (width, height)):
                    visual_index += 1
                    visual_id = f"visual-{visual_index:02d}"
                    visual_records.append((visual_id, visual_path, visual_cue))
        music = project.get("music")
        if music:
            music_path = project_file(root, music)
            if not music_path.is_file():
                raise ProjectError(f"music not found: {music_path}")
            music_copy = temporary / f"studio-music{music_path.suffix.lower()}"
            shutil.copy2(music_path, music_copy)
        asset_records = [(path, path.stem.lower()) for path in [background, narration, *avatar_paths.values()]]
        if music:
            asset_records.append((music_copy, "studio-music"))
        asset_records.extend((source, asset_id) for asset_id, source, _ in visual_records)
        for path, asset_id in dict.fromkeys(asset_records):
            _engine_cli(engine_command, project_path, ["asset", "register", str(project_path), str(path), asset_id])

        timeline_path = project_path / "timeline.json"
        timeline = read_json(timeline_path)
        transcript_path = temporary / "studio-transcript.json"
        write_json(transcript_path, {
            "schemaVersion": 1, "durationSeconds": duration, "granularity": "word",
            "words": [{"text": item["text"].strip(), "start": float(item["start"]), "end": min(duration, float(item["end"]))} for item in words],
        })
        type_scale = min(width / 1080, height / 1920)
        is_portrait = height > width
        caption_options_path = temporary / "studio-caption-options.json"
        write_json(caption_options_path, {
            "layoutPreset": "speechBubble",
            "x": 0.36 if is_portrait else 0.31, "y": 0.63 if is_portrait else 0.46,
            "width": 0.58 if is_portrait else 0.65, "height": 0.1 if is_portrait else 0.12,
            "fontSize": max(8, round(48 * type_scale)), "wordsPerCaption": 6, "wordsPerLine": 3,
            "wordHighlight": True, "wordHighlightColor": "#426BEB", "wordHighlightAnimation": "pop",
            "color": "#172236", "backgroundColor": "#FFFFFF",
            "bubble": {"tailSide": "left", "tailPosition": 0.35, "tailSizePixels": max(8, round(26 * type_scale)), "cornerRadiusPixels": max(8, round(28 * type_scale))},
        })
        caption_track_path = temporary / "studio-captions.json"
        _engine_cli(engine_command, project_path, ["timeline", "captions", str(transcript_path), str(caption_track_path), str(caption_options_path)])
        captions = read_json(caption_track_path)
        captions["order"] = 4
        title_track = {
            "id": "studio-scene-headings", "kind": "overlay", "order": 2,
            "clips": [{
                "id": f"scene-heading-{index + 1:02d}", "timelineStart": float(scene["start"]),
                "durationSeconds": float(scene["end"]) - float(scene["start"]),
                "text": scene.get("visual_label") or scene["headline"],
                "x": 0.08, "y": 0.16, "width": 0.82, "height": 0.08,
                "fontSize": max(8, round(54 * type_scale)), "fontWeight": 800, "color": "#172236",
                "backgroundColor": "transparent", "textAlign": "center", "verticalAlign": "center",
                "keyframes": [
                    {"time": 0, "properties": {"y": 0.18, "opacity": 0}},
                    {"time": min(0.45, (float(scene["end"]) - float(scene["start"])) / 3), "properties": {"y": 0.16, "opacity": 1}, "ease": "power2.out"},
                ],
            } for index, scene in enumerate(scenes)],
        }
        visual_clips = []
        for index, (visual_id, _, cue) in enumerate(visual_records):
            duration_seconds = float(cue["duration"])
            x, y = float(cue.get("x", 0.5)), float(cue.get("y", 0.55))
            width, height = float(cue.get("width", 0.38)), float(cue.get("height", 0.2))
            arrival = min(0.48, duration_seconds * 0.35)
            shift_x = (0.028 if cue.get("layer_index", index) % 2 == 0 else -0.028) if cue.get("layered") else 0.025
            shift_y = min(0.025, height * 0.15) if cue.get("layered") else min(0.035, height * 0.12)
            start_props = {"x": x + shift_x, "y": y + shift_y, "width": width * 0.88, "height": height * 0.88, "opacity": 0}
            end_props = {"x": x, "y": y, "width": width, "height": height, "opacity": 1}
            if cue.get("layered"):
                start_props["rotationDegrees"] = -2 if cue["layer_index"] % 2 == 0 else 2
                end_props["rotationDegrees"] = 0
            visual_clips.append({
                "id": f"visual-{index + 1:02d}", "assetId": visual_id,
                "sourceIn": 0, "sourceOut": duration_seconds,
                "timelineStart": float(cue["start"]), "durationSeconds": duration_seconds,
                "x": x, "y": y, "width": width, "height": height, "fit": "contain",
                "keyframes": [
                    {"time": 0, "properties": start_props},
                    {"time": arrival, "properties": end_props, "ease": "back.out" if cue.get("layered") else "power2.out"},
                    {"time": duration_seconds - 0.18, "properties": {"opacity": 1}},
                    {"time": duration_seconds, "properties": {"x": x - 0.015, "opacity": 0}, "ease": "power2.in"},
                ],
            })
        timeline["tracks"] = [
            {"id": "studio-background", "kind": "video", "order": 0, "clips": [
                {"id": "background", "assetId": "studio-background", "sourceIn": 0, "sourceOut": duration, "timelineStart": 0, "durationSeconds": duration, "x": 0, "y": 0, "width": 1, "height": 1, "fit": "fill"},
            ]},
            {"id": "studio-visuals", "kind": "video", "order": 1, "allowOverlap": True, "clips": visual_clips},
            title_track,
            {"id": "studio-avatar", "kind": "video", "order": 3, "clips": [
                {"id": f"avatar-{index + 1}", "assetId": f"avatar-{item['pose']}-{item['mouth']}-{'blink' if item['blink'] else 'open'}", "sourceIn": 0, "sourceOut": item["end"] - item["start"], "timelineStart": item["start"], "durationSeconds": item["end"] - item["start"], "x": 0, "y": 0, "width": 1, "height": 1, "fit": "fill"}
                for index, item in enumerate(intervals)
            ]},
            captions,
            {"id": "studio-voice", "kind": "audio", "order": 5, "clips": [
                {"id": "narration", "assetId": "studio-narration", "sourceIn": 0, "sourceOut": duration, "timelineStart": 0, "durationSeconds": duration},
            ]},
        ]
        if music:
            music_duration = probe_duration(music_copy)
            music_clip_duration = min(duration, music_duration)
            timeline["tracks"].append({"id": "studio-music", "kind": "audio", "order": 6, "clips": [
                {"id": "music-bed", "assetId": "studio-music", "sourceIn": 0, "sourceOut": music_clip_duration, "timelineStart": 0, "durationSeconds": music_clip_duration, "volume": 0.1},
            ]})
            timeline["audioMix"] = {"sidechain": [{"sourceTrackId": "studio-voice", "targetTrackId": "studio-music", "thresholdDb": -34, "ratio": 5, "attackSeconds": 0.02, "releaseSeconds": 0.4}]}
        timeline["audioMastering"] = {"integratedLoudnessLUFS": -16, "truePeakDBTP": -1.5, "loudnessRangeLU": 11}
        timeline["project"]["durationSeconds"] = duration
        _write_engine_timeline(project_path, timeline_path, timeline)
        _engine_cli(engine_command, project_path, ["timeline", "validate", str(timeline_path)])
        output.parent.mkdir(parents=True, exist_ok=True)
        _engine_cli(
            engine_command,
            project_path,
            ["timeline", "render", str(project_path), str(timeline_path), str(output.resolve()), "draft" if preview else "standard"],
            _browser_env(temporary / "hyperframes-cache"),
        )
    return output
