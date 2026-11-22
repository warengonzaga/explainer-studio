"""Export Studio-owned explainer layers to the generic Engine timeline."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from bisect import bisect_right
from pathlib import Path
from uuid import uuid4

from .audio import mouth_at, mouth_track, phonetic_mouth_track
from .captions import caption_options, DEFAULT_HOOK_FONT, font_stack
from .common import ProjectError, file_hash, probe_duration, project_file, read_json, studio_data, studio_home, write_json
from .timing import storyboard_hash, validate_storyboard, validate_words


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
    if not isinstance(manifest, dict) or manifest.get("name") != "aivee":
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


def _npm_global_root() -> Path | None:
    npm = shutil.which("npm")
    try:
        result = subprocess.run([npm, "root", "-g"], capture_output=True, text=True) if npm else None
    except OSError:
        return None
    return Path(result.stdout.strip()) if result and result.returncode == 0 and result.stdout.strip() else None


def _installed_aivee(node: str) -> tuple[list[str], str] | None:
    modules = _npm_global_root()
    resolved = _package_cli(modules / "aivee") if modules else None
    if not resolved:
        return None
    cli, package_root = resolved
    return [node, str(cli)], package_root


def _global_aivee_path() -> Path | None:
    modules = _npm_global_root()
    return modules / "aivee" if modules else None


def resolve_aivee() -> tuple[list[str], str]:
    node = _node()
    installed = _installed_aivee(node)
    if installed and _verify_aivee(installed[0]):
        return installed
    if installed:
        raise ProjectError("The global AIVEE installation is incompatible or missing render requirements; run `npm install --global aivee@latest` and retry")
    package = _global_aivee_path()
    if package and package.exists():
        raise ProjectError(f"A global AIVEE package exists but its CLI is invalid: {package}; repair or remove it before installing AIVEE again")
    raise ProjectError("AIVEE is not installed; run `explainer install-engine` to install it globally")


def ensure_aivee() -> tuple[list[str], str]:
    node = _node()
    installed = _installed_aivee(node)
    if installed:
        if not _verify_aivee(installed[0]):
            raise ProjectError("The global AIVEE installation is incompatible or missing render requirements; update it with `npm install --global aivee@latest` and retry")
        return installed
    package = _global_aivee_path()
    if package and package.exists():
        raise ProjectError(f"A global AIVEE package exists but its CLI is invalid: {package}; repair or remove it before installing AIVEE again")
    npm = shutil.which("npm")
    if not npm:
        raise ProjectError("npm is required to install AIVEE; install Node.js 22 or later with npm")
    try:
        result = subprocess.run(
            [npm, "install", "--global", "aivee@latest"],
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ProjectError("Could not run npm to install AIVEE; check npm permissions and retry") from exc
    if result.returncode:
        raise ProjectError(f"Could not install AIVEE globally (npm exit {result.returncode}); check network access, npm permissions, and npm configuration")
    installed = _installed_aivee(node)
    if not installed or not _verify_aivee(installed[0]):
        raise ProjectError("AIVEE installation completed but the global CLI is unavailable or incompatible; check npm's global prefix and render requirements")
    return installed


def _verify_aivee(command: list[str]) -> bool:
    try:
        result = subprocess.run([*command, "capabilities"], capture_output=True, text=True, timeout=30)
        if result.returncode:
            return False
        capabilities = json.loads(result.stdout)
        return (
            capabilities.get("schemaVersion") == 1
            and capabilities.get("node", {}).get("supported") is True
            and capabilities.get("render", {}).get("requirementsAvailable") is True
            and capabilities.get("render", {}).get("outputs", {}).get("mp4", {}).get("defaultCodecAvailable") is True
        )
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError):
        return False


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


def setup_aivee_home(home: Path) -> dict:
    command, _ = ensure_aivee()
    result = _engine_cli(command, Path.home(), ["studio", "setup", "explainer", "--home", str(home)])
    try:
        return json.loads(result)
    except json.JSONDecodeError as exc:
        raise ProjectError("AIVEE returned an invalid workspace response") from exc


def create_aivee_project(
    home: Path,
    slug: str,
    duration: float = 10,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 60,
) -> dict:
    command, _ = resolve_aivee()
    result = _engine_cli(
        command, home,
        ["studio", "project", "create", "explainer", slug, "--home", str(home), f"{width}x{height}", str(fps), f"{duration:.6f}"],
    )
    try:
        return json.loads(result)
    except json.JSONDecodeError as exc:
        raise ProjectError("AIVEE returned an invalid project response") from exc


def register_asset(project: Path, source: Path, asset_id: str) -> dict:
    command, _ = resolve_aivee()
    result = _engine_cli(command, project, ["asset", "register", str(project), str(source), asset_id])
    try:
        return json.loads(result)
    except json.JSONDecodeError as exc:
        raise ProjectError("AIVEE returned an invalid asset response") from exc


def list_project_assets(project: Path) -> dict:
    command, _ = resolve_aivee()
    result = _engine_cli(command, project, ["asset", "list", str(project)])
    try:
        return json.loads(result)
    except json.JSONDecodeError as exc:
        raise ProjectError("AIVEE returned an invalid asset list") from exc


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


def _register_render_asset(
    engine_command: list[str], project: Path, source: Path, asset_id: str,
    assets: dict, owned_asset_ids: set[str],
) -> dict:
    safe_id = re.sub(r"[^a-z0-9]+", "-", asset_id.lower()).strip("-") or "asset"
    extension = re.sub(r"[^a-z0-9]+", "", source.suffix.lower().lstrip(".")) or "media"
    registered_id = f"studio-render-{safe_id}-{extension}"
    existing = assets.get(registered_id)
    if existing and existing.get("sha256") == file_hash(source):
        asset = existing
    else:
        if existing and registered_id not in owned_asset_ids:
            raise ProjectError(f"render asset ID conflicts with existing project media: {registered_id}")
        args = (
            ["asset", "relink", str(project), registered_id, str(source)]
            if existing else ["asset", "register", str(project), str(source), registered_id]
        )
        asset = json.loads(_engine_cli(engine_command, project, args))
        assets[registered_id] = asset
    return {**asset, "id": registered_id}


def _visual_layers(root: Path, cue: dict, frame_size: tuple[int, int], asset_dir: Path) -> list[tuple[Path, dict]]:
    from PIL import Image

    source = project_file(root, cue["asset"])
    layer_dir = source.with_name(f"{source.stem}.layers")
    manifest_path = layer_dir / "manifest.json"
    if not manifest_path.is_file():
        return [(source, cue)]
    root = root.resolve()
    layer_root = layer_dir.resolve()
    manifest = manifest_path.resolve()
    if not layer_root.is_relative_to(root) or not manifest.is_relative_to(layer_root):
        raise ProjectError(f"graphic layer manifest must stay inside the project: {manifest_path}")
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
        resolved_path = path.resolve()
        if resolved_path.parent != layer_root or not resolved_path.is_file():
            raise ProjectError(f"graphic layer file not found in {manifest_path}: {entry['file']}")
        try:
            origin_x, origin_y = int(entry["x"]), int(entry["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"graphic layer origin is invalid in {manifest_path}") from exc
        with Image.open(resolved_path) as source_image:
            image = source_image.convert("RGBA")
            bounds = image.getchannel("A").getbbox() or (0, 0, image.width, image.height)
            left, top, right, bottom = bounds[0] + origin_x, bounds[1] + origin_y, bounds[2] + origin_x, bounds[3] + origin_y
            cropped_path = asset_dir / f"graphic-layer-{uuid4().hex}.png"
            image.crop(bounds).save(cropped_path)
        if left < 0 or top < 0 or right > source_width or bottom > source_height:
            raise ProjectError(f"graphic layer bounds exceed the source image in {manifest_path}")
        result.append((cropped_path, {
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


def _check_reels_box(x: float, y: float, width: float, height: float, label: str) -> None:
    if x < 0.093 - 1e-6 or y < 0.13 - 1e-6 or x + width > 0.82 + 1e-6 or y + height > 0.771 + 1e-6:
        raise ProjectError(f"Reels {label} is outside the safe area; reposition it before rendering")


def custom_scene_clips(scenes: list[dict]) -> list[dict]:
    return [
        {"id": f"custom-scene-{index + 1:02d}", "composition": scene["composition"],
         "timelineStart": float(scene["start"]), "durationSeconds": float(scene["end"]) - float(scene["start"])}
        for index, scene in enumerate(scenes) if scene.get("composition")
    ]


def portrait_regions() -> dict[str, dict[str, float]]:
    """Default portrait visual, speech bubble, and avatar boxes inside the Reels safe area."""
    from .avatar import PORTRAIT_AVATAR

    return {
        "visual": {"x": 0.13, "y": 0.26, "width": 0.66, "height": 0.30},
        "bubble": {"x": 0.46, "y": 0.59, "width": 0.34, "height": 0.10},
        "avatar": PORTRAIT_AVATAR,
    }


def portrait_caption() -> dict[str, int]:
    """Portrait speech-bubble type. AIVEE keeps the font size and paints overflow outside the box."""
    return {"fontSize": 32, "wordsPerLine": 2, "wordsPerCaption": 6, "paddingPixels": 22}


def ensure_render_allowed(board: dict, *, preview: bool) -> None:
    """Final renders require the current storyboard approval. Draft previews do not."""
    if preview:
        return
    if not board.get("approved") or board.get("approval_hash") != storyboard_hash(board):
        raise ProjectError("storyboard is not approved; review it in chat, then run `explainer approve <project>`")


def draft_mark_track(duration: float, *, portrait: bool, type_scale: float) -> dict:
    """A visible DRAFT label kept inside the portrait safe area."""
    clip = {
        "id": "draft-mark", "timelineStart": 0, "durationSeconds": duration, "text": "DRAFT",
        "x": 0.64, "y": 0.70, "width": 0.14, "height": 0.04,
        "fontSize": max(8, round(22 * type_scale)), "fontWeight": 800,
        "color": "#172236", "backgroundColor": "#F6F8FC",
        "textAlign": "center", "verticalAlign": "center",
    }
    if portrait:
        _check_reels_box(clip["x"], clip["y"], clip["width"], clip["height"], "draft mark")
    return {"id": "studio-draft", "kind": "overlay", "order": 8, "clips": [clip]}


def render_with_engine(root: Path, output: Path, profile: dict, preview: bool = False, portrait: bool = False) -> Path:
    from PIL import Image
    from .avatar import _is_blinking, avatar_box, draw_avatar

    root = root.resolve()
    data = studio_data(root)
    project = read_json(data / "project.json")
    board = read_json(data / "storyboard.json")
    ensure_render_allowed(board, preview=preview)
    voice = project_file(root, project["voice"])
    duration = probe_duration(voice)
    validate_storyboard(root, board, duration)
    words = read_json(data / "words.json")
    validate_words(words, duration)
    if output.exists():
        raise ProjectError(f"output already exists: {output}")

    engine_command, _ = resolve_aivee()
    width, height = (1080, 1920) if portrait else (int(project.get("width", 1920)), int(project.get("height", 1080)))
    portrait = portrait or height > width
    fps = int(project.get("fps", 60))
    if preview:
        width, height = round(width / 2), round(height / 2)
        fps = min(fps, 20)
    if width < 320 or height < 240 or fps < 1 or fps > 60:
        raise ProjectError("invalid project resolution or frame rate")

    scratch_root = data / ".work"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engine-export-", dir=scratch_root) as temporary:
        temporary = Path(temporary)
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
        if portrait:
            ax, ay, aw, ah = avatar_box(size)
            _check_reels_box(ax / width, ay / height, aw / width, ah / height, "avatar")
        for pose, mouth, blinking in {key for key in keys}:
            time = 0.05 if blinking else 1.0
            filename = f"avatar-{pose}-{mouth}-{'blink' if blinking else 'open'}.png"
            sprite = Image.new("RGBA", size, (0, 0, 0, 0))
            draw_avatar(sprite, root, project, pose, mouth, time, avatar_box(size))
            path = temporary / filename
            sprite.save(path)
            avatar_paths[(pose, mouth, blinking)] = path

        project_path = root
        narration = temporary / f"studio-narration{voice.suffix.lower()}"
        shutil.copy2(voice, narration)
        visual_records = []
        visual_index = 0
        visual_region = portrait_regions()["visual"] if portrait else None
        for scene in scenes:
            if scene.get("composition"):
                continue
            for cue in scene.get("visual_cues", []):
                if visual_region is not None:
                    cue = {**visual_region, **cue}
                    x, y = float(cue["x"]), float(cue["y"])
                    cue_width, cue_height = float(cue["width"]), float(cue["height"])
                    _check_reels_box(x, y, cue_width, cue_height, "visual cue")
                for visual_path, visual_cue in _visual_layers(root, cue, (width, height), temporary):
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
        logo_path = project_file(root, project["logo"]) if project.get("logo") else None
        if logo_path and not logo_path.is_file():
            raise ProjectError(f"logo not found: {logo_path}")
        asset_records = [(path, path.stem.lower()) for path in [narration, *avatar_paths.values()]]
        if music:
            asset_records.append((music_copy, "studio-music"))
        if logo_path:
            asset_records.append((logo_path, "studio-logo"))
        asset_records.extend((source, asset_id) for asset_id, source, _ in visual_records)
        render_assets = {}
        timeline_path = project_path / "timeline.json"
        timeline = read_json(timeline_path)
        owned_asset_ids = {
            clip["assetId"] for track in timeline.get("tracks", [])
            if track.get("id", "").startswith("studio-")
            for clip in track.get("clips", []) if isinstance(clip.get("assetId"), str)
        }
        asset_manifest = json.loads(_engine_cli(engine_command, project_path, ["asset", "list", str(project_path)]))
        registered_assets = {
            asset["id"]: asset for asset in asset_manifest.get("assets", [])
            if isinstance(asset, dict) and isinstance(asset.get("id"), str)
        }
        for path, asset_id in dict.fromkeys(asset_records):
            render_assets[asset_id] = _register_render_asset(
                engine_command, project_path, path, asset_id, registered_assets, owned_asset_ids,
            )

        transcript_path = temporary / "studio-transcript.json"
        type_scale = min(width / 1080, height / 1920)
        is_portrait = height > width
        colors = profile.get("colors", {})
        project_caption = project.get("caption", {})
        if not isinstance(project_caption, dict):
            raise ProjectError("project caption settings must be an object")
        bubble = portrait_regions()["bubble"] if is_portrait else {"x": 0.31, "y": 0.46, "width": 0.65, "height": 0.12}
        text = portrait_caption() if is_portrait else {"fontSize": 48, "wordsPerCaption": 6, "wordsPerLine": 3}
        caption_options = {
            "layoutPreset": "speechBubble",
            "x": bubble["x"], "y": bubble["y"], "width": bubble["width"], "height": bubble["height"],
            "fontSize": max(8, round(text["fontSize"] * type_scale)),
            "wordsPerCaption": text["wordsPerCaption"], "wordsPerLine": text["wordsPerLine"],
            "wordHighlight": True, "wordHighlightColor": colors.get("accent", "#426BEB"), "wordHighlightAnimation": "pop",
            "color": colors.get("ink", "#172236"), "backgroundColor": "#FFFFFF",
            "bubble": {"tailSide": "left", "tailPosition": 0.35, "tailSizePixels": max(8, round(26 * type_scale)), "cornerRadiusPixels": max(8, round(28 * type_scale))},
            **({"paddingPixels": max(0, round(text["paddingPixels"] * type_scale))} if is_portrait else {}),
            **caption_options(profile, project),
        }
        caption_clips = []
        scene_caption_fields = {"x", "y", "width", "height", "fontSize", "fontFamily", "fontWeight", "color", "backgroundColor", "wordHighlight", "wordHighlightColor", "wordHighlightAnimation", "textShadow", "textOutline", "bubble"}
        for scene_index, scene in enumerate(scenes):
            scene_start, scene_end = float(scene["start"]), float(scene["end"])
            scene_words = [item for item in words if scene_start <= float(item["start"]) < scene_end]
            if not scene_words:
                continue
            write_json(transcript_path, {
                "schemaVersion": 1, "durationSeconds": duration, "granularity": "word",
                "words": [{"text": item["text"].strip(), "start": float(item["start"]), "end": min(duration, float(item["end"]))} for item in scene_words],
            })
            caption_track_path = temporary / f"studio-captions-{scene_index + 1:02d}.json"
            scene_options_path = temporary / f"studio-caption-options-{scene_index + 1:02d}.json"
            scene_caption = scene.get("caption", {})
            if not isinstance(scene_caption, dict):
                raise ProjectError("scene caption settings must be an object")
            scene_options = {key: value for key, value in scene_caption.items() if key in scene_caption_fields}
            if "fontFamily" in scene_options:
                scene_options["fontFamily"] = font_stack(scene_options["fontFamily"])
            options = {**caption_options, **scene_options}
            if isinstance(caption_options.get("bubble"), dict) and isinstance(scene_caption.get("bubble"), dict):
                options["bubble"] = {**caption_options["bubble"], **scene_caption["bubble"]}
            write_json(scene_options_path, options)
            _engine_cli(engine_command, project_path, ["timeline", "captions", str(transcript_path), str(caption_track_path), str(scene_options_path)])
            for clip in read_json(caption_track_path).get("clips", []):
                clip["id"] = f"scene-{scene_index + 1:02d}-{clip['id']}"
                if portrait:
                    _check_reels_box(float(clip["x"]), float(clip["y"]), float(clip["width"]), float(clip["height"]), "caption")
                caption_clips.append(clip)
        captions = {"id": "captions", "kind": "overlay", "order": 5, "clips": caption_clips}
        custom_clips = custom_scene_clips(scenes)
        brand_clip = {
            "id": "studio-brand", "timelineStart": 0, "durationSeconds": duration,
            "text": project.get("brand", "Explainer Studio"),
            "x": 0.1 if is_portrait else 0.025, "y": 0.135 if is_portrait else 0.03,
            "width": 0.28 if is_portrait else 0.24, "height": 0.04,
            "fontSize": max(8, round(24 * type_scale)), "fontWeight": 700,
            "color": colors.get("ink", "#172236"), "backgroundColor": "transparent",
        }
        if portrait:
            _check_reels_box(brand_clip["x"], brand_clip["y"], brand_clip["width"], brand_clip["height"], "brand label")
        brand_track = (
            {"id": "studio-brand", "kind": "video", "order": 2, "clips": [{
                "id": "studio-brand-image", "assetId": "studio-logo", "sourceIn": 0,
                "sourceOut": duration, "timelineStart": 0, "durationSeconds": duration,
                "x": brand_clip["x"], "y": brand_clip["y"], "width": brand_clip["width"], "height": brand_clip["height"], "fit": "contain",
            }]} if logo_path else {"id": "studio-brand", "kind": "overlay", "order": 2, "clips": [brand_clip]}
        )
        title_track = {
            "id": "studio-scene-headings", "kind": "overlay", "order": 3,
            "clips": [{
                "id": f"scene-heading-{index + 1:02d}", "timelineStart": float(scene["start"]),
                "durationSeconds": float(scene["end"]) - float(scene["start"]),
                "text": scene.get("visual_label") or scene["headline"],
                "x": 0.1 if is_portrait else 0.08, "y": 0.16, "width": 0.72 if is_portrait else 0.82, "height": 0.08,
                "fontSize": max(8, round(54 * type_scale)), "fontFamily": font_stack(profile.get("hook_font_family") or DEFAULT_HOOK_FONT),
                "fontWeight": 800, "color": colors.get("ink", "#172236"),
                "backgroundColor": "transparent", "textAlign": "center", "verticalAlign": "center",
                "keyframes": [
                    {"time": 0, "properties": {"y": 0.18, "opacity": 0}},
                    {"time": min(0.45, (float(scene["end"]) - float(scene["start"])) / 3), "properties": {"y": 0.16, "opacity": 1}, "ease": "power2.out"},
                ],
            } for index, scene in enumerate(scenes)],
        }
        if portrait:
            for heading in title_track["clips"]:
                _check_reels_box(heading["x"], heading["y"], heading["width"], heading["height"], "scene heading")
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
            if portrait:
                _check_reels_box(start_props["x"], start_props["y"], start_props["width"], start_props["height"], "visual entrance")
                _check_reels_box(end_props["x"], end_props["y"], end_props["width"], end_props["height"], "visual frame")
                _check_reels_box(x - 0.015, y, width, height, "visual exit")
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
        timeline["project"]["backgroundColor"] = colors.get("background", "#F6F8FC")
        timeline["tracks"] = [
            {"id": "studio-visuals", "kind": "video", "order": 1, "allowOverlap": True, "clips": visual_clips},
            brand_track,
            title_track,
            {"id": "studio-avatar", "kind": "video", "order": 4, "clips": [
                {"id": f"avatar-{index + 1}", "assetId": f"avatar-{item['pose']}-{item['mouth']}-{'blink' if item['blink'] else 'open'}", "sourceIn": 0, "sourceOut": item["end"] - item["start"], "timelineStart": item["start"], "durationSeconds": item["end"] - item["start"], "x": 0, "y": 0, "width": 1, "height": 1, "fit": "fill"}
                for index, item in enumerate(intervals)
            ]},
            captions,
            {"id": "studio-voice", "kind": "audio", "order": 6, "clips": [
                {"id": "narration", "assetId": "studio-narration", "sourceIn": 0, "sourceOut": duration, "timelineStart": 0, "durationSeconds": duration},
            ]},
        ]
        if custom_clips:
            timeline["tracks"].insert(0, {"id": "studio-custom-scenes", "kind": "overlay", "order": 1, "clips": custom_clips})
        if music:
            music_duration = probe_duration(music_copy)
            music_clip_duration = min(duration, music_duration)
            timeline["tracks"].append({"id": "studio-music", "kind": "audio", "order": 7, "clips": [
                {"id": "music-bed", "assetId": "studio-music", "sourceIn": 0, "sourceOut": music_clip_duration, "timelineStart": 0, "durationSeconds": music_clip_duration, "volume": 0.1},
            ]})
            timeline["audioMix"] = {"sidechain": [{"sourceTrackId": "studio-voice", "targetTrackId": "studio-music", "thresholdDb": -34, "ratio": 5, "attackSeconds": 0.02, "releaseSeconds": 0.4}]}
        if preview:
            timeline["tracks"].append(draft_mark_track(duration, portrait=is_portrait, type_scale=type_scale))
        timeline["audioMastering"] = {"integratedLoudnessLUFS": -16, "truePeakDBTP": -1.5, "loudnessRangeLU": 11}
        timeline["project"]["durationSeconds"] = duration
        for track in timeline.get("tracks", []):
            for clip in track.get("clips", []):
                if clip.get("assetId") in render_assets:
                    clip["assetId"] = render_assets[clip["assetId"]]["id"]
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
