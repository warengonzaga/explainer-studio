"""Export a Studio avatar performance for use in a native AIVEE scene."""

from __future__ import annotations

import hashlib
import math
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from .avatar import avatar_box, draw_avatar
from .common import ProjectError, file_hash, probe_duration, project_file, read_json, studio_data, write_json
from .engine import _check_reels_box, avatar_intervals, avatar_keyframes, ensure_render_allowed, list_project_assets, register_asset
from .timing import validate_storyboard, validate_words


def _sprite_scale(scale: float) -> float:
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not 0.25 <= scale <= 4:
        raise ProjectError("avatar export scale must be a number from 0.25 to 4")
    return float(scale)


def export_avatar(source: Path, target: Path, profile: dict, *, scale: float = 1.0) -> dict:
    """Write Studio avatar sprites and timing into a separate AIVEE project."""
    source = source.expanduser().resolve()
    target = target.expanduser()
    if target.is_symlink():
        raise ProjectError(f"AIVEE project must not be a symlink: {target}")
    target = target.resolve()
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ProjectError("Studio and native AIVEE projects must be separate directories")
    if not source.is_dir():
        raise ProjectError(f"Studio project not found: {source}")
    if not target.is_dir():
        raise ProjectError(f"AIVEE project not found: {target}")
    if any((target / name).is_symlink() for name in ("meta.json", "timeline.json")):
        raise ProjectError("AIVEE project metadata must not be symlinks")
    if not (target / "meta.json").is_file() or not (target / "timeline.json").is_file():
        raise ProjectError(f"not an AIVEE project: {target}")

    data = studio_data(source)
    project = read_json(data / "project.json")
    board = read_json(data / "storyboard.json")
    voice_value = Path(project["voice"]).expanduser()
    voice_input = voice_value if voice_value.is_absolute() else source / voice_value
    if voice_input.is_symlink():
        raise ProjectError("narration file must not be a symlink")
    voice = project_file(source, project["voice"])
    if not voice.is_file():
        raise ProjectError(f"narration file not found or is a symlink: {voice}")
    duration = probe_duration(voice)
    validate_storyboard(source, board, duration)
    ensure_render_allowed(board, preview=False)
    words_path = data / "words.json"
    if words_path.is_symlink() or not words_path.resolve().is_relative_to(data.resolve()):
        raise ProjectError("word timings must be a regular file inside Studio data")
    words = read_json(words_path)
    validate_words(words, duration)

    try:
        width, height, fps = (int(project.get(key, fallback)) for key, fallback in (("width", 1920), ("height", 1080), ("fps", 60)))
    except (TypeError, ValueError) as exc:
        raise ProjectError("Studio project has invalid canvas settings") from exc
    if width < 320 or height < 240 or not 1 <= fps <= 60:
        raise ProjectError("Studio project has invalid canvas settings")
    scale = _sprite_scale(scale)

    # Studio owns files in this namespace; AIVEE owns the rest of its project.
    studio_root = target / "studio-data"
    namespace = studio_root / "explainer"
    for path in (studio_root, namespace):
        if path.is_symlink():
            raise ProjectError(f"AIVEE Studio data directory must not be a symlink: {path}")
    resolved_namespace = namespace.resolve()
    if not resolved_namespace.is_relative_to(target):
        raise ProjectError("AIVEE Studio data directory leaves the project")
    export_parent = namespace / "avatar-exports"
    if export_parent.is_symlink():
        raise ProjectError(f"avatar export directory must not be a symlink: {export_parent}")
    export_parent.mkdir(parents=True, exist_ok=True)

    project_slug = re.sub(r"[^a-z0-9]+", "-", source.name.lower()).strip("-")[:40] or "studio-project"
    source_hash = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
    slug = f"{project_slug}-{source_hash}"
    output = export_parent / slug
    if output.exists() or output.is_symlink():
        raise ProjectError(f"avatar export already exists: {output}")

    width, height = (1080, 1920) if height > width else (width, height)
    portrait = height > width
    box = avatar_box((width, height))
    if portrait:
        x, y, avatar_width, avatar_height = box
        _check_reels_box(x / width, y / height, avatar_width / width, avatar_height / height, "avatar")

    output.mkdir()
    sprites_dir = output / "sprites"
    try:
        sprites_dir.mkdir()
        voice_copy = output / f"narration{voice.suffix.lower()}"
        shutil.copy2(voice, voice_copy)
        shutil.copy2(words_path, output / "words.json")

        scratch = data / ".work"
        if scratch.is_symlink():
            raise ProjectError("Studio work directory must not be a symlink")
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="avatar-export-", dir=scratch) as temporary:
            keys = avatar_keyframes(source, project, board, profile, duration, fps, Path(temporary))
        intervals = avatar_intervals(keys, fps, duration)

        sprite_width = max(1, round(box[2] * scale))
        sprite_height = max(1, round(box[3] * scale))
        sprite_records = {}
        for index, (pose, mouth, blink) in enumerate(sorted(set(keys)), start=1):
            image_name = f"avatar-{index:03d}.png"
            image_path = sprites_dir / image_name
            image = Image.new("RGBA", (sprite_width, sprite_height), (0, 0, 0, 0))
            draw_avatar(
                image, source, project, pose, mouth, 0.05 if blink else 1.0,
                (0, 0, sprite_width, sprite_height), fit_scale=scale,
            )
            image.save(image_path)
            sprite_records[(pose, mouth, blink)] = {"file": f"sprites/{image_name}", "asset_id": None, "asset_path": None}

        registered = list_project_assets(target).get("assets", [])
        if not isinstance(registered, list):
            raise ProjectError("AIVEE returned an invalid asset list")
        registered_by_id = {item["id"]: item for item in registered if isinstance(item, dict) and isinstance(item.get("id"), str)}

        def register_or_reuse(path: Path, asset_id: str) -> str:
            digest = file_hash(path)
            existing = registered_by_id.get(asset_id)
            if existing:
                if existing.get("sha256") != digest:
                    raise ProjectError(f"AIVEE asset ID conflicts with existing project media: {asset_id}")
                asset_path = existing.get("path")
                if not isinstance(asset_path, str) or not asset_path:
                    raise ProjectError(f"AIVEE returned an invalid asset path for {asset_id}")
                return asset_path
            asset = register_asset(target, path, asset_id)
            if asset.get("id") != asset_id or asset.get("sha256") != digest:
                raise ProjectError(f"AIVEE returned invalid registration metadata for {asset_id}")
            if not isinstance(asset.get("path"), str) or not asset["path"]:
                raise ProjectError(f"AIVEE returned an invalid asset path for {asset_id}")
            registered_by_id[asset_id] = asset
            return asset["path"]

        voice_asset_id = f"studio-narration-{slug}-{file_hash(voice_copy)[:10]}"
        voice_asset_path = register_or_reuse(voice_copy, voice_asset_id)
        for key, record in sprite_records.items():
            sprite_path = output / record["file"]
            asset_id = f"studio-avatar-{slug}-{file_hash(sprite_path)[:10]}"
            record["asset_id"] = asset_id
            record["asset_path"] = register_or_reuse(sprite_path, asset_id)

        for interval in intervals:
            key = (interval["pose"], interval["mouth"], interval["blink"])
            interval.update(sprite_records[key])

        timing = {
            "schema_version": 1,
            "duration_seconds": duration,
            "canvas": {"width": width, "height": height, "fps": fps},
            "sprite_scale": scale,
            "sprite_size": {"width": sprite_width, "height": sprite_height},
            "avatar_placement": {"x": box[0] / width, "y": box[1] / height, "width": box[2] / width, "height": box[3] / height},
            "narration": {"file": voice_copy.name, "asset_id": voice_asset_id, "asset_path": voice_asset_path},
            "words_file": "words.json",
            "sprites": list(sprite_records.values()),
            "intervals": intervals,
        }
        write_json(output / "timing.json", timing)
        (output / "README.md").write_text(
            "# Explainer Studio avatar export\n\n"
            "This folder contains transparent avatar state sprites, their timed pose/mouth/blink intervals, "
            "the source word timings, and a copy of the narration. The narration and PNG states are also registered "
            "with AIVEE; use each interval's `asset_path` in a native scene and switch states at `start`/`end`.\n\n"
            "`timing.json` is the source of truth. Times are seconds from the beginning of the narration. "
            "Place each sprite using `avatar_placement` to match the Studio composition. "
            "`sprite_scale` multiplies the PNG pixel size without moving that placement.\n",
            encoding="utf-8",
        )
    except Exception:
        # The content-addressed AIVEE IDs let a retry reuse any media registered before a failure.
        shutil.rmtree(output, ignore_errors=True)
        raise

    return {
        "output": str(output),
        "timing": str(output / "timing.json"),
        "sprites": len(sprite_records),
        "intervals": len(intervals),
        "scale": scale,
        "sprite_size": {"width": sprite_width, "height": sprite_height},
        "voice_asset": voice_asset_path,
        "words": str(output / "words.json"),
    }
