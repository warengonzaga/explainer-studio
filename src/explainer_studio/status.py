"""Read-only project stage report for the status command."""

from __future__ import annotations

from pathlib import Path

from .common import ProjectError, file_hash, project_file, read_json, studio_data
from .timing import scene_composition_hash, storyboard_hash

STAGES = ("voice", "words", "storyboard", "approved", "preview", "final")
PREVIEW_RENDERS = ("draft-engine.mp4", "draft-portrait-engine.mp4")
FINAL_RENDERS = ("final-engine.mp4", "final-portrait-engine.mp4")


def project_status(root: Path) -> tuple[dict, list[str]]:
    """Return the status data object and the safe next commands."""
    root = root.resolve()
    if not root.is_dir():
        raise ProjectError(f"project not found: {root}")
    data_dir = studio_data(root)
    project_path = data_dir / "project.json"
    if not project_path.is_file():
        raise ProjectError(f"missing {project_path}")
    project = read_json(project_path)
    if not isinstance(project, dict):
        raise ProjectError(f"invalid project file: {project_path}")

    voice = _voice_path(root, project.get("voice"))
    words = data_dir / "words.json"
    script = data_dir / "script.txt"
    board_path = data_dir / "storyboard.json"
    board = _read_object(board_path)
    preview = _render_paths(root, PREVIEW_RENDERS)
    final = _render_paths(root, FINAL_RENDERS)
    voice_done = voice is not None and voice.is_file()
    words_done = _words_ready(words)
    storyboard_done = _storyboard_current(board, script, voice if voice_done else None, root)
    approved_done = _approval_current(board, script, voice if voice_done else None, words, root)
    stages = {
        "voice": _stage(voice_done, [voice] if voice_done else []),
        "words": _stage(words_done, [words] if words.is_file() else []),
        "storyboard": _stage(storyboard_done, [board_path] if board_path.is_file() else []),
        "approved": _stage(approved_done, [board_path] if board_path.is_file() else []),
        "preview": _stage(bool(preview), preview),
        "final": _stage(bool(final), final),
    }
    steps, gate = _next_steps(root, stages)
    payload = {"project": str(root), "voice_attached": voice_done, "stages": stages}
    if gate:
        payload["review_gate"] = gate
    return payload, steps


def format_status(data: dict, steps: list[str]) -> list[str]:
    """Plain-text lines for a status result."""
    lines = [f"project: {data['project']}"]
    for name in STAGES:
        stage = data["stages"][name]
        label = "done" if stage["done"] else "not done"
        paths = ", ".join(stage["paths"])
        lines.append(f"{name}: {label} ({paths})" if paths else f"{name}: {label}")
    if steps:
        lines.append(f"next: {steps[0]}")
    elif not data["voice_attached"]:
        lines.append("next: attach narration")
    elif data.get("review_gate") == "storyboard":
        lines.append("next: review the storyboard in chat")
    if data.get("review_gate"):
        lines.append(f"review: {data['review_gate']}")
    return lines


def _stage(done: bool, paths: list[Path]) -> dict:
    return {"done": done, "paths": [str(path) for path in paths]}


def _voice_path(root: Path, relative) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    return project_file(root, relative)


def _read_object(path: Path):
    if not path.is_file():
        return None
    try:
        value = read_json(path)
    except ProjectError:
        return None
    return value if isinstance(value, dict) else None


def _words_ready(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        words = read_json(path)
    except ProjectError:
        return False
    if not isinstance(words, list) or not words:
        return False
    return all(isinstance(item, dict) and {"text", "start", "end"} <= set(item) for item in words)


def _same_hash(path: Path | None, expected) -> bool:
    return path is not None and path.is_file() and expected == file_hash(path)


def _storyboard_current(board, script: Path, voice: Path | None, root: Path) -> bool:
    if not isinstance(board, dict) or board.get("version") != 1:
        return False
    scenes = board.get("scenes")
    source = board.get("source")
    if not isinstance(scenes, list) or not scenes or not isinstance(source, dict):
        return False
    if not _same_hash(script, source.get("script_sha256")) or not _same_hash(voice, source.get("voice_sha256")):
        return False
    try:
        return all(
            project_file(root, scene["composition"]).is_file()
            for scene in scenes if scene.get("composition")
        )
    except (KeyError, ProjectError):
        return False


def _approval_current(board, script: Path, voice: Path | None, words: Path, root: Path) -> bool:
    if not _storyboard_current(board, script, voice, root) or not _compositions_current(board, root) or board.get("approved") is not True:
        return False
    if not _same_hash(words, board.get("source", {}).get("words_sha256")):
        return False
    try:
        return board.get("approval_hash") == storyboard_hash(board)
    except (TypeError, KeyError, ValueError):
        return False


def _compositions_current(board, root: Path) -> bool:
    try:
        return all(
            scene_composition_hash(project_file(root, scene["composition"])) == scene.get("composition_sha256")
            for scene in board.get("scenes", []) if scene.get("composition")
        )
    except (KeyError, ProjectError):
        return False


def _render_paths(root: Path, names: tuple[str, ...]) -> list[Path]:
    renders = root / "renders"
    return [renders / name for name in names if (renders / name).is_file()]


def _next_steps(root: Path, stages: dict) -> tuple[list[str], str | None]:
    from .cli import command_step

    project = str(root)
    if not stages["voice"]["done"]:
        return [], None
    if not stages["words"]["done"]:
        return [command_step("transcribe", project)], None
    if not stages["storyboard"]["done"]:
        return [command_step("storyboard", project)], None
    if not stages["approved"]["done"]:
        return [], "storyboard"
    if stages["final"]["paths"]:
        return [command_step("check", project, stages["final"]["paths"][0])], None
    if stages["preview"]["paths"]:
        return [command_step("contact-sheet", project, stages["preview"]["paths"][0])], "preview"
    return [command_step("render", project, "--preview")], None
