"""Bundled and user-owned presenter sprite packs."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from .common import ProjectError, project_file, read_json


POSES = {"idle", "present", "point", "celebrate"}
MOUTHS = {"rest", "closed", "small", "open", "wide"}


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


def validate_pack(root: Path, pack_relative: str) -> dict:
    pack = project_file(root, pack_relative)
    if not pack.is_dir():
        raise ProjectError(f"avatar pack not found: {pack}")
    manifest = read_json(pack / "manifest.json")
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
    manifest = validate_pack(source.parent, source.name)
    if target.exists():
        raise ProjectError(f"avatar pack already exists: {target}")
    target.mkdir(parents=True)
    shutil.copy2(source / "manifest.json", target / "manifest.json")
    references = set(manifest["poses"].values()) | set(manifest.get("mouths", {}).values()) | set(manifest.get("blinks", {}).values())
    for settings in manifest.get("mouth_fit", {}).values():
        references.update(settings.get("mouths", {}).values())
    for relative in references:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)


def draw_avatar(canvas: Image.Image, root: Path, project: dict, pose: str, mouth: str, t: float, box: tuple[int, int, int, int]) -> None:
    if pose not in POSES:
        raise ProjectError(f"unsupported pose: {pose}")
    if mouth not in MOUTHS:
        mouth = "rest"
    pack_relative = project.get("avatar_pack")
    if pack_relative:
        manifest = validate_pack(root, pack_relative)
        pack = project_file(root, pack_relative)
    else:
        pack = _bundled_default_pack()
        manifest = validate_pack(pack.parent, pack.name)
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


def preview_avatar(root: Path, output: Path) -> Path:
    project = read_json(root / "project.json")
    return _preview_sheet(root, project, output)


def preview_pack(pack: Path, output: Path) -> Path:
    pack = pack.resolve()
    validate_pack(pack.parent, pack.name)
    return _preview_sheet(pack.parent, {"avatar_pack": pack.name, "colors": {}}, output)


def _preview_sheet(root: Path, project: dict, output: Path) -> Path:
    if output.exists():
        raise ProjectError(f"preview already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = validate_pack(root, project["avatar_pack"]) if project.get("avatar_pack") else {}
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
