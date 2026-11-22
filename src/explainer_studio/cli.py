"""Command-line interface used by the plugin's chat skills."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .common import ProjectError, command, file_hash, probe_duration, project_file, read_json, studio_data, studio_file, studio_home, write_json


class ResultError(ProjectError):
    def __init__(self, message: str, data: dict | None = None, next_steps: list[str] | None = None):
        super().__init__(message)
        self.data = data or {}
        self.next_steps = list(next_steps or [])


def command_payload(command: str, data: dict, next_steps: list[str], *, ok: bool = True, error: str | None = None) -> dict:
    """Stable result for --json: ok, command, data, next_steps, error."""
    return {"ok": ok, "command": command, "data": data, "next_steps": list(next_steps), "error": error}


def emit(args, data: dict, next_steps: list[str], *lines: str) -> None:
    if args.json:
        print(json.dumps(command_payload(args.command, data, next_steps), ensure_ascii=False))
        return
    for line in lines:
        print(line)


def add_command(subparsers, json_flags, name: str, **kwargs):
    return subparsers.add_parser(name, parents=[json_flags], **kwargs)


def command_step(name: str, *args: str) -> str:
    """One next-step command, with arguments quoted for a shell."""
    return " ".join(["explainer", name, *(shlex.quote(arg) for arg in args)])


def load_profile() -> dict:
    path = studio_home() / "profile.json"
    if not path.is_file():
        raise ResultError(
            "profile not set up; run `explainer setup` through the plugin",
            {},
            ["explainer setup"],
        )
    return read_json(path)


def show_profile(args) -> None:
    profile = load_profile().copy()
    if "voice_provider_default" not in profile:
        profile["voice_provider_default"] = "elevenlabs" if profile.get("voice_route") == "elevenlabs" else "ask"
    profile.pop("voice_route", None)
    profile.pop("voice_id", None)
    emit(args, profile, ["explainer init <project>"], json.dumps(profile, indent=2))


def _replace_avatar_pack(source: Path, destination: Path) -> Path | None:
    from .avatar import copy_pack, validate_pack

    stage = destination.with_name(f"{destination.name}.stage-{uuid.uuid4().hex}")
    backup = destination.with_name(f"{destination.name}.backup-{uuid.uuid4().hex}")
    try:
        copy_pack(source, stage)
        validate_pack(stage.parent, stage.name)
        if destination.exists():
            destination.rename(backup)
        stage.rename(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return backup if backup.exists() else None


def _rollback_avatar_pack(destination: Path, backup: Path | None) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if backup and backup.exists():
        backup.rename(destination)


def bootstrap(args) -> None:
    if sys.version_info < (3, 11):
        raise ProjectError("Python 3.11 or later is required to bootstrap Explainer Studio")
    plugin_root = Path(__file__).resolve().parents[2]
    environment = studio_home() / "venv"
    try:
        if not (environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")).is_file():
            subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        requirement = f"{plugin_root}[transcribe]" if args.transcribe else str(plugin_root)
        result = subprocess.run([str(python), "-m", "pip", "install", requirement], capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProjectError(f"could not create the managed Python environment: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ProjectError(f"could not install Studio dependencies: {detail[-1200:]}")
    emit(args, {"python": str(python)}, ["explainer doctor"], f"managed Studio environment ready: {python}")


def avatar_preview_command(args) -> None:
    from .avatar import preview_avatar

    root = Path(args.project).resolve()
    output = Path(args.output).resolve() if args.output else root / "renders" / "avatar-preview.png"
    path = preview_avatar(root, output)
    emit(args, {"output": str(path)}, [command_step("render", str(root), "--preview")], str(path))


def avatar_preview_pack_command(args) -> None:
    from .avatar import preview_pack

    path = preview_pack(Path(args.pack).resolve(), Path(args.output).resolve())
    emit(args, {"output": str(path)}, [command_step("setup", "--avatar-pack", str(Path(args.pack).resolve()))], str(path))


def avatar_validate_command(args) -> None:
    from .avatar import validate_pack

    pack = Path(args.pack).expanduser().resolve()
    manifest = validate_pack(pack.parent, pack.name)
    message = f"valid avatar pack: {manifest['name']} ({manifest['id']}@{manifest['version']})"
    emit(
        args,
        {"name": manifest["name"], "id": manifest["id"], "version": manifest["version"]},
        [command_step("setup", "--avatar-pack", str(pack))],
        message,
    )


def contact_sheet_command(args) -> None:
    from .quality import contact_sheet

    root = Path(args.project).resolve()
    output = Path(args.output).resolve() if args.output else root / "renders" / "contact-sheet.jpg"
    sheet = contact_sheet(root, Path(args.video).resolve(), output)
    video = str(Path(args.video).resolve())
    emit(args, {"output": str(sheet)}, [command_step("sync-check", str(root), video)], str(sheet))


def sync_check_command(args) -> None:
    from .quality import sync_check

    root = Path(args.project).resolve()
    report = sync_check(
        root, Path(args.video).resolve(), args.model, args.language,
        Path(args.render_words).resolve() if args.render_words else None,
    )
    emit(args, report, [], str(report))


def setup(args) -> None:
    from .engine import setup_aivee_home

    target = studio_home() / "profile.json"
    old = read_json(target) if target.is_file() else {}
    if target.exists() and not args.force:
        raise ProjectError(f"profile already exists: {target}; use --force after confirming changes")
    aivee_home = Path(args.home or old.get("aivee_home") or "~/AIVEE").expanduser().resolve()
    workspace = setup_aivee_home(aivee_home)
    brand = args.brand or old.get("brand") or "Explainer Studio"
    voice_provider_default = args.voice_provider_default or old.get("voice_provider_default")
    if not voice_provider_default:
        voice_provider_default = "elevenlabs" if old.get("voice_route") == "elevenlabs" else "ask"
    if voice_provider_default not in {"ask", "recording", "elevenlabs", "higgsfield", "suno"}:
        raise ProjectError("voice provider default must be ask, recording, elevenlabs, higgsfield, or suno")
    rhubarb_path = args.rhubarb_path or old.get("rhubarb_path")
    if rhubarb_path:
        rhubarb_file = Path(rhubarb_path).expanduser()
        rhubarb_path = str(rhubarb_file.resolve()) if rhubarb_file.is_file() else shutil.which(str(rhubarb_path))
        if not rhubarb_path:
            raise ProjectError("Rhubarb executable not found")
    colors = old.get("colors", {}).copy()
    for key, value, default in (("background", args.background, "#F6F8FC"), ("ink", args.ink, "#172236"), ("accent", args.accent, "#426BEB")):
        colors[key] = value or colors.get(key) or default
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", colors[key]):
            raise ProjectError(f"{key} must be a six-digit hex color")
    logo = old.get("logo")
    if args.logo:
        source = Path(args.logo).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ProjectError("logo must be an existing PNG or JPEG")
        from PIL import Image
        try:
            with Image.open(source) as image:
                image.verify()
        except OSError as exc:
            raise ProjectError("logo is not a readable image") from exc
        logo = f"assets/logo{source.suffix.lower()}"
        destination = studio_home() / logo
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source != destination:
            shutil.copy2(source, destination)
    plugin_root = Path(__file__).resolve().parents[2]
    avatar = args.avatar or old.get("avatar") or "emo"
    if avatar == "built-in":
        avatar = "emo"
    avatar_pack = old.get("avatar_pack")
    avatar_name = old.get("avatar_name", "Emo")
    avatar_backup = None
    avatar_destination = Path(workspace["avatarPacks"])
    if args.avatar_pack:
        from .avatar import validate_pack

        source = Path(args.avatar_pack).expanduser().resolve()
        manifest = validate_pack(source.parent, source.name)
        avatar_destination = avatar_destination / manifest["id"]
        if source != avatar_destination.resolve():
            if avatar_destination.exists():
                raise ProjectError(f"avatar pack id already exists in the AIVEE Library: {manifest['id']}")
            avatar_backup = _replace_avatar_pack(source, avatar_destination)
        avatar, avatar_pack = "custom", str(avatar_destination.resolve())
        avatar_name = manifest.get("name", "Custom")
    elif avatar == "emo":
        avatar_pack, avatar_name = None, "Emo"
    elif avatar == "custom" and avatar_pack:
        source = Path(avatar_pack).expanduser()
        source = source if source.is_absolute() else studio_home() / source
        source = source.resolve()
        from .avatar import validate_pack

        manifest = validate_pack(source.parent, source.name)
        avatar_destination = avatar_destination / manifest["id"]
        if source != avatar_destination.resolve():
            if avatar_destination.exists():
                validate_pack(avatar_destination.parent, avatar_destination.name)
            else:
                avatar_backup = _replace_avatar_pack(source, avatar_destination)
        avatar_pack = str(avatar_destination.resolve())
    if avatar == "custom" and not avatar_pack:
        raise ProjectError("custom avatar requires --avatar-pack")
    profile = {
        "version": 1, "brand": brand, "language": args.language or old.get("language") or "en",
        "voice_provider_default": voice_provider_default,
        "avatar": avatar, "avatar_name": avatar_name, "avatar_pack": avatar_pack,
        "rhubarb_path": str(Path(rhubarb_path).expanduser().resolve()) if rhubarb_path else None,
        "aivee_home": str(aivee_home), "aivee_workspace": workspace,
        "colors": colors, "logo": logo, "cta": args.cta or old.get("cta") or "",
    }
    staged_profile = target.with_name(f"profile.json.stage-{uuid.uuid4().hex}")
    try:
        write_json(staged_profile, profile)
        staged_profile.replace(target)
    except Exception:
        if args.avatar_pack and source != avatar_destination.resolve():
            _rollback_avatar_pack(avatar_destination, avatar_backup)
        raise
    finally:
        staged_profile.unlink(missing_ok=True)
    if avatar_backup:
        shutil.rmtree(avatar_backup)
    emit(
        args,
        {"profile": str(target), "aivee_home": str(aivee_home)},
        ["explainer init <project>"],
        f"profile saved: {target}",
        f"AIVEE home: {aivee_home}",
    )


def doctor(args) -> None:
    from .engine import resolve_aivee

    missing = []
    lines = [f"python: {sys.version.split()[0]}"]
    checks = {"python": sys.version.split()[0], "pillow": None, "faster_whisper": False, "aivee": None, "profile": None}
    if sys.version_info < (3, 11):
        missing.append("Python 3.11+")
    try:
        import PIL
        checks["pillow"] = PIL.__version__
        lines.append(f"pillow: {PIL.__version__}")
    except ImportError:
        lines.append("pillow: MISSING (run `explainer bootstrap`)")
        missing.append("Pillow")
    for name in ("ffmpeg", "ffprobe"):
        found = shutil.which(name)
        checks[name] = found
        lines.append(f"{name}: {found or 'MISSING'}")
        if not found:
            missing.append(name)
    node, npm = shutil.which("node"), shutil.which("npm")
    node_version = ""
    if node:
        result = subprocess.run([node, "--version"], capture_output=True, text=True)
        node_version = result.stdout.strip() if result.returncode == 0 else "unknown version"
    node_label = f"{node} ({node_version})" if node else "MISSING"
    checks["node"] = node_label
    checks["npm"] = npm
    lines.append(f"node: {node_label}")
    lines.append(f"npm: {npm or 'MISSING'}")
    try:
        node_major = int(node_version.removeprefix("v").split(".", 1)[0])
    except ValueError:
        node_major = 0
    if not node or node_major < 22:
        missing.append("Node.js 22+")
    if not npm:
        missing.append("npm")
    try:
        import faster_whisper  # noqa: F401
        checks["faster_whisper"] = True
        lines.append("faster-whisper: available")
    except ImportError:
        lines.append("faster-whisper: optional, needed for automatic word timing")
    path = studio_home() / "profile.json"
    lines.append(f"profile: {path if path.is_file() else 'not set up'}")
    checks["profile"] = str(path) if path.is_file() else None
    try:
        _, package_root = resolve_aivee()
        manifest_path = Path(package_root) / "package.json"
        version = read_json(manifest_path).get("version", "unknown") if manifest_path.is_file() else "unknown"
        checks["aivee"] = version
        lines.append(f"aivee: {version} ({package_root})")
    except ProjectError as exc:
        lines.append(f"aivee: NOT READY ({exc})")
        missing.append("AIVEE (run `explainer install-engine`)")
    from .engine import _browser_env
    browser = _browser_env(studio_home() / "browser-cache").get("HYPERFRAMES_BROWSER_PATH")
    checks["render_browser"] = browser
    lines.append(f"render browser: {browser or 'MISSING (install Chrome or Edge)'}")
    if not browser:
        missing.append("Chrome or Edge")
    profile = read_json(path) if path.is_file() else {}
    rhubarb = os.environ.get("RHUBARB_PATH") or profile.get("rhubarb_path") or shutil.which("rhubarb")
    if rhubarb and not Path(rhubarb).expanduser().is_file():
        rhubarb = shutil.which(rhubarb)
    rhubarb_label = str(Path(rhubarb).expanduser().resolve()) if rhubarb else "optional; amplitude lip sync will be used"
    checks["rhubarb"] = str(Path(rhubarb).expanduser().resolve()) if rhubarb else None
    lines.append(f"rhubarb: {rhubarb_label}")
    checks["missing"] = missing
    steps = _doctor_steps(missing, path.is_file())
    if missing:
        if not args.json:
            for line in lines:
                print(line)
        raise ResultError("required setup is incomplete: " + ", ".join(missing), checks, steps)
    emit(args, checks, steps, *lines)


def _doctor_steps(missing: list[str], profile_ready: bool) -> list[str]:
    steps = []
    if any(item in {"Python 3.11+", "Pillow"} for item in missing):
        steps.append("explainer bootstrap")
    if any(item.startswith(("Node.js", "npm", "AIVEE")) for item in missing):
        steps.append("explainer install-engine")
    if not missing and not profile_ready:
        steps.append("explainer setup")
    if not missing and profile_ready:
        steps.append("explainer init <project>")
    return steps


def install_engine(args) -> None:
    from .engine import ensure_aivee

    command, package_root = ensure_aivee()
    result = subprocess.run([*command, "capabilities"], capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ProjectError(f"AIVEE installation could not be verified: {detail[-1200:]}")
    manifest_path = Path(package_root) / "package.json"
    version = read_json(manifest_path).get("version", "unknown") if manifest_path.is_file() else "unknown"
    message = f"AIVEE {version} ready from the global npm installation: {package_root}"
    emit(args, {"version": version, "package": str(package_root)}, ["explainer doctor"], message)


def engine_command(args) -> int:
    from .engine import resolve_aivee

    arguments = args.arguments
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if not arguments:
        raise ProjectError("provide an AIVEE command after `explainer engine --`")
    program, _ = resolve_aivee()
    if not args.json:
        return subprocess.run([*program, *arguments]).returncode
    result = subprocess.run([*program, *arguments], capture_output=True, text=True)
    detail = (result.stderr or result.stdout).strip()
    data = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    if result.returncode:
        print(json.dumps(command_payload(
            args.command, data, [], ok=False, error=detail or f"AIVEE exited {result.returncode}",
        ), ensure_ascii=False))
        return result.returncode
    emit(args, data, [])
    return 0


def init(args) -> None:
    from .engine import create_aivee_project, register_asset

    profile = load_profile()
    for label in ("voice", "script"):
        value = getattr(args, label)
        if value:
            source = Path(value).expanduser().resolve()
            if not source.is_file():
                raise ProjectError(f"{label} file not found: {source}")
    duration = probe_duration(Path(args.voice).expanduser().resolve()) if args.voice else 10
    result = create_aivee_project(Path(profile["aivee_home"]), args.project, duration)
    root = Path(result["project"]).resolve()
    data = Path(result["studioData"]).resolve()
    voice = "assets/voice.mp3"
    if args.voice:
        source = Path(args.voice).expanduser().resolve()
        if not source.is_file():
            raise ProjectError(f"voice file not found: {source}")
        voice = register_asset(root, source, "narration")["path"]
    if args.script:
        source = Path(args.script).expanduser().resolve()
        if not source.is_file():
            raise ProjectError(f"script file not found: {source}")
        shutil.copy2(source, data / "script.txt")
    else:
        (data / "script.txt").write_text("", encoding="utf-8")
    project = {
        "version": 1, "title": args.title or root.name, "brand": profile["brand"],
        "language": profile["language"], "voice": voice, "avatar_pack": None,
        "colors": profile["colors"], "width": 1920, "height": 1080, "fps": 60,
        "music": None, "logo": None, "cta": profile.get("cta", ""),
    }
    if profile.get("logo"):
        source = studio_home() / profile["logo"]
        if source.is_file():
            project["logo"] = register_asset(root, source, "studio-logo")["path"]
    if profile.get("avatar_pack"):
        source = Path(profile["avatar_pack"])
        if not source.is_dir():
            raise ProjectError(f"saved avatar pack not found: {source}")
        project["avatar_pack"] = str(source.resolve())
    write_json(data / "project.json", project)
    step = command_step("transcribe", str(root)) if args.voice else command_step("attach-voice", str(root), "<voice-file>")
    emit(args, {"project": str(root)}, [step], f"project created: {root}")


def attach_voice(args) -> None:
    from .engine import register_asset

    root = Path(args.project).resolve()
    data = studio_data(root)
    project = read_json(data / "project.json")
    source = Path(args.file).expanduser().resolve()
    if not source.is_file():
        raise ProjectError(f"voice file not found: {source}")
    suffix = source.suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a", ".flac"}:
        raise ProjectError("voice file must be MP3, WAV, M4A, or FLAC")
    if project.get("voice") != "assets/voice.mp3":
        raise ProjectError("voice already exists; create a new project for a new take")
    asset = register_asset(root, source, "narration")
    project["voice"] = asset["path"]
    write_json(data / "project.json", project)
    voice = root / asset["path"]
    emit(args, {"voice": str(voice)}, [command_step("transcribe", str(root))], f"voice attached: {voice}")


def retime(args) -> None:
    import hashlib
    import tempfile

    from .engine import create_aivee_project, list_project_assets, register_asset
    from .timing import build_storyboard, transcribe, validate_storyboard, validate_words

    source = Path(args.project).expanduser().resolve()
    source_data = studio_data(source)
    voice = Path(args.voice).expanduser().resolve()
    if not voice.is_file():
        raise ProjectError(f"new voice file not found: {voice}")
    old_project = read_json(source_data / "project.json")
    old_board = read_json(source_data / "storyboard.json")
    validate_storyboard(source, old_board)
    profile = load_profile()
    duration = probe_duration(voice)
    script = source_data / "script.txt"
    if not script.is_file():
        raise ProjectError(f"project script not found: {script}")
    if args.words:
        words_source = Path(args.words).expanduser().resolve()
        preflight_words = read_json(words_source)
        validate_words(preflight_words, duration)
    else:
        preflight_words = None

    assets = {}
    for relative in [old_project.get("logo"), old_project.get("music")]:
        if relative:
            assets[relative] = project_file(source, relative)
    for scene in old_board["scenes"]:
        references = [scene.get("asset"), *(cue.get("asset") for cue in scene.get("visual_cues", []))]
        for relative in references:
            if relative:
                assets[relative] = project_file(source, relative)
    for relative, path in assets.items():
        if not path.is_file():
            raise ProjectError(f"project asset not found: {path}")

    project = dict(old_project)
    if project.get("avatar_pack"):
        avatar_value = Path(project["avatar_pack"]).expanduser()
        avatar_source = avatar_value.resolve() if avatar_value.is_absolute() else project_file(source, str(avatar_value))
        if not avatar_source.is_dir():
            raise ProjectError(f"avatar pack not found: {avatar_source}")
        from .avatar import validate_pack

        avatar_manifest = validate_pack(avatar_source.parent, avatar_source.name)
        avatar_library = Path(profile["aivee_workspace"]["avatarPacks"])
        avatar_target = avatar_library / avatar_manifest["id"]
        if not avatar_target.exists():
            _replace_avatar_pack(avatar_source, avatar_target)
        validate_pack(avatar_target.parent, avatar_target.name)
        project["avatar_pack"] = str(avatar_target.resolve())

    # Run transcription and storyboard validation before AIVEE reserves the target slug.
    with tempfile.TemporaryDirectory(prefix="explainer-retime-") as temporary:
        preflight = Path(temporary)
        preflight_data = preflight / "studio-data" / "explainer"
        preflight_data.mkdir(parents=True)
        preflight_voice = preflight / "assets" / f"narration{voice.suffix.lower()}"
        preflight_voice.parent.mkdir(parents=True)
        shutil.copy2(voice, preflight_voice)
        preflight_project = {**project, "voice": preflight_voice.relative_to(preflight).as_posix(), "avatar_pack": None}
        write_json(preflight_data / "project.json", preflight_project)
        shutil.copy2(script, preflight_data / "script.txt")
        if preflight_words is not None:
            write_json(preflight_data / "words.json", preflight_words)
        else:
            transcribe(preflight, args.model, args.language)
        board = build_storyboard(preflight)
        if len(board["scenes"]) != len(old_board["scenes"]):
            raise ProjectError("retimed scene count differs; review the new storyboard before copying scene choices")
        words = read_json(preflight_data / "words.json")

    fingerprint_source = {
        "project": old_project,
        "storyboard": old_board,
        "script_sha256": file_hash(script),
        "voice_sha256": file_hash(voice),
        "words_sha256": file_hash(words_source) if args.words else None,
        "model": args.model if not args.words else None,
        "language": args.language if not args.words else None,
        "assets": {relative: file_hash(path) for relative, path in assets.items()},
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.new_project):
        raise ProjectError("use a lowercase kebab-case project slug")
    projects = Path(profile["aivee_workspace"]["projects"]).expanduser().resolve()
    expected_target = projects / args.new_project
    marker_name = ".explainer-retime.json"
    if expected_target.is_symlink():
        raise ProjectError("AIVEE project path must not be a symlink")
    if expected_target.exists():
        if expected_target.resolve().parent != projects:
            raise ProjectError("AIVEE project path must be a direct child of its projects directory")
        target, data = expected_target.resolve(), studio_data(expected_target.resolve())
        marker = data / marker_name
        marker_data = read_json(marker) if marker.is_file() and not marker.is_symlink() else None
        if not isinstance(marker_data, dict) or marker_data.get("fingerprint") != fingerprint:
            raise ProjectError(f"AIVEE project already exists: {target}")
    else:
        result = create_aivee_project(Path(profile["aivee_home"]), args.new_project, duration)
        target, data = Path(result["project"]).resolve(), Path(result["studioData"]).resolve()
        write_json(data / marker_name, {"fingerprint": fingerprint})

    registered_assets = list_project_assets(target).get("assets", [])
    asset_paths = {}

    def register_or_reuse(path: Path, asset_id: str) -> str:
        digest = file_hash(path)
        existing = next((asset for asset in registered_assets if asset.get("id") == asset_id), None)
        if existing:
            if existing.get("sha256") != digest:
                raise ProjectError(f"incomplete retime has a conflicting registered asset: {asset_id}")
            return existing["path"]
        asset = register_asset(target, path, asset_id)
        registered_assets.append(asset)
        return asset["path"]

    project["voice"] = register_or_reuse(voice, "narration")

    def copy_asset(relative: str | None) -> str | None:
        if relative is None:
            return None
        if relative not in asset_paths:
            asset_id = "source-" + hashlib.sha256(relative.encode()).hexdigest()[:10]
            asset_paths[relative] = register_or_reuse(assets[relative], asset_id)
        return asset_paths[relative]

    for field in ("logo", "music"):
        project[field] = copy_asset(project.get(field))
    write_json(data / "project.json", project)
    shutil.copy2(script, data / "script.txt")
    write_json(data / "words.json", words)
    for new, old in zip(board["scenes"], old_board["scenes"]):
        for key in ("headline", "pose", "asset", "visual_label"):
            if key in old:
                new[key] = copy_asset(old[key]) if key == "asset" else old[key]
        old_duration = float(old["end"]) - float(old["start"])
        new_duration = float(new["end"]) - float(new["start"])
        if old_duration > 0:
            new["visual_cues"] = [{
                **cue, "asset": copy_asset(cue["asset"]),
                "start": float(new["start"]) + (float(cue["start"]) - float(old["start"])) / old_duration * new_duration,
                "duration": float(cue["duration"]) / old_duration * new_duration,
            } for cue in old.get("visual_cues", [])]
    validate_storyboard(target, board)
    write_json(studio_file(target, "storyboard.json"), board)
    (data / marker_name).unlink(missing_ok=True)
    emit(
        args,
        {"project": str(target)},
        [command_step("approve", str(target))],
        f"retimed project created: {target}; review and approve the new storyboard",
    )


def attach_avatar(args) -> None:
    from .avatar import copy_pack, validate_pack

    root = Path(args.project).resolve()
    source = Path(args.pack).expanduser().resolve()
    if not source.is_dir():
        raise ProjectError(f"avatar pack not found: {source}")
    profile = load_profile()
    library = Path(profile["aivee_workspace"]["avatarPacks"])
    manifest = validate_pack(source.parent, source.name)
    target = library / manifest["id"]
    if target.exists():
        if source.resolve() != target.resolve():
            raise ProjectError(f"avatar pack id already exists in the AIVEE library: {target}")
        validate_pack(target.parent, target.name)
    else:
        _replace_avatar_pack(source, target)
    data = studio_data(root)
    project = read_json(data / "project.json")
    project["avatar_pack"] = str(target.resolve())
    write_json(data / "project.json", project)
    emit(args, {"project": str(target)}, [command_step("avatar-preview", str(target))], f"avatar attached: {target}")


def approve(args) -> None:
    from .timing import storyboard_hash, validate_storyboard

    root = Path(args.project).resolve()
    data = studio_data(root)
    board = read_json(data / "storyboard.json")
    if not isinstance(board.get("source"), dict):
        board["source"] = {}
    board["source"]["words_sha256"] = file_hash(data / "words.json")
    validate_storyboard(root, board)
    board["approved"] = True
    board["approval_hash"] = storyboard_hash(board)
    write_json(data / "storyboard.json", board)
    emit(
        args,
        {"storyboard": str(data / "storyboard.json")},
        [command_step("render", str(root), "--preview")],
        f"storyboard approved: {data / 'storyboard.json'}",
    )


def check(args) -> None:
    import json
    from .timing import validate_storyboard

    root = Path(args.project).resolve()
    data = studio_data(root)
    project = read_json(data / "project.json")
    voice = project_file(root, project["voice"])
    duration = probe_duration(voice)
    board = read_json(data / "storyboard.json")
    validate_storyboard(root, board, duration)
    output = Path(args.video).resolve()
    if not output.is_file():
        raise ProjectError(f"video not found: {output}")
    actual = probe_duration(output)
    if abs(actual - duration) > .25:
        raise ProjectError(f"video duration {actual:.3f}s differs from voice {duration:.3f}s")
    streams = subprocess.run(
        [command("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(output)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(streams.stdout)["streams"]
    video = next((s for s in data if s.get("codec_type") == "video"), None)
    audio = next((s for s in data if s.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise ProjectError("render needs both video and narration audio streams")
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
        raise ProjectError("render is not H.264 video with AAC audio")
    full = (int(project.get("width", 1920)), int(project.get("height", 1080)))
    size = (int(video["width"]), int(video["height"]))
    allowed = {full, (round(full[0] / 2), round(full[1] / 2)), (1080, 1920), (540, 960)}
    if size not in allowed:
        raise ProjectError(f"unexpected video size: {size[0]}x{size[1]}")
    message = f"PASS: H.264/AAC {size[0]}x{size[1]}, {actual:.3f}s voice/video, {len(board['scenes'])} scenes"
    emit(
        args,
        {"video": str(output), "width": size[0], "height": size[1], "duration": round(actual, 3), "scenes": len(board["scenes"])},
        [command_step("contact-sheet", str(root), str(output))],
        message,
    )


def default_render_name(*, preview: bool, portrait: bool) -> str:
    suffix = "-portrait" if portrait else ""
    return f"{'draft' if preview else 'final'}{suffix}-engine.mp4"


def render_engine_command(args) -> None:
    from .engine import render_with_engine

    root = Path(args.project).resolve()
    profile = load_profile()
    target = Path(args.output).resolve() if args.output else root / "renders" / default_render_name(preview=args.preview, portrait=args.portrait)
    output = render_with_engine(root, target, profile, preview=args.preview, portrait=args.portrait)
    if args.preview:
        step = command_step("render", str(root), *(["--portrait"] if args.portrait else []))
    else:
        step = command_step("check", str(root), str(output))
    emit(args, {"video": str(output), "preview": bool(args.preview), "portrait": bool(args.portrait)}, [step], str(output))


def transcribe_command(args) -> None:
    from .timing import transcribe

    root = Path(args.project).resolve()
    count = transcribe(root, args.model, args.language)
    emit(args, {"words": count}, [command_step("storyboard", str(root))], f"{count} words timed")


def import_words_command(args) -> None:
    from .timing import import_words

    root = Path(args.project).resolve()
    count = import_words(root, Path(args.file).resolve())
    emit(args, {"words": count}, [command_step("storyboard", str(root))], f"{count} words imported")


def storyboard_command(args) -> None:
    from .timing import build_storyboard

    root = Path(args.project).resolve()
    count = len(build_storyboard(root)["scenes"])
    emit(
        args,
        {"scenes": count, "storyboard": str(studio_file(root, "storyboard.json"))},
        [command_step("approve", str(root))],
        f"{count} scenes planned; review storyboard.json before approval",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="explainer", description="Create voice-timed explainer videos")
    json_flags = argparse.ArgumentParser(add_help=False)
    json_flags.add_argument("--json", action="store_true", help="print one JSON result on stdout")
    sub = parser.add_subparsers(dest="command", required=True)
    p = add_command(sub, json_flags, "doctor", help="check local tools")
    p.set_defaults(handler=doctor)
    p = add_command(sub, json_flags, "bootstrap", help="create the managed Studio Python environment")
    p.add_argument("--transcribe", action="store_true", help="also install optional faster-whisper dependencies")
    p.set_defaults(handler=bootstrap)
    p = add_command(sub, json_flags, "install-engine", help="install AIVEE globally if missing, or verify the shared CLI")
    p.set_defaults(handler=install_engine)
    p = add_command(sub, json_flags, "engine", help="run an AIVEE CLI command")
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    p.set_defaults(handler=engine_command)
    p = add_command(sub, json_flags, "setup", help="save a creator profile")
    p.add_argument("--brand")
    p.add_argument("--language")
    p.add_argument("--voice-provider-default", choices=["ask", "recording", "elevenlabs", "higgsfield", "suno"])
    p.add_argument("--avatar", choices=["emo", "built-in", "custom"])
    p.add_argument("--avatar-pack")
    p.add_argument("--rhubarb-path")
    p.add_argument("--home", help="AIVEE home folder (defaults to ~/AIVEE)")
    p.add_argument("--logo")
    p.add_argument("--cta")
    p.add_argument("--background")
    p.add_argument("--ink")
    p.add_argument("--accent")
    p.add_argument("--force", action="store_true")
    p.set_defaults(handler=setup)
    p = add_command(sub, json_flags, "profile", help="show saved non-secret settings")
    p.set_defaults(handler=show_profile)
    p = add_command(sub, json_flags, "init", help="create a film project")
    p.add_argument("project")
    p.add_argument("--title")
    p.add_argument("--script")
    p.add_argument("--voice")
    p.set_defaults(handler=init)
    p = add_command(sub, json_flags, "attach-voice", help="attach a narrated take")
    p.add_argument("project")
    p.add_argument("file")
    p.set_defaults(handler=attach_voice)
    p = add_command(sub, json_flags, "retime", help="create a new AIVEE project from a re-recorded take")
    p.add_argument("project")
    p.add_argument("new_project")
    p.add_argument("--voice", required=True)
    p.add_argument("--words")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.set_defaults(handler=retime)
    p = add_command(sub, json_flags, "attach-avatar", help="attach an avatar sprite pack")
    p.add_argument("project")
    p.add_argument("pack")
    p.set_defaults(handler=attach_avatar)
    p = add_command(sub, json_flags, "avatar-preview", help="make a contact sheet of avatar poses and mouth shapes")
    p.add_argument("project")
    p.add_argument("--output")
    p.set_defaults(handler=avatar_preview_command)
    p = add_command(sub, json_flags, "avatar-preview-pack", help="preview a custom pack before setup")
    p.add_argument("pack")
    p.add_argument("--output", required=True)
    p.set_defaults(handler=avatar_preview_pack_command)
    p = add_command(sub, json_flags, "avatar-validate", help="validate a standardized avatar pack folder")
    p.add_argument("pack")
    p.set_defaults(handler=avatar_validate_command)
    p = add_command(sub, json_flags, "transcribe", help="generate word timing from narration")
    p.add_argument("project")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.set_defaults(handler=transcribe_command)
    p = add_command(sub, json_flags, "import-words", help="use reviewed word timings from JSON")
    p.add_argument("project")
    p.add_argument("file")
    p.set_defaults(handler=import_words_command)
    p = add_command(sub, json_flags, "storyboard", help="align script paragraphs to speech")
    p.add_argument("project")
    p.set_defaults(handler=storyboard_command)
    p = add_command(sub, json_flags, "approve", help="mark a reviewed storyboard approved")
    p.add_argument("project")
    p.set_defaults(handler=approve)
    p = add_command(sub, json_flags, "render", help="render a preview or final MP4 through the AI Video Editing Engine")
    p.add_argument("project")
    p.add_argument("--preview", action="store_true", help="render a draft before storyboard approval")
    p.add_argument("--portrait", action="store_true")
    p.add_argument("--output")
    p.set_defaults(handler=render_engine_command)
    p = add_command(sub, json_flags, "render-engine", help="render through the AI Video Editing Engine")
    p.add_argument("project")
    p.add_argument("--preview", action="store_true", help="render a draft before storyboard approval")
    p.add_argument("--portrait", action="store_true")
    p.add_argument("--output")
    p.set_defaults(handler=render_engine_command)
    p = add_command(sub, json_flags, "check", help="validate a rendered video's basic timing")
    p.add_argument("project")
    p.add_argument("video")
    p.set_defaults(handler=check)
    p = add_command(sub, json_flags, "contact-sheet", help="make a scene review sheet from a rendered video")
    p.add_argument("project")
    p.add_argument("video")
    p.add_argument("--output")
    p.set_defaults(handler=contact_sheet_command)
    p = add_command(sub, json_flags, "sync-check", help="compare rendered speech timings with source words")
    p.add_argument("project")
    p.add_argument("video")
    p.add_argument("--render-words")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.set_defaults(handler=sync_check_command)
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
        return result if isinstance(result, int) else 0
    except (ProjectError, OSError, KeyError, ValueError) as exc:
        if getattr(args, "json", False):
            print(json.dumps(command_payload(
                args.command,
                getattr(exc, "data", {}) or {},
                getattr(exc, "next_steps", []) or [],
                ok=False,
                error=str(exc),
            ), ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
