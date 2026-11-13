"""Bundled and user-owned presenter sprite packs."""

from __future__ import annotations

import shutil
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

from .common import ProjectError, project_file, read_json


POSES = {"idle", "present", "point", "celebrate"}
MOUTHS = {"rest", "closed", "small", "open", "wide"}
FORMAT_V1 = {
    "poses": {
        "talking": {"idle", "present", "like", "thinking", "idea", "celebrate"},
        "pointing": {"top_left", "left", "bottom_left", "top_right", "right", "bottom_right", "viewer"},
        "emotion": {"smile", "grin", "laugh", "sad", "worried", "surprised", "angry"},
    },
    "eyes": {
        "talking": {"open", "closed", "top_left", "left", "bottom_left", "top_right", "right", "bottom_right"},
        "emotion": {"smile", "grin", "laugh", "sad", "worried", "surprised", "angry"},
    },
    "mouth": {
        "talking": {"rest", "closed", "small", "open", "wide"},
        "emotion": {"smile", "grin", "laugh", "sad", "worried", "surprised", "angry"},
    },
}


def avatar_box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    if h > w:
        scale = min(w / 1080, h / 1920)
        return round(32 * scale), round(1120 * scale), round(475 * scale), round(500 * scale)
    return round(w * .025), round(h * .29), round(w * .31), round(h * .58)


def _is_blinking(t: float) -> bool:
    return t % 4.7 < .11


def _hex(value: str, fallback: str) -> str:
    return value if isinstance(value, str) and len(value) == 7 and value.startswith("#") else fallback


def _mouth(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, state: str, ink: str) -> None:
    w = size
    if state in {"rest", "closed"}:
        draw.arc((x - w / 2, y - w / 5, x + w / 2, y + w / 4), 5, 175, fill=ink, width=max(2, round(w * 0.08)))
    elif state == "small":
        draw.ellipse((x - w * .25, y - w * .2, x + w * .25, y + w * .2), fill=ink)
    elif state == "open":
        draw.ellipse((x - w * .32, y - w * .3, x + w * .32, y + w * .45), fill=ink)
    else:
        draw.rounded_rectangle((x - w * .48, y - w * .22, x + w * .48, y + w * .3), radius=w * .15, fill=ink)


def _bundled_default_pack() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "avatars" / "emo"


def _validate_v1(pack: Path, manifest: dict, *, draft: bool = False) -> dict:
    if not isinstance(manifest, dict) or type(manifest.get("format_version")) is not int or manifest["format_version"] != 1:
        raise ProjectError("unsupported avatar pack format_version; expected 1")
    for field in ("id", "name", "version", "creator", "license"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ProjectError(f"avatar manifest needs a nonempty {field}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", manifest["id"]):
        raise ProjectError("avatar manifest id must use lowercase letters, digits, and hyphens")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", manifest["version"]):
        raise ProjectError("avatar manifest version must use semantic version numbers")
    license_file = manifest.get("license_file")
    if license_file not in {"LICENSE", "TERMS.md"} or not (pack / license_file).is_file() or (pack / license_file).is_symlink():
        raise ProjectError("avatar pack needs its declared LICENSE or TERMS.md file")
    for filename in (("README.md",) if draft else ("README.md", "preview.png")):
        if not (pack / filename).is_file() or (pack / filename).is_symlink():
            raise ProjectError(f"avatar pack is missing {filename}")
    sheets = manifest.get("sheets")
    if not isinstance(sheets, dict):
        raise ProjectError("avatar manifest needs sheets")
    references: list[tuple[str, dict[str, list[int]]]] = []
    for group, categories in FORMAT_V1.items():
        if not isinstance(sheets.get(group), dict):
            raise ProjectError(f"avatar manifest needs sheets.{group}")
        for category, required in categories.items():
            entry = sheets[group].get(category)
            if not isinstance(entry, dict) or not isinstance(entry.get("frames"), dict):
                raise ProjectError(f"avatar manifest needs sheets.{group}.{category}.frames")
            frames = entry["frames"]
            missing = required - frames.keys()
            extra = frames.keys() - required
            if missing or extra:
                detail = f"missing {', '.join(sorted(missing))}" if missing else f"unsupported {', '.join(sorted(extra))}"
                raise ProjectError(f"invalid frames in sheets.{group}.{category}: {detail}")
            relative = entry.get("path")
            if not isinstance(relative, str) or Path(relative).is_absolute():
                raise ProjectError(f"invalid sheet path: sheets.{group}.{category}.path")
            path = pack / relative
            if not path.resolve().is_relative_to(pack.resolve()) or path.is_symlink() or not path.is_file():
                raise ProjectError(f"unsafe or missing sheet: {relative}")
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    width, height = image.size
                    if image.format != "PNG" or image.mode not in {"RGBA", "LA"}:
                        raise ProjectError(f"avatar sheet must be a transparent PNG: {relative}")
                    for name, rect in frames.items():
                        if (not isinstance(rect, list) or len(rect) != 4 or
                                any(type(value) is not int for value in rect) or
                                rect[0] < 0 or rect[1] < 0 or rect[2] <= 0 or rect[3] <= 0 or
                                rect[0] + rect[2] > width or rect[1] + rect[3] > height):
                            raise ProjectError(f"invalid frame bounds: sheets.{group}.{category}.{name}")
                    references.append((relative, frames))
            except OSError as exc:
                raise ProjectError(f"invalid avatar PNG: {relative}") from exc
    face = manifest.get("face")
    if not isinstance(face, dict):
        raise ProjectError("avatar manifest needs face placement")
    for part in ("eyes", "mouth"):
        rect = face.get(part)
        if (not isinstance(rect, list) or len(rect) != 4 or
                any(type(value) is not int for value in rect) or
                rect[0] < 0 or rect[1] < 0 or rect[2] <= 0 or rect[3] <= 0):
            raise ProjectError(f"avatar manifest needs face.{part} as [x, y, width, height]")
    if not (pack / "manifest.json").is_file():
        raise ProjectError("avatar pack is missing manifest.json")
    return manifest


def validate_pack(root: Path, pack_relative: str, *, allow_bundled_legacy: bool = False, draft: bool = False) -> dict:
    pack = project_file(root, pack_relative)
    if not pack.is_dir():
        raise ProjectError(f"avatar pack not found: {pack}")
    if (pack / "manifest.json").is_symlink():
        raise ProjectError("avatar manifest must not be a symlink")
    manifest = read_json(pack / "manifest.json")
    if isinstance(manifest, dict) and manifest.get("format_version") is not None:
        return _validate_v1(pack, manifest, draft=draft)
    if not allow_bundled_legacy or pack.resolve() != _bundled_default_pack().resolve():
        raise ProjectError("legacy avatar pack is unsupported; expected manifest format_version 1")
    return _validate_legacy_pack(pack, manifest)


def _validate_legacy_pack(pack: Path, manifest: dict) -> dict:
    poses = manifest.get("poses")
    if not isinstance(poses, dict) or "idle" not in poses:
        raise ProjectError("avatar manifest needs poses.idle")
    for name, relative in poses.items():
        path = pack / relative if isinstance(relative, str) else pack
        if (name not in POSES or not path.resolve().is_relative_to(pack.resolve())
                or not path.is_file() or path.is_symlink() or path.suffix.lower() != ".png"):
            raise ProjectError(f"invalid avatar pose: {name}")
    anchor = manifest.get("mouth_anchor")
    if not isinstance(anchor, list) or len(anchor) != 2 or not all(isinstance(n, (int, float)) and 0 <= n <= 1 for n in anchor):
        raise ProjectError("avatar manifest needs mouth_anchor [x, y] in 0..1")
    references = list(poses.values()) + list(manifest.get("mouths", {}).values()) + list(manifest.get("blinks", {}).values())
    for relative in references:
        path = pack / relative
        if not path.resolve().is_relative_to(pack.resolve()) or not path.is_file() or path.is_symlink():
            raise ProjectError(f"invalid avatar asset: {relative}")
        try:
            with Image.open(path) as image:
                image.verify()
        except OSError as exc:
            raise ProjectError(f"invalid avatar PNG: {relative}") from exc
    return manifest
    poses = manifest.get("poses")
    if not isinstance(poses, dict) or "idle" not in poses:
        raise ProjectError("avatar manifest needs poses.idle")
    for name, relative in poses.items():
        if not isinstance(relative, str) or name not in POSES or not (pack / relative).resolve().is_relative_to(pack.resolve()) or not (pack / relative).is_file() or (pack / relative).is_symlink() or Path(relative).suffix.lower() != ".png":
            raise ProjectError(f"invalid avatar pose: {name}")
    anchor = manifest.get("mouth_anchor")
    if not isinstance(anchor, list) or len(anchor) != 2 or not all(isinstance(n, (int, float)) and 0 <= n <= 1 for n in anchor):
        raise ProjectError("avatar manifest needs mouth_anchor [x, y] in 0..1")
    mouths = manifest.get("mouths", {})
    if not isinstance(mouths, dict):
        raise ProjectError("avatar mouths must be a map")
    blinks = manifest.get("blinks", {})
    if not isinstance(blinks, dict):
        raise ProjectError("avatar blinks must be a map")
    references = set(poses.values())
    for name, relative in blinks.items():
        if (name not in poses or not isinstance(relative, str)
                or not (pack / relative).resolve().is_relative_to(pack.resolve())
                or not (pack / relative).is_file() or (pack / relative).is_symlink()
                or Path(relative).suffix.lower() != ".png"):
            raise ProjectError(f"invalid avatar blink: {name}")
        references.add(relative)
    fit = manifest.get("mouth_fit", {})
    if not isinstance(fit, dict) or any(name not in poses for name in fit):
        raise ProjectError("avatar mouth_fit must map supported poses to fit settings")

    def validate_mouths(values: object, context: str) -> None:
        if not isinstance(values, dict):
            raise ProjectError(f"{context} must be a map")
        for name, relative in values.items():
            if (not isinstance(relative, str) or name not in MOUTHS
                    or not (pack / relative).resolve().is_relative_to(pack.resolve())
                    or not (pack / relative).is_file() or (pack / relative).is_symlink()
                    or Path(relative).suffix.lower() != ".png"):
                raise ProjectError(f"invalid avatar mouth: {context}.{name}")
            references.add(relative)

    validate_mouths(mouths, "avatar mouths")
    for pose, settings in fit.items():
        if not isinstance(settings, dict):
            raise ProjectError(f"avatar mouth_fit.{pose} must be a map")
        pose_anchor = settings.get("anchor")
        if pose_anchor is not None and (
            not isinstance(pose_anchor, list) or len(pose_anchor) != 2
            or not all(isinstance(n, (int, float)) and 0 <= n <= 1 for n in pose_anchor)
        ):
            raise ProjectError(f"avatar mouth_fit.{pose}.anchor must be [x, y] in 0..1")
        pose_width = settings.get("width")
        if pose_width is not None and (not isinstance(pose_width, (int, float)) or not .02 <= pose_width <= .5):
            raise ProjectError(f"avatar mouth_fit.{pose}.width must be between 0.02 and 0.5")
        scale = settings.get("scale")
        if scale is not None and (not isinstance(scale, (int, float)) or not .5 <= scale <= 1.5):
            raise ProjectError(f"avatar mouth_fit.{pose}.scale must be between 0.5 and 1.5")
        if "mouths" in settings:
            validate_mouths(settings["mouths"], f"avatar mouth_fit.{pose}.mouths")
    width = manifest.get("mouth_width", .13)
    if not isinstance(width, (int, float)) or not .02 <= width <= .5:
        raise ProjectError("avatar mouth_width must be between 0.02 and 0.5")
    for relative in references:
        try:
            with Image.open(pack / relative) as image:
                image.verify()
        except OSError as exc:
            raise ProjectError(f"invalid avatar PNG: {relative}") from exc
    return manifest


def copy_pack(source: Path, target: Path) -> None:
    source = source.resolve()
    manifest = validate_pack(source.parent, source.name, allow_bundled_legacy=source == _bundled_default_pack().resolve())
    if target.exists():
        raise ProjectError(f"avatar pack already exists: {target}")
    target.mkdir(parents=True)
    if manifest.get("format_version") == 1:
        shutil.copy2(source / "manifest.json", target / "manifest.json")
        references = {
            source / "README.md", source / manifest["license_file"],
            *(source / entry["path"] for groups in manifest["sheets"].values() for entry in groups.values()),
        }
        for item in references:
            destination = target / item.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
        preview = source / "preview.png"
        if preview.is_file():
            shutil.copy2(preview, target / "preview.png")
        return
    shutil.copy2(source / "manifest.json", target / "manifest.json")
    references = set(manifest["poses"].values()) | set(manifest.get("mouths", {}).values()) | set(manifest.get("blinks", {}).values())
    for settings in manifest.get("mouth_fit", {}).values():
        references.update(settings.get("mouths", {}).values())
    for relative in references:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)


def draw_avatar(canvas: Image.Image, root: Path, project: dict, pose: str, mouth: str, t: float, box: tuple[int, int, int, int]) -> None:
    pack_relative = project.get("avatar_pack")
    if pack_relative:
        manifest = validate_pack(root, pack_relative, draft=bool(project.get("avatar_preview_draft")))
        pack = project_file(root, pack_relative)
    else:
        pack = _bundled_default_pack()
        manifest = validate_pack(pack.parent, pack.name, allow_bundled_legacy=True)
    if manifest.get("format_version") == 1:
        _draw_v1_avatar(canvas, pack, manifest, pose, mouth, t, box)
        return
    _draw_legacy_avatar(canvas, pack, manifest, pose, mouth, t, box)


def _draw_legacy_avatar(canvas: Image.Image, pack: Path, manifest: dict, pose: str, mouth: str, t: float, box: tuple[int, int, int, int]) -> None:
    if pose in {"point_right", "point_viewer"}:
        pose = "point"
    if pose not in POSES:
        raise ProjectError(f"unsupported pose: {pose}")
    if mouth not in MOUTHS:
        mouth = "rest"
    blink_file = manifest.get("blinks", {}).get(pose)
    if blink_file and _is_blinking(t):
        pose_path = pack / blink_file
    else:
        pose_path = pack / manifest["poses"].get(pose, manifest["poses"]["idle"])
    x, y, w, h = box
    with Image.open(pose_path) as source:
        sprite = source.convert("RGBA")
        sprite.thumbnail((w, h), Image.Resampling.LANCZOS)
    sx = x + (w - sprite.width) // 2
    sy = y + h - sprite.height
    canvas.paste(sprite, (sx, sy), sprite)
    fit = manifest.get("mouth_fit", {}).get(pose, {})
    ax, ay = fit.get("anchor", manifest["mouth_anchor"])
    mx, my = sx + sprite.width * ax, sy + sprite.height * ay
    mouth_file = fit.get("mouths", {}).get(mouth, manifest.get("mouths", {}).get(mouth))
    if mouth_file:
        with Image.open(pack / mouth_file) as source:
            patch = source.convert("RGBA")
            target_w = max(2, round(sprite.width * float(fit.get("width", manifest.get("mouth_width", .13))) * float(fit.get("scale", 1))))
            patch.thumbnail((target_w, target_w * 2), Image.Resampling.LANCZOS)
        canvas.paste(patch, (round(mx - patch.width / 2), round(my - patch.height / 2)), patch)
    else:
        _mouth(ImageDraw.Draw(canvas), mx, my, sprite.width * float(fit.get("width", manifest.get("mouth_width", .13))) * float(fit.get("scale", 1)), mouth, _hex(project.get("colors", {}).get("ink"), "#12223B"))


def _draw_v1_avatar(canvas: Image.Image, pack: Path, manifest: dict, pose: str, mouth: str, t: float, box: tuple[int, int, int, int]) -> None:
    if pose.startswith("point_"):
        category, frame = "pointing", pose.removeprefix("point_")
        gaze = "open" if frame == "viewer" else frame
        expression = None
    elif pose.startswith("emotion_"):
        category, frame = "emotion", pose.removeprefix("emotion_")
        gaze, expression = frame, frame
    else:
        category, frame, gaze, expression = "talking", pose, "open", None
    sheet_set = manifest["sheets"]
    entries = [
        (sheet_set["poses"][category], frame, None),
        (sheet_set["eyes"]["emotion" if expression else "talking"], expression or ("closed" if _is_blinking(t) else gaze), manifest["face"]["eyes"]),
    ]
    mouth_category = "emotion" if expression and mouth == "rest" else "talking"
    mouth_frame = expression if mouth_category == "emotion" else (mouth if mouth in FORMAT_V1["mouth"]["talking"] else "rest")
    entries.append((sheet_set["mouth"][mouth_category], mouth_frame, manifest["face"]["mouth"]))
    pose_sheet, pose_rect = entries[0][0], entries[0][0]["frames"][frame]
    x, y, w, h = box
    base = _crop_sheet(pack, pose_sheet, pose_rect)
    base.thumbnail((w, h), Image.Resampling.LANCZOS)
    sx, sy = x + (w - base.width) // 2, y + h - base.height
    canvas.paste(base, (sx, sy), base)
    pose_width, pose_height = pose_rect[2], pose_rect[3]
    for entry, _, destination_rect in entries[1:]:
        rect = entry["frames"][_]
        layer = _crop_sheet(pack, entry, rect)
        dx, dy, dw, dh = destination_rect
        layer = layer.resize((max(1, round(base.width * dw / pose_width)), max(1, round(base.height * dh / pose_height))), Image.Resampling.LANCZOS)
        px = sx + round(base.width * dx / pose_width)
        py = sy + round(base.height * dy / pose_height)
        canvas.paste(layer, (px, py), layer)


def _crop_sheet(pack: Path, entry: dict, rect: list[int]) -> Image.Image:
    with Image.open(pack / entry["path"]) as image:
        x, y, width, height = rect
        return image.convert("RGBA").crop((x, y, x + width, y + height))


def pose_supported(manifest: dict, pose: str) -> bool:
    if manifest.get("format_version") != 1:
        return pose in POSES | {"point_right", "point_viewer"}
    if pose.startswith("point_"):
        group, name = "pointing", pose.removeprefix("point_")
    elif pose.startswith("emotion_"):
        group, name = "emotion", pose.removeprefix("emotion_")
    else:
        group, name = "talking", pose
    return name in manifest["sheets"]["poses"][group]["frames"]


def preview_avatar(root: Path, output: Path) -> Path:
    project = read_json(root / "project.json")
    return _preview_sheet(root, project, output)


def preview_pack(pack: Path, output: Path) -> Path:
    pack = pack.resolve()
    validate_pack(pack.parent, pack.name, draft=True)
    return _preview_sheet(pack.parent, {"avatar_pack": pack.name, "avatar_preview_draft": True, "colors": {}}, output)


def _preview_sheet(root: Path, project: dict, output: Path) -> Path:
    if output.exists():
        raise ProjectError(f"preview already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = validate_pack(root, project["avatar_pack"], draft=bool(project.get("avatar_preview_draft"))) if project.get("avatar_pack") else {}
    if manifest.get("format_version") == 1:
        rows = [(name, state, 1.0) for name in sorted(FORMAT_V1["poses"]["talking"]) for state in sorted(FORMAT_V1["mouth"]["talking"])]
        rows += [(f"point_{name}", "rest", 1.0) for name in sorted(FORMAT_V1["poses"]["pointing"])]
        rows += [(f"emotion_{name}", "rest", 1.0) for name in sorted(FORMAT_V1["poses"]["emotion"])]
        rows.append(("idle", "rest", .05))
        cell_w, cell_h, columns = 260, 340, 5
        sheet = Image.new("RGB", (cell_w * columns, cell_h * math.ceil(len(rows) / columns)), "#F6F8FC")
        draw = ImageDraw.Draw(sheet)
        for index, (pose, mouth, time) in enumerate(rows):
            x, y = index % columns * cell_w, index // columns * cell_h
            draw.rounded_rectangle((x + 8, y + 8, x + cell_w - 8, y + cell_h - 8), radius=16, fill="white")
            draw_avatar(sheet, root, project, pose, mouth, time, (x + 32, y + 18, cell_w - 64, cell_h - 68))
            draw.text((x + 18, y + cell_h - 36), f"{pose} / {mouth}", fill="#172236")
        sheet.save(output)
        return output
    poses = ["idle", "present", "point", "celebrate"]
    mouths = ["rest", "closed", "small", "open", "wide"]
    blink_column = any(manifest.get("blinks", {}).get(pose) for pose in poses)
    columns = ([ ("blink", "rest", .05) ] if blink_column else []) + [(mouth, mouth, 1.0) for mouth in mouths]
    cell_w, cell_h = 260, 340
    sheet = Image.new("RGB", (cell_w * len(columns), cell_h * len(poses)), "#F6F8FC")
    draw = ImageDraw.Draw(sheet)
    for row, pose in enumerate(poses):
        for col, (label, mouth, time) in enumerate(columns):
            x, y = col * cell_w, row * cell_h
            draw.rounded_rectangle((x + 8, y + 8, x + cell_w - 8, y + cell_h - 8), radius=16, fill="white")
            draw_avatar(sheet, root, project, pose, mouth, time, (x + 32, y + 18, cell_w - 64, cell_h - 68))
            draw.text((x + 18, y + cell_h - 36), f"{pose} / {label}", fill="#172236")
    sheet.save(output)
    return output
