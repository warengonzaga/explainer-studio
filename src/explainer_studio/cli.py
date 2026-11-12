"""Command-line interface used by the plugin's chat skills."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .common import ProjectError, command, file_hash, probe_duration, project_file, read_json, studio_home, write_json


def load_profile() -> dict:
    path = studio_home() / "profile.json"
    if not path.is_file():
        raise ProjectError("profile not set up; run `explainer setup` through the plugin")
    return read_json(path)


def _replace_avatar_pack(source: Path, destination: Path) -> Path | None:
    from .avatar import copy_pack, validate_pack

    destination.parent.mkdir(parents=True, exist_ok=True)
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
    print(f"managed Studio environment ready: {python}")


def avatar_preview_command(args) -> None:
    from .avatar import preview_avatar

    root = Path(args.project).resolve()
    output = Path(args.output).resolve() if args.output else root / "renders" / "avatar-preview.png"
    print(preview_avatar(root, output))


def avatar_preview_pack_command(args) -> None:
    from .avatar import preview_pack

    print(preview_pack(Path(args.pack).resolve(), Path(args.output).resolve()))


def contact_sheet_command(args) -> None:
    from .quality import contact_sheet

    root = Path(args.project).resolve()
    output = Path(args.output).resolve() if args.output else root / "renders" / "contact-sheet.jpg"
    print(contact_sheet(root, Path(args.video).resolve(), output))


def sync_check_command(args) -> None:
    from .quality import sync_check

    print(sync_check(
        Path(args.project).resolve(), Path(args.video).resolve(), args.model, args.language,
        Path(args.render_words).resolve() if args.render_words else None,
    ))


def setup(args) -> None:
    target = studio_home() / "profile.json"
    old = read_json(target) if target.is_file() else {}
    if target.exists() and not args.force:
        raise ProjectError(f"profile already exists: {target}; use --force after confirming changes")
    brand = args.brand or old.get("brand") or "Explainer Studio"
    voice_route = args.voice_route or old.get("voice_route") or "recording"
    if voice_route not in {"recording", "elevenlabs"}:
        raise ProjectError("voice route must be recording or elevenlabs")
    voice_id = args.voice_id or old.get("voice_id")
    if voice_route == "elevenlabs" and not voice_id:
        raise ProjectError("ElevenLabs requires --voice-id (API key stays in ELEVENLABS_API_KEY)")
    if voice_id and not re.fullmatch(r"[A-Za-z0-9_-]+", voice_id):
        raise ProjectError("voice ID contains unsupported characters")
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
    avatar_installed = False
    avatar_destination = studio_home() / "assets" / "avatar"
    if args.avatar_pack:
        from .avatar import validate_pack

        source = Path(args.avatar_pack).expanduser().resolve()
        manifest = validate_pack(source.parent, source.name)
        if source != avatar_destination.resolve():
            avatar_backup = _replace_avatar_pack(source, avatar_destination)
        avatar, avatar_pack = "custom", "assets/avatar"
        avatar_name = manifest.get("name", "Custom")
    elif avatar == "emo":
        from .avatar import copy_pack, validate_pack

        avatar_destination = studio_home() / "assets" / "emo"
        if avatar_destination.exists():
            validate_pack(avatar_destination.parent, avatar_destination.name)
        else:
            copy_pack(plugin_root / "assets" / "avatars" / "emo", avatar_destination)
            avatar_installed = True
        avatar_pack, avatar_name = "assets/emo", "Emo"
    if avatar == "custom" and not avatar_pack:
        raise ProjectError("custom avatar requires --avatar-pack")
    profile = {
        "version": 1, "brand": brand, "language": args.language or old.get("language") or "en",
        "voice_route": voice_route, "voice_id": voice_id,
        "avatar": avatar, "avatar_name": avatar_name, "avatar_pack": avatar_pack,
        "rhubarb_path": str(Path(rhubarb_path).expanduser().resolve()) if rhubarb_path else None,
        "output_dir": str(Path(args.output_dir or old.get("output_dir") or "~/Explainer Studio").expanduser().resolve()),
        "colors": colors, "logo": logo, "cta": args.cta or old.get("cta") or "",
    }
    staged_profile = target.with_name(f"profile.json.stage-{uuid.uuid4().hex}")
    try:
        write_json(staged_profile, profile)
        staged_profile.replace(target)
    except Exception:
        if args.avatar_pack and source != avatar_destination.resolve():
            _rollback_avatar_pack(avatar_destination, avatar_backup)
        elif avatar_installed and avatar_destination.exists():
            shutil.rmtree(avatar_destination)
        raise
    finally:
        staged_profile.unlink(missing_ok=True)
    if avatar_backup:
        shutil.rmtree(avatar_backup)
    print(f"profile saved: {target}")


def doctor(_) -> None:
    from .engine import resolve_aivee

    missing = []
    print(f"python: {sys.version.split()[0]}")
    if sys.version_info < (3, 11):
        missing.append("Python 3.11+")
    try:
        import PIL
        print(f"pillow: {PIL.__version__}")
    except ImportError:
        print("pillow: MISSING (run `explainer bootstrap`)")
        missing.append("Pillow")
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        print(f"{name}: {path or 'MISSING'}")
        if not path:
            missing.append(name)
    node, npm = shutil.which("node"), shutil.which("npm")
    node_version = ""
    if node:
        result = subprocess.run([node, "--version"], capture_output=True, text=True)
        node_version = result.stdout.strip() if result.returncode == 0 else "unknown version"
    node_label = f"{node} ({node_version})" if node else "MISSING"
    print(f"node: {node_label}")
    print(f"npm: {npm or 'MISSING'}")
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
        print("faster-whisper: available")
    except ImportError:
        print("faster-whisper: optional, needed for automatic word timing")
    path = studio_home() / "profile.json"
    print(f"profile: {path if path.is_file() else 'not set up'}")
    try:
        _, package_root = resolve_aivee()
        manifest_path = Path(package_root) / "package.json"
        version = read_json(manifest_path).get("version", "unknown") if manifest_path.is_file() else "unknown"
        print(f"aivee: {version} ({package_root})")
    except ProjectError as exc:
        print(f"aivee: NOT READY ({exc})")
        missing.append("AIVEE (run `explainer install-engine`)")
    from .engine import _browser_env
    browser = _browser_env(studio_home() / "browser-cache").get("HYPERFRAMES_BROWSER_PATH")
    print(f"render browser: {browser or 'MISSING (install Chrome or Edge)'}")
    if not browser:
        missing.append("Chrome or Edge")
    profile = read_json(path) if path.is_file() else {}
    rhubarb = os.environ.get("RHUBARB_PATH") or profile.get("rhubarb_path") or shutil.which("rhubarb")
    if rhubarb and not Path(rhubarb).expanduser().is_file():
        rhubarb = shutil.which(rhubarb)
    print(f"rhubarb: {Path(rhubarb).expanduser().resolve() if rhubarb else 'optional; amplitude lip sync will be used'}")
    if missing:
        raise ProjectError("required setup is incomplete: " + ", ".join(missing))


def install_engine(_) -> None:
    from .engine import ensure_aivee

    command, package_root = ensure_aivee()
    result = subprocess.run([*command, "capabilities"], capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ProjectError(f"AIVEE installation could not be verified: {detail[-1200:]}")
    manifest_path = Path(package_root) / "package.json"
    version = read_json(manifest_path).get("version", "unknown") if manifest_path.is_file() else "unknown"
    print(f"AIVEE {version} ready: {package_root}")


def engine_command(args) -> int:
    from .engine import resolve_aivee

    arguments = args.arguments
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if not arguments:
        raise ProjectError("provide an AIVEE command after `explainer engine --`")
    command, _ = resolve_aivee()
    return subprocess.run([*command, *arguments]).returncode


def init(args) -> None:
    from .avatar import copy_pack

    profile = load_profile()
    root = Path(args.project).expanduser().resolve()
    if root.exists():
        raise ProjectError(f"project already exists: {root}")
    for label in ("voice", "script"):
        value = getattr(args, label)
        if value:
            source = Path(value).expanduser().resolve()
            if not source.is_file():
                raise ProjectError(f"{label} file not found: {source}")
    root.mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "renders").mkdir()
    voice = "assets/voice.mp3"
    if args.voice:
        source = Path(args.voice).expanduser().resolve()
        if not source.is_file():
            raise ProjectError(f"voice file not found: {source}")
        voice = f"assets/voice{source.suffix.lower()}"
        shutil.copy2(source, root / voice)
    if args.script:
        source = Path(args.script).expanduser().resolve()
        if not source.is_file():
            raise ProjectError(f"script file not found: {source}")
        shutil.copy2(source, root / "script.txt")
    else:
        (root / "script.txt").write_text("", encoding="utf-8")
    project = {
        "version": 1, "title": args.title or root.name, "brand": profile["brand"],
        "language": profile["language"], "voice": voice, "avatar_pack": None,
        "colors": profile["colors"], "width": 1920, "height": 1080, "fps": 60,
        "music": None, "logo": None, "cta": profile.get("cta", ""),
    }
    if profile.get("logo"):
        source = studio_home() / profile["logo"]
        if source.is_file():
            project["logo"] = "assets/" + source.name
            shutil.copy2(source, root / project["logo"])
    if profile.get("avatar_pack"):
        source = studio_home() / profile["avatar_pack"]
        if not source.is_dir():
            raise ProjectError(f"saved avatar pack not found: {source}")
        copy_pack(source, root / "assets" / "avatar")
        project["avatar_pack"] = "assets/avatar"
    write_json(root / "project.json", project)
    print(f"project created: {root}")


def attach_voice(args) -> None:
    root = Path(args.project).resolve()
    project = read_json(root / "project.json")
    source = Path(args.file).expanduser().resolve()
    if not source.is_file():
        raise ProjectError(f"voice file not found: {source}")
    suffix = source.suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a", ".flac"}:
        raise ProjectError("voice file must be MP3, WAV, M4A, or FLAC")
    target = root / "assets" / f"voice{suffix}"
    if target.exists():
        raise ProjectError(f"voice already exists: {target}; create a new project for a new take")
    shutil.copy2(source, target)
    project["voice"] = str(target.relative_to(root)).replace("\\", "/")
    write_json(root / "project.json", project)
    print(f"voice attached: {target}")


def retime(args) -> None:
    from .timing import build_storyboard, import_words, transcribe, validate_storyboard

    source = Path(args.project).expanduser().resolve()
    target = Path(args.new_project).expanduser().resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ProjectError("new project must not overlap the source project")
    if target.exists():
        raise ProjectError(f"retimed project already exists: {target}")
    voice = Path(args.voice).expanduser().resolve()
    if not voice.is_file():
        raise ProjectError(f"new voice file not found: {voice}")
    old_project = read_json(source / "project.json")
    old_board = read_json(source / "storyboard.json")
    validate_storyboard(source, old_board)
    old_voice = project_file(source, old_project["voice"])

    def ignore_artifacts(directory: str, names: list[str]) -> set[str]:
        current = Path(directory).resolve()
        ignored = set(names) & {"renders", ".work", "engine", "words.json", "storyboard.json"} if current == source else set()
        if current == old_voice.parent.resolve():
            ignored.add(old_voice.name)
        return ignored

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise ProjectError(f"retimed project already exists: {target}") from exc
    try:
        shutil.copytree(source, target, ignore=ignore_artifacts, dirs_exist_ok=True)
        (target / "renders").mkdir(exist_ok=True)
        new_voice = target / "assets" / f"voice-{uuid.uuid4().hex[:8]}{voice.suffix.lower()}"
        shutil.copy2(voice, new_voice)
        project = read_json(target / "project.json")
        project["voice"] = str(new_voice.relative_to(target)).replace("\\", "/")
        write_json(target / "project.json", project)
        if args.words:
            import_words(target, Path(args.words).expanduser().resolve())
        else:
            transcribe(target, args.model, args.language)
        board = build_storyboard(target)
        if len(board["scenes"]) != len(old_board["scenes"]):
            raise ProjectError("retimed scene count differs; review the new storyboard before copying scene choices")
        for new, old in zip(board["scenes"], old_board["scenes"]):
            for key in ("headline", "pose", "asset", "visual_label"):
                if key in old:
                    new[key] = old[key]
            old_duration = float(old["end"]) - float(old["start"])
            new_duration = float(new["end"]) - float(new["start"])
            if old_duration > 0:
                new["visual_cues"] = [{
                    **cue,
                    "start": float(new["start"]) + (float(cue["start"]) - float(old["start"])) / old_duration * new_duration,
                    "duration": float(cue["duration"]) / old_duration * new_duration,
                } for cue in old.get("visual_cues", [])]
        validate_storyboard(target, board)
        write_json(target / "storyboard.json", board)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    print(f"retimed project created: {target}; review and approve the new storyboard")


def attach_avatar(args) -> None:
    from .avatar import copy_pack, validate_pack

    root = Path(args.project).resolve()
    source = Path(args.pack).expanduser().resolve()
    if not source.is_dir():
        raise ProjectError(f"avatar pack not found: {source}")
    target = root / "assets" / "avatar"
    if target.exists():
        raise ProjectError(f"avatar pack already exists: {target}")
    copy_pack(source, target)
    try:
        validate_pack(root, "assets/avatar")
    except Exception:
        shutil.rmtree(target)
        raise
    project = read_json(root / "project.json")
    project["avatar_pack"] = "assets/avatar"
    write_json(root / "project.json", project)
    print(f"avatar attached: {target}")


def approve(args) -> None:
    from .timing import storyboard_hash, validate_storyboard

    root = Path(args.project).resolve()
    board = read_json(root / "storyboard.json")
    if not isinstance(board.get("source"), dict):
        board["source"] = {}
    board["source"]["words_sha256"] = file_hash(root / "words.json")
    validate_storyboard(root, board)
    board["approved"] = True
    board["approval_hash"] = storyboard_hash(board)
    write_json(root / "storyboard.json", board)
    print(f"storyboard approved: {root / 'storyboard.json'}")


def synthesize(args) -> None:
    import urllib.error
    import urllib.request

    root = Path(args.project).resolve()
    project = read_json(root / "project.json")
    profile = load_profile()
    if profile["voice_route"] != "elevenlabs":
        raise ProjectError("profile voice route is recording; run setup again to choose ElevenLabs")
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise ProjectError("ELEVENLABS_API_KEY is not set in the environment")
    target = project_file(root, project["voice"])
    if target.exists():
        raise ProjectError(f"voice already exists: {target}")
    script = (root / "script.txt").read_text(encoding="utf-8").strip()
    if not script:
        raise ProjectError("script.txt is empty")
    import json
    payload = json.dumps({"text": script, "model_id": "eleven_multilingual_v2"}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{profile['voice_id']}",
        data=payload,
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        raise ProjectError(f"ElevenLabs returned HTTP {exc.code}; check voice ID, account, and API access") from exc
    except urllib.error.URLError as exc:
        raise ProjectError("could not reach ElevenLabs") from exc
    if len(audio) < 1024:
        raise ProjectError("ElevenLabs returned an unexpectedly small audio file")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(audio)
    print(f"narration generated: {target}")


def check(args) -> None:
    import json
    from .timing import validate_storyboard

    root = Path(args.project).resolve()
    project = read_json(root / "project.json")
    voice = project_file(root, project["voice"])
    duration = probe_duration(voice)
    board = read_json(root / "storyboard.json")
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
    print(f"PASS: H.264/AAC {size[0]}x{size[1]}, {actual:.3f}s voice/video, {len(board['scenes'])} scenes")


def render_engine_command(args) -> None:
    from .engine import render_with_engine

    root = Path(args.project).resolve()
    profile = load_profile()
    suffix = "-portrait" if args.portrait else ""
    target = Path(args.output).resolve() if args.output else root / "renders" / f"{'preview' if args.preview else 'final'}{suffix}-engine.mp4"
    print(render_with_engine(root, target, profile, preview=args.preview, portrait=args.portrait))


def transcribe_command(args) -> None:
    from .timing import transcribe

    print(f"{transcribe(Path(args.project).resolve(), args.model, args.language)} words timed")


def import_words_command(args) -> None:
    from .timing import import_words

    print(f"{import_words(Path(args.project).resolve(), Path(args.file).resolve())} words imported")


def storyboard_command(args) -> None:
    from .timing import build_storyboard

    print(f"{len(build_storyboard(Path(args.project).resolve())['scenes'])} scenes planned; review storyboard.json before approval")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="explainer", description="Create voice-timed explainer videos")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="check local tools")
    p.set_defaults(handler=doctor)
    p = sub.add_parser("bootstrap", help="create the managed Studio Python environment")
    p.add_argument("--transcribe", action="store_true", help="also install optional faster-whisper dependencies")
    p.set_defaults(handler=bootstrap)
    p = sub.add_parser("install-engine", help="install or verify AIVEE for this Studio profile")
    p.set_defaults(handler=install_engine)
    p = sub.add_parser("engine", help="run an AIVEE CLI command")
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    p.set_defaults(handler=engine_command)
    p = sub.add_parser("setup", help="save a creator profile")
    p.add_argument("--brand")
    p.add_argument("--language")
    p.add_argument("--voice-route", choices=["recording", "elevenlabs"])
    p.add_argument("--voice-id")
    p.add_argument("--avatar", choices=["emo", "built-in", "custom"])
    p.add_argument("--avatar-pack")
    p.add_argument("--rhubarb-path")
    p.add_argument("--output-dir")
    p.add_argument("--logo")
    p.add_argument("--cta")
    p.add_argument("--background")
    p.add_argument("--ink")
    p.add_argument("--accent")
    p.add_argument("--force", action="store_true")
    p.set_defaults(handler=setup)
    p = sub.add_parser("profile", help="show saved non-secret settings")
    p.set_defaults(handler=lambda a: print(__import__("json").dumps(load_profile(), indent=2)))
    p = sub.add_parser("init", help="create a film project")
    p.add_argument("project")
    p.add_argument("--title")
    p.add_argument("--script")
    p.add_argument("--voice")
    p.set_defaults(handler=init)
    p = sub.add_parser("attach-voice", help="attach a narrated take")
    p.add_argument("project")
    p.add_argument("file")
    p.set_defaults(handler=attach_voice)
    p = sub.add_parser("retime", help="create a new project from a re-recorded take")
    p.add_argument("project")
    p.add_argument("new_project")
    p.add_argument("--voice", required=True)
    p.add_argument("--words")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.set_defaults(handler=retime)
    p = sub.add_parser("attach-avatar", help="attach an avatar sprite pack")
    p.add_argument("project")
    p.add_argument("pack")
    p.set_defaults(handler=attach_avatar)
    p = sub.add_parser("avatar-preview", help="make a contact sheet of avatar poses and mouth shapes")
    p.add_argument("project")
    p.add_argument("--output")
    p.set_defaults(handler=avatar_preview_command)
    p = sub.add_parser("avatar-preview-pack", help="preview a custom pack before setup")
    p.add_argument("pack")
    p.add_argument("--output", required=True)
    p.set_defaults(handler=avatar_preview_pack_command)
    p = sub.add_parser("synthesize", help="generate narration with configured ElevenLabs voice")
    p.add_argument("project")
    p.set_defaults(handler=synthesize)
    p = sub.add_parser("transcribe", help="generate word timing from narration")
    p.add_argument("project")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.set_defaults(handler=transcribe_command)
    p = sub.add_parser("import-words", help="use reviewed word timings from JSON")
    p.add_argument("project")
    p.add_argument("file")
    p.set_defaults(handler=import_words_command)
    p = sub.add_parser("storyboard", help="align script paragraphs to speech")
    p.add_argument("project")
    p.set_defaults(handler=storyboard_command)
    p = sub.add_parser("approve", help="mark a reviewed storyboard approved")
    p.add_argument("project")
    p.set_defaults(handler=approve)
    p = sub.add_parser("render", help="render a preview or final MP4 through the AI Video Editing Engine")
    p.add_argument("project")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--portrait", action="store_true")
    p.add_argument("--output")
    p.set_defaults(handler=render_engine_command)
    p = sub.add_parser("render-engine", help="render through the AI Video Editing Engine")
    p.add_argument("project")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--portrait", action="store_true")
    p.add_argument("--output")
    p.set_defaults(handler=render_engine_command)
    p = sub.add_parser("check", help="validate a rendered video's basic timing")
    p.add_argument("project")
    p.add_argument("video")
    p.set_defaults(handler=check)
    p = sub.add_parser("contact-sheet", help="make a scene review sheet from a rendered video")
    p.add_argument("project")
    p.add_argument("video")
    p.add_argument("--output")
    p.set_defaults(handler=contact_sheet_command)
    p = sub.add_parser("sync-check", help="compare rendered speech timings with source words")
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
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
