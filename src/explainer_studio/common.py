"""Shared project paths, JSON handling, and media probing."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


class ProjectError(Exception):
    """A recoverable project or input error."""


def studio_home() -> Path:
    return Path(os.environ.get("EXPLAINER_STUDIO_HOME", Path.home() / ".explainer-studio")).expanduser()


def command(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise ProjectError(f"{name} is required and was not found on PATH")
    return found


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        raise ProjectError(f"command failed ({exc.returncode}): {args[0]}") from exc


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_file(root: Path, relative: str) -> Path:
    """Resolve a project-owned input without allowing traversal outside it."""
    if not isinstance(relative, str) or not relative:
        raise ProjectError("asset path must be a nonempty project-relative string")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ProjectError(f"asset path leaves the project: {relative}")
    return target


def studio_data(root: Path) -> Path:
    """Use AIVEE's Studio namespace for new projects and the root for legacy ones."""
    target = root / "studio-data" / "explainer"
    if target.is_symlink() or target.parent.is_symlink():
        raise ProjectError("Studio data directories must not be symlinks")
    if not target.exists() and not target.is_symlink():
        return root
    resolved = target.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ProjectError("Studio data directory leaves the AIVEE project")
    if not resolved.is_dir():
        return root
    if not (resolved / "project.json").is_file() and (root / "project.json").is_file():
        return root
    return resolved


def studio_file(root: Path, name: str) -> Path:
    return studio_data(root) / name


def probe_duration(path: Path) -> float:
    out = run(
        [command("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        duration = float(out)
    except ValueError as exc:
        raise ProjectError(f"could not read duration of {path}") from exc
    if duration <= 0:
        raise ProjectError(f"media duration must be positive: {path}")
    return duration
