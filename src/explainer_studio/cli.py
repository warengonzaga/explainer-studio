"""Command-line interface used by the plugin's chat skills."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .avatar import copy_pack, preview_avatar, preview_pack, validate_pack
from .common import ProjectError, command, probe_duration, project_file, read_json, write_json
from .engine import render_with_engine, resolve_engine_root
from .quality import contact_sheet, sync_check
from .render import render, storyboard_hash
from .timing import build_storyboard, import_words, transcribe, validate_storyboard


def home() -> Path:
    return Path(os.environ.get("EXPLAINER_STUDIO_HOME", Path.home() / ".explainer-studio")).expanduser()


def load_profile() -> dict:
    path = home() / "profile.json"
    if not path.is_file():
        raise ProjectError("profile not set up; run `explainer setup` through the plugin")
    return read_json(path)


def setup(args) -> None:
    target = home() / "profile.json"
    old = read_json(target) if target.is_file() else {}
    if target.exists() and not args.force:
        raise ProjectError(f"profile already exists: {target}; use --force after confirming changes")
    brand = args.brand or old.get("brand")
    if not brand:
        raise ProjectError("brand is required")
    voice_route = args.voice_route or old.get("voice_route") or "recording"
    if voice_route not in {"recording", "elevenlabs"}:
        raise ProjectError("voice route must be recording or elevenlabs")
    voice_id = args.voice_id or old.get("voice_id")
    if voice_route == "elevenlabs" and not voice_id:
        raise ProjectError("ElevenLabs requires --voice-id (API key stays in ELEVENLABS_API_KEY)")
    if voice_id and not re.fullmatch(r"[A-Za-z0-9_-]+", voice_id):
        raise ProjectError("voice ID contains unsupported characters")
    engine_path = args.engine_path or old.get("engine_path")
    if engine_path:
        engine_path = str(resolve_engine_root({"engine_path": engine_path}))
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
        destination = home() / logo
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source != destination:
            shutil.copy2(source, destination)
    avatar = args.avatar or old.get("avatar") or "built-in"
    avatar_pack = old.get("avatar_pack")
    avatar_name = old.get("avatar_name", "Built-in")
    if args.avatar_pack:
        source = Path(args.avatar_pack).expanduser().resolve()
        manifest = validate_pack(source.parent, source.name)
        destination = home() / "assets" / "avatar"
        if source != destination.resolve():
            if destination.exists():
                shutil.rmtree(destination)
            copy_pack(source, destination)
        avatar, avatar_pack = "custom", "assets/avatar"
        avatar_name = manifest.get("name", "Custom")
    elif args.avatar == "built-in":
        avatar_pack = None
        avatar_name = "Built-in"
    if avatar == "custom" and not avatar_pack:
        raise ProjectError("custom avatar requires --avatar-pack")
    profile = {
        "version": 1, "brand": brand, "language": args.language or old.get("language") or "en",
        "voice_route": voice_route, "voice_id": voice_id,
        "avatar": avatar, "avatar_name": avatar_name, "avatar_pack": avatar_pack,
        "engine_path": engine_path,
        "rhubarb_path": str(Path(rhubarb_path).expanduser().resolve()) if rhubarb_path else None,
        "output_dir": str(Path(args.output_dir or old.get("output_dir") or "~/Explainer Studio").expanduser().resolve()),
        "colors": colors, "logo": logo, "cta": args.cta or old.get("cta") or "",
    }
    write_json(target, profile)
    print(f"profile saved: {target}")


def doctor(_) -> None:
    print(f"python: {sys.version.split()[0]}")
    try:
        import PIL
        print(f"pillow: {PIL.__version__}")
    except ImportError:
        print("pillow: MISSING (pip install -e .)")
    for name in ("ffmpeg", "ffprobe"):
        print(f"{name}: {shutil.which(name) or 'MISSING'}")
    try:
        import faster_whisper  # noqa: F401
        print("faster-whisper: available")
    except ImportError:
        print("faster-whisper: optional, needed for automatic word timing")
    path = home() / "profile.json"
    print(f"profile: {path if path.is_file() else 'not set up'}")
    try:
        engine_root = resolve_engine_root(read_json(path) if path.is_file() else {})
        print(f"engine: {engine_root}")
    except ProjectError as exc:
        print(f"engine: MISSING ({exc})")
    profile = read_json(path) if path.is_file() else {}
    rhubarb = os.environ.get("RHUBARB_PATH") or profile.get("rhubarb_path") or shutil.which("rhubarb")
    if rhubarb and not Path(rhubarb).expanduser().is_file():
        rhubarb = shutil.which(rhubarb)
    print(f"rhubarb: {Path(rhubarb).expanduser().resolve() if rhubarb else 'optional; amplitude lip sync will be used'}")


def init(args) -> None:
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
        source = home() / profile["logo"]
        if source.is_file():
            project["logo"] = "assets/" + source.name
            shutil.copy2(source, root / project["logo"])
    if profile.get("avatar_pack"):
        source = home() / profile["avatar_pack"]
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
    source = Path(args.project).expanduser().resolve()
    target = Path(args.new_project).expanduser().resolve()
    if target.exists():
        raise ProjectError(f"retimed project already exists: {target}")
    voice = Path(args.voice).expanduser().resolve()
    if not voice.is_file():
        raise ProjectError(f"new voice file not found: {voice}")
    old_board = read_json(source / "storyboard.json")
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("renders", ".work", "voice.mp3", "voice.wav", "voice.m4a", "voice.flac", "words.json", "storyboard.json"))
    (target / "renders").mkdir(exist_ok=True)
    new_voice = target / "assets" / f"voice{voice.suffix.lower()}"
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
    write_json(target / "storyboard.json", board)
    print(f"retimed project created: {target}; review and approve the new storyboard")


def attach_avatar(args) -> None:
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
    root = Path(args.project).resolve()
    board = read_json(root / "storyboard.json")
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


def render_command(args) -> None:
    root = Path(args.project).resolve()
    name = ("preview" if args.preview else "final") + ("-portrait" if args.portrait else "") + "-legacy.mp4"
    target = Path(args.output).resolve() if args.output else root / "renders" / name
    print(render(root, target, preview=args.preview, portrait=args.portrait))


def render_engine_command(args) -> None:
    root = Path(args.project).resolve()
    profile = load_profile()
    suffix = "-portrait" if args.portrait else ""
    target = Path(args.output).resolve() if args.output else root / "renders" / f"{'preview' if args.preview else 'final'}{suffix}-engine.mp4"
    print(render_with_engine(root, target, profile, preview=args.preview, portrait=args.portrait))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="explainer", description="Create voice-timed explainer videos")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="check local tools")
    p.set_defaults(handler=doctor)
    p = sub.add_parser("setup", help="save a creator profile")
    p.add_argument("--brand")
    p.add_argument("--language")
    p.add_argument("--voice-route", choices=["recording", "elevenlabs"])
    p.add_argument("--voice-id")
    p.add_argument("--avatar", choices=["built-in", "custom"])
    p.add_argument("--avatar-pack")
    p.add_argument("--engine-path")
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
    p.set_defaults(handler=lambda a: print(preview_avatar(Path(a.project).resolve(), Path(a.output).resolve() if a.output else Path(a.project).resolve() / "renders" / "avatar-preview.png")))
    p = sub.add_parser("avatar-preview-pack", help="preview a custom pack before setup")
    p.add_argument("pack")
    p.add_argument("--output", required=True)
    p.set_defaults(handler=lambda a: print(preview_pack(Path(a.pack).resolve(), Path(a.output).resolve())))
    p = sub.add_parser("synthesize", help="generate narration with configured ElevenLabs voice")
    p.add_argument("project")
    p.set_defaults(handler=synthesize)
    p = sub.add_parser("transcribe", help="generate word timing from narration")
    p.add_argument("project")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.set_defaults(handler=lambda a: print(f"{transcribe(Path(a.project).resolve(), a.model, a.language)} words timed"))
    p = sub.add_parser("import-words", help="use reviewed word timings from JSON")
    p.add_argument("project")
    p.add_argument("file")
    p.set_defaults(handler=lambda a: print(f"{import_words(Path(a.project).resolve(), Path(a.file).resolve())} words imported"))
    p = sub.add_parser("storyboard", help="align script paragraphs to speech")
    p.add_argument("project")
    p.set_defaults(handler=lambda a: print(f"{len(build_storyboard(Path(a.project).resolve())['scenes'])} scenes planned; review storyboard.json before approval"))
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
    p = sub.add_parser("render-legacy", help="render with the comparison-only Studio compositor")
    p.add_argument("project")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--portrait", action="store_true")
    p.add_argument("--output")
    p.set_defaults(handler=render_command)
    p = sub.add_parser("check", help="validate a rendered video's basic timing")
    p.add_argument("project")
    p.add_argument("video")
    p.set_defaults(handler=check)
    p = sub.add_parser("contact-sheet", help="make a scene review sheet from a rendered video")
    p.add_argument("project")
    p.add_argument("video")
    p.add_argument("--output")
    p.set_defaults(handler=lambda a: print(contact_sheet(Path(a.project).resolve(), Path(a.video).resolve(), Path(a.output).resolve() if a.output else Path(a.project).resolve() / "renders" / "contact-sheet.jpg")))
    p = sub.add_parser("sync-check", help="compare rendered speech timings with source words")
    p.add_argument("project")
    p.add_argument("video")
    p.add_argument("--render-words")
    p.add_argument("--model", default="small")
    p.add_argument("--language")
    p.set_defaults(handler=lambda a: print(sync_check(Path(a.project).resolve(), Path(a.video).resolve(), a.model, a.language, Path(a.render_words).resolve() if a.render_words else None)))
    args = parser.parse_args(argv)
    try:
        args.handler(args)
        return 0
    except (ProjectError, OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
