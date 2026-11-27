"""Bundled HTML scene starters and the open area they can use."""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

from .avatar import avatar_box
from .common import ProjectError, project_file, read_json, studio_file
from .engine import _check_reels_box, portrait_regions


_KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TOKEN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_LANGUAGE = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")
_GAP = 0.02
_MIN_BAND = 0.14
_THEME_TOKENS = (
    "SCENE_DURATION",
    "PROJECT_WIDTH",
    "PROJECT_HEIGHT",
    "DOCUMENT_LANGUAGE",
    "COLOR_BACKGROUND",
    "COLOR_INK",
    "COLOR_ACCENT",
    "STAGE_X",
    "STAGE_Y",
    "STAGE_W",
    "STAGE_H",
)
_COLOR_DEFAULTS = {"background": "#F6F8FC", "ink": "#172236", "accent": "#426BEB"}


def template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "library" / "templates"


def list_templates() -> list[dict]:
    """Scene starters shipped with Studio, including the original shot-plan template."""
    return [{key: item[key] for key in ("id", "title", "summary", "texts")} for item in _load_templates()]


def caption_region(project: dict, width: int, height: int) -> dict[str, float]:
    """Normalized caption box from the project, or the format default."""
    caption = project.get("caption") or {}
    if not isinstance(caption, dict):
        raise ProjectError("project caption settings must be an object")
    placement = caption.get("placement") or {}
    if not isinstance(placement, dict):
        raise ProjectError("caption placement must be an object")
    box = dict(portrait_regions()["bubble"] if height > width else {"x": 0.31, "y": 0.46, "width": 0.65, "height": 0.12})
    for key in ("x", "y", "width", "height"):
        if key not in placement:
            continue
        value = placement[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ProjectError("caption placement values must be finite numbers from 0 to 1")
        box[key] = float(value)
    if box["width"] <= 0 or box["height"] <= 0 or box["x"] < 0 or box["y"] < 0 or box["x"] + box["width"] > 1 or box["y"] + box["height"] > 1:
        raise ProjectError("caption placement must stay inside the frame")
    return box


def avatar_region(width: int, height: int) -> dict[str, float]:
    x, y, box_width, box_height = avatar_box((width, height))
    return {"x": x / width, "y": y / height, "width": box_width / width, "height": box_height / height}


def scene_stage(width: int, height: int, caption: dict[str, float]) -> dict[str, float]:
    """Normalized graphic box clear of the avatar and captions."""
    avatar = avatar_region(width, height)
    if height > width:
        stage = dict(portrait_regions()["visual"])
        _check_reels_box(stage["x"], stage["y"], stage["width"], stage["height"], "scene stage")
        if _overlaps(stage, avatar) or _overlaps(stage, caption):
            raise ProjectError("scene stage overlaps the avatar or captions; reposition the captions")
        return stage

    left = avatar["x"] + avatar["width"] + _GAP
    band_width = 0.96 - left
    if band_width < 0.2:
        raise ProjectError("scene stage has no room beside the avatar")
    above = _band(left, band_width, 0.26, caption["y"] - _GAP)
    below = _band(left, band_width, caption["y"] + caption["height"] + _GAP, 0.94)
    candidates = [
        stage for stage in (above, below)
        if stage and _inside(stage) and not _overlaps(stage, avatar) and not _overlaps(stage, caption)
    ]
    if not candidates:
        raise ProjectError("scene stage has no room clear of the avatar and captions")
    return max(candidates, key=lambda stage: stage["height"])


def scene_duration(root: Path, scene_number: int) -> float:
    path = studio_file(root, "storyboard.json")
    if not path.is_file():
        raise ProjectError("generate a storyboard before attaching a scene starter")
    board = read_json(path)
    if not isinstance(board, dict) or not isinstance(board.get("scenes"), list):
        raise ProjectError("generate a storyboard before attaching a scene starter")
    if isinstance(scene_number, bool) or not isinstance(scene_number, int) or scene_number < 1 or scene_number > len(board["scenes"]):
        raise ProjectError(f"scene must be between 1 and {len(board['scenes'])}")
    scene = board["scenes"][scene_number - 1]
    if not isinstance(scene, dict):
        raise ProjectError(f"scene {scene_number} must be an object")
    try:
        duration = float(scene["end"]) - float(scene["start"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectError(f"scene {scene_number} needs numeric start and end") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ProjectError("scene duration must be a positive finite number")
    return duration


def parse_text_assignments(items: list[str] | None) -> dict[str, str]:
    texts: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ProjectError("--set must use key=value")
        key, value = item.split("=", 1)
        key = key.strip()
        if not _KEY.fullmatch(key):
            raise ProjectError("--set key must use lowercase letters, digits, and hyphens")
        if key in texts:
            raise ProjectError(f"duplicate --set key: {key}")
        texts[key] = value.strip()
    return texts


def add_scene_starter(root: Path, template_id: str, *, name: str | None, duration: float, texts: dict[str, str] | None = None) -> dict:
    """Copy one starter into the project. Refuse to replace an existing scene file."""
    spec = _require(template_id)
    scene_name = name or template_id
    if not _KEY.fullmatch(scene_name):
        raise ProjectError("scene starter name must use lowercase letters, digits, and hyphens")
    duration_text = _number(duration, "scene duration must be a positive finite number")
    project = _project(root)
    width, height = _canvas(project)
    colors = _colors(project)
    stage = scene_stage(width, height, caption_region(project, width, height))
    values = {
        "COMPOSITION_ID": "root",
        "SCENE_DURATION": duration_text,
        "PROJECT_WIDTH": str(width),
        "PROJECT_HEIGHT": str(height),
        "DOCUMENT_LANGUAGE": _language(project.get("language")),
        "COLOR_BACKGROUND": colors["background"],
        "COLOR_INK": colors["ink"],
        "COLOR_ACCENT": colors["accent"],
        "STAGE_X": _percent(stage["x"]),
        "STAGE_Y": _percent(stage["y"]),
        "STAGE_W": _percent(stage["width"]),
        "STAGE_H": _percent(stage["height"]),
    }
    supplied = texts or {}
    known_keys = [item["key"] for item in spec["texts"]]
    unknown = sorted(set(supplied) - set(known_keys))
    if unknown:
        known = ", ".join(known_keys) or "none"
        raise ProjectError(f"unknown text field for {template_id}: {', '.join(unknown)}; known fields: {known}")
    for key, default in spec["defaults"].items():
        values["TEXT_" + key.upper().replace("-", "_")] = _text(supplied.get(key, default))

    target = _scene_file(root, scene_name)
    rendered = _fill(spec["html"], values)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    relative = target.relative_to(root.resolve()).as_posix()
    return {
        "template": template_id,
        "name": scene_name,
        "path": relative,
        "duration": float(duration_text),
        "width": width,
        "height": height,
    }


def discard_scene_starter(root: Path, relative: str) -> None:
    """Remove a starter file this command just wrote."""
    path = project_file(root, relative)
    parts = path.relative_to(root.resolve()).parts
    if parts[:2] != ("compositions", "scenes") or path.name != "index.html":
        raise ProjectError("refusing to remove a path outside a scene starter")
    if path.is_symlink():
        raise ProjectError("scene starter path must not be a symlink")
    if path.is_file():
        path.unlink()
    parent = path.parent
    if parent.is_dir() and not parent.is_symlink() and not any(parent.iterdir()):
        parent.rmdir()


def _describe(directory: Path, scene: Path) -> dict:
    if directory.is_symlink() or scene.is_symlink():
        raise ProjectError(f"scene starter must not be a symlink: {directory.name}")
    if not _KEY.fullmatch(directory.name):
        raise ProjectError(f"scene starter name must use lowercase letters, digits, and hyphens: {directory.name}")
    meta_path = directory / "template.json"
    html_text = scene.read_text(encoding="utf-8")
    if meta_path.is_file():
        if meta_path.is_symlink():
            raise ProjectError(f"scene starter must not be a symlink: {directory.name}")
        meta = _parameterized_meta(directory.name, read_json(meta_path), html_text)
    else:
        meta = {"title": _heading(directory) or directory.name, "summary": _first_paragraph(directory), "texts": [], "defaults": {}}
    return {"id": directory.name, "title": meta["title"], "summary": meta["summary"], "texts": meta["texts"], "defaults": meta["defaults"], "html": html_text}


def _parameterized_meta(name: str, meta: dict, html_text: str) -> dict:
    if not isinstance(meta, dict):
        raise ProjectError(f"{name} template metadata must be an object")
    title, summary, texts = meta.get("title"), meta.get("summary"), meta.get("texts")
    if not isinstance(title, str) or not title.strip() or not isinstance(summary, str) or not summary.strip():
        raise ProjectError(f"{name} template needs a title and summary")
    if not isinstance(texts, dict) or not texts:
        raise ProjectError(f"{name} template needs text fields")
    defaults = {}
    keys = []
    for key, default in texts.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ProjectError(f"{name} template has an invalid text field")
        if not isinstance(default, str) or not default.strip() or "{{" in default or "}}" in default:
            raise ProjectError(f"{name} template needs a default for {key}")
        defaults[key] = default.strip()
        keys.append({"key": key, "default": defaults[key]})
        token = "TEXT_" + key.upper().replace("-", "_")
        if "{{" + token + "}}" not in html_text:
            raise ProjectError(f"{name} scene is missing {token}")
    for token in _THEME_TOKENS:
        if "{{" + token + "}}" not in html_text:
            raise ProjectError(f"{name} scene is missing {token}")
    if "window.__timelines.root" not in html_text:
        raise ProjectError(f"{name} scene must register window.__timelines.root")
    return {"title": title.strip(), "summary": summary.strip(), "texts": keys, "defaults": defaults}


def _load_templates() -> list[dict]:
    root = template_root()
    if not root.is_dir():
        raise ProjectError(f"scene starters are not available: {root}")
    found = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        scene = directory / "scene.html"
        if not scene.is_file():
            continue
        found.append(_describe(directory, scene))
    if not found:
        raise ProjectError(f"scene starters are not available: {root}")
    return found


def _require(template_id: str) -> dict:
    matches = [item for item in _load_templates() if item["id"] == template_id]
    if not matches:
        known = ", ".join(item["id"] for item in _load_templates())
        raise ProjectError(f"unknown scene starter: {template_id}; known starters: {known}")
    return matches[0]


def _project(root: Path) -> dict:
    project = read_json(studio_file(root, "project.json"))
    if not isinstance(project, dict):
        raise ProjectError("project settings must be an object")
    return project


def _canvas(project: dict) -> tuple[int, int]:
    width, height = project.get("width"), project.get("height")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ProjectError("project width and height must be positive integers")
    return width, height


def _colors(project: dict) -> dict[str, str]:
    raw = project.get("colors") or {}
    if not isinstance(raw, dict):
        raise ProjectError("project colors must be an object")
    colors = {}
    for key, default in _COLOR_DEFAULTS.items():
        value = raw.get(key) or default
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ProjectError(f"project {key} color must be a six-digit hex color")
        colors[key] = value.upper()
    return colors


def _language(value) -> str:
    if not isinstance(value, str) or not _LANGUAGE.fullmatch(value.strip()):
        return ""
    return value.strip()


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectError("scene text must not be empty")
    if len(value) > 160 or "{{" in value or "}}" in value or any(ord(char) < 32 for char in value):
        raise ProjectError("scene text must be one short line without template markers")
    return html.escape(value.strip(), quote=True)


def _fill(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ProjectError(f"scene template placeholder is not supported: {key}")
        return values[key]

    rendered = _TOKEN.sub(replace, template)
    if _TOKEN.search(rendered):
        raise ProjectError("scene template has an unreplaced placeholder")
    return rendered if rendered.endswith("\n") else rendered + "\n"


def _scene_file(root: Path, name: str) -> Path:
    root = root.resolve()
    if not root.is_dir():
        raise ProjectError(f"project not found: {root}")
    directory = root / "compositions" / "scenes" / name
    for candidate in (root / "compositions", root / "compositions" / "scenes", directory):
        if candidate.is_symlink():
            raise ProjectError("scene composition path must not be a symlink")
        if candidate.exists() and not candidate.is_dir():
            raise ProjectError(f"scene composition path is not a directory: {candidate.relative_to(root).as_posix()}")
    target = directory / "index.html"
    if target.is_symlink() or target.exists():
        raise ProjectError(f"scene starter already exists: {target.relative_to(root).as_posix()}")
    return target


def _band(left: float, width: float, top: float, bottom: float) -> dict[str, float] | None:
    height = bottom - top
    if height < _MIN_BAND:
        return None
    return {"x": left, "y": top, "width": width, "height": height}


def _inside(box: dict[str, float]) -> bool:
    return box["x"] >= 0 and box["y"] >= 0 and box["width"] > 0 and box["height"] > 0 and box["x"] + box["width"] <= 1 and box["y"] + box["height"] <= 1


def _overlaps(first: dict[str, float], second: dict[str, float]) -> bool:
    return not (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )


def _number(value: float, message: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ProjectError(message)
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if not text or text == "0":
        raise ProjectError(message)
    return text


def _percent(value: float) -> str:
    return f"{value * 100:.4f}".rstrip("0").rstrip(".")


def _heading(directory: Path) -> str:
    readme = directory / "README.md"
    if not readme.is_file() or readme.is_symlink():
        return ""
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _first_paragraph(directory: Path) -> str:
    readme = directory / "README.md"
    if not readme.is_file() or readme.is_symlink():
        return ""
    lines = []
    for line in readme.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if lines:
                break
            continue
        if not stripped:
            if lines:
                break
            continue
        lines.append(stripped)
    return " ".join(lines)
