"""Sound-effect packs, timeline cues, and the optional AIVEE mix."""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import struct
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from .common import ProjectError, read_json, studio_data, studio_file, write_json
from .engine import _engine_cli, resolve_aivee


SFX_AIVEE_VERSION = (0, 3, 0)
DEFAULT_PACK_ID = "default-tones"
SAMPLE_RATE = 44100
MAX_AUDIO_BYTES = 8_000_000
OPENVERSE_AUDIO_URL = "https://api.openverse.org/v1/audio/"
_CC_LICENSES = {"cc0", "pdm", "by", "by-sa", "by-nc", "by-nd", "by-nc-sa", "by-nc-nd"}
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".aiff"}
_KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PACK_FIELDS = {"format_version", "id", "name", "version", "creator", "license", "license_file", "attribution", "roles"}
_ROLE_FIELDS = {
    "file", "license", "license_url", "license_version", "attribution", "creator",
    "creator_url", "source", "source_id", "title", "landing_url", "query",
}
_CUE_FIELDS = {"role", "file", "at", "gainDb", "fadeInMs", "fadeOutMs", "event", "label"}
_GENERATED_TRACKS = {
    "studio-visuals", "studio-avatar", "studio-voice", "studio-music", "studio-brand",
    "studio-scene-headings", "studio-draft", "studio-custom-scenes", "captions",
}
_SKIPPED_TRACKS = {"studio-avatar", "studio-voice", "studio-music", "studio-draft"}
_REVEAL_CALL = re.compile(r"""\breveal\(\s*(['"])(?P<selector>.+?)\1\s*,\s*(?P<time>\d*\.?\d+)\s*\)""")
_TIMELINE_CALL = re.compile(
    r"""timeline\.(?P<method>fromTo|from|to|set)\(\s*(['"])(?P<selector>.+?)\2(?P<body>.*?)\)\s*;""",
    re.DOTALL,
)
_POSITION = re.compile(r""",\s*(?:at\(\s*(\d*\.?\d+)\s*\)|(\d*\.?\d+))\s*$""", re.DOTALL)
_AT_FRACTION = re.compile(r"""\bat\s*=\s*(?:\([^)]*\)|[A-Za-z_][\w]*)\s*=>\s*[^;{]*\bduration\s*\*""")

DEFAULT_EVENTS = {
    "scene-change": "whoosh",
    "transition": "whoosh",
    "element": "pop",
    "badge": "pop",
    "step": "pop",
    "click": "click",
    "typing": "click",
}
DEFAULT_GAIN_DB = {"whoosh": -12, "pop": -10, "click": -16, "ding": -12}
DEFAULT_FADE_IN_MS = {"whoosh": 12, "pop": 0, "click": 0, "ding": 0}
DEFAULT_FADE_OUT_MS = {"whoosh": 60, "pop": 30, "click": 8, "ding": 90}
_ROLES = ("whoosh", "pop", "click", "ding")


def parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(version).split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    if not parts:
        raise ProjectError(f"invalid AIVEE version: {version}")
    return tuple(parts)


def version_at_least(version: str, minimum: tuple[int, ...] = SFX_AIVEE_VERSION) -> bool:
    try:
        current = parse_version(version)
    except ProjectError:
        return False
    width = max(len(current), len(minimum))
    padded = current + (0,) * (width - len(current))
    target = minimum + (0,) * (width - len(minimum))
    return padded >= target


def sfx_doctor_status(version: str | None) -> dict:
    """Doctor line for sound-effect mixing. Older than 0.3.0 stays a hint, not a failed check."""
    available = bool(version) and version_at_least(version)
    if available:
        line = f"sfx: available (AIVEE {version})"
    elif version:
        line = f"sfx: needs AIVEE 0.3.0 or later (installed {version})"
    else:
        line = "sfx: needs AIVEE 0.3.0 or later"
    return {"available": available, "version": version, "line": line}


def require_sfx_aivee() -> tuple[list[str], str]:
    command, package_root = resolve_aivee()
    manifest = read_json(Path(package_root) / "package.json")
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version_at_least(version):
        found = version if isinstance(version, str) else "unknown"
        raise ProjectError(f"{sfx_doctor_status(found)['line']}; run `explainer doctor`")
    return command, package_root


def sound_library(profile: dict) -> Path:
    """Sound packs sit beside avatar packs in the AIVEE Explainer library."""
    workspace = profile.get("aivee_workspace") if isinstance(profile, dict) else None
    if not isinstance(workspace, dict):
        raise ProjectError("creator profile has no AIVEE library; run `explainer setup`")
    avatar_packs = workspace.get("avatarPacks")
    if isinstance(avatar_packs, str) and avatar_packs.strip():
        return Path(avatar_packs).expanduser().resolve().parent / "Sound Packs"
    library = workspace.get("library")
    if isinstance(library, str) and library.strip():
        return Path(library).expanduser().resolve() / "Sound Packs"
    raise ProjectError("creator profile has no AIVEE library; run `explainer setup`")


def install_default_pack(library: Path) -> Path:
    """Write the synthesized default pack. Leave an existing pack untouched."""
    target = library / DEFAULT_PACK_ID
    if target.exists():
        validate_pack(target)
        return target
    library.mkdir(parents=True, exist_ok=True)
    stage = library / f".{DEFAULT_PACK_ID}.stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    try:
        for role in _ROLES:
            _write_wav(stage / f"{role}.wav", _synthesize(role))
        write_json(stage / "manifest.json", _default_manifest())
        (stage / "README.md").write_text(_DEFAULT_README, encoding="utf-8")
        (stage / "LICENSE").write_text(_DEFAULT_LICENSE, encoding="utf-8")
        validate_pack(stage)
        stage.rename(target)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return target


def validate_pack(pack: Path) -> dict:
    pack = pack.resolve()
    manifest_path = pack / "manifest.json"
    if not pack.is_dir():
        raise ProjectError(f"sound pack not found: {pack}")
    if manifest_path.is_symlink():
        raise ProjectError("sound pack manifest must not be a symlink")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ProjectError("sound pack manifest must be an object")
    unknown = sorted(set(manifest) - _PACK_FIELDS)
    if unknown:
        raise ProjectError(f"sound pack manifest has unknown fields: {', '.join(unknown)}")
    if manifest.get("format_version") != 1:
        raise ProjectError("sound pack manifest needs format_version 1")
    for field in ("id", "name", "version", "creator", "license"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProjectError(f"sound pack manifest needs {field}")
    if not _KEY.fullmatch(manifest["id"]):
        raise ProjectError("sound pack id must use lowercase letters, digits, and hyphens")
    _optional_text(manifest, "attribution", "sound pack attribution")
    license_file = manifest.get("license_file")
    if license_file is not None:
        _pack_file(pack, license_file, "license file")
    readme = pack / "README.md"
    if readme.is_symlink() or not readme.is_file():
        raise ProjectError("sound pack is missing README.md")
    roles = manifest.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise ProjectError("sound pack manifest needs a roles object")
    for role, entry in roles.items():
        if not isinstance(role, str) or not _KEY.fullmatch(role):
            raise ProjectError(f"invalid sound pack role: {role}")
        if not isinstance(entry, dict):
            raise ProjectError(f"sound pack role {role} must be an object")
        extra = sorted(set(entry) - _ROLE_FIELDS)
        if extra:
            raise ProjectError(f"sound pack role {role} has unknown fields: {', '.join(extra)}")
        _pack_file(pack, entry.get("file"), f"role {role} file", audio=True)
        for field in ("license", "license_url", "license_version", "attribution", "creator", "creator_url", "source", "source_id", "title", "landing_url", "query"):
            if field in entry:
                _optional_text(entry, field, f"role {role} {field}", required=True)
    return manifest


def resolve_pack(spec: str | None, profile: dict | None, *, install_default: bool = False) -> Path:
    if spec is not None and not isinstance(spec, str):
        raise ProjectError("sound pack must be an id or folder")
    if isinstance(spec, str) and spec.strip():
        candidate = Path(spec).expanduser()
        if candidate.is_absolute() or candidate.parts[:1] == ("..",) or len(candidate.parts) > 1:
            pack = candidate.resolve()
            validate_pack(pack)
            return pack
        if not _KEY.fullmatch(spec):
            raise ProjectError("sound pack id must use lowercase letters, digits, and hyphens")
        pack_id = spec
    else:
        pack_id = DEFAULT_PACK_ID
    if profile is None:
        raise ProjectError("creator profile has no AIVEE library; run `explainer setup`")
    library = sound_library(profile)
    if pack_id == DEFAULT_PACK_ID and install_default:
        return install_default_pack(library)
    pack = library / pack_id
    if not pack.is_dir():
        raise ProjectError(f"sound pack not found: {pack}")
    validate_pack(pack)
    return pack


def load_mapping(path: Path | None = None, project_mapping: dict | None = None) -> dict:
    mapping = {
        "events": dict(DEFAULT_EVENTS),
        "gainDb": dict(DEFAULT_GAIN_DB),
        "fadeInMs": dict(DEFAULT_FADE_IN_MS),
        "fadeOutMs": dict(DEFAULT_FADE_OUT_MS),
    }
    for source, label in ((project_mapping, "project sfx mapping"),):
        _merge_mapping(mapping, source, label)
    if path is not None:
        _merge_mapping(mapping, read_json(path), f"mapping file {path}")
    return mapping


def project_sfx_settings(root: Path) -> dict:
    path = studio_file(root, "project.json")
    if not path.is_file():
        return {}
    project = read_json(path)
    if not isinstance(project, dict):
        raise ProjectError("project.json must be an object")
    settings = project.get("sfx", {})
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise ProjectError("project sfx settings must be an object")
    return settings


def derive_cues(root: Path, pack: Path, mapping: dict | None = None) -> dict:
    root = root.resolve()
    pack = pack.resolve()
    manifest = validate_pack(pack)
    mapping = mapping or load_mapping()
    board = _read_optional(studio_file(root, "storyboard.json"))
    timeline = _read_optional(root / "timeline.json")
    if board is None and timeline is None:
        raise ProjectError("generate a storyboard before sound-effect cues")
    duration = _timeline_duration(board, timeline)
    events = []
    if isinstance(board, dict):
        events.extend(_storyboard_events(root, board))
    if isinstance(timeline, dict):
        events.extend(_timeline_events(timeline, storyboard_present=isinstance(board, dict)))
    cues = []
    seen: set[tuple[str, float]] = set()
    for event in sorted(events, key=lambda item: (item["at"], item["event"], item["label"])):
        role = mapping["events"].get(event["event"])
        if not isinstance(role, str) or role not in manifest["roles"]:
            if role is None:
                continue
            raise ProjectError(f"sound pack {manifest['id']} has no role for {event['event']}: {role}")
        at = round(float(event["at"]), 3)
        if at < 0 or at >= duration:
            continue
        key = (role, at)
        if key in seen:
            continue
        seen.add(key)
        cues.append({
            "role": role,
            "file": manifest["roles"][role]["file"],
            "at": at,
            "gainDb": mapping["gainDb"].get(role, 0),
            "fadeInMs": mapping["fadeInMs"].get(role, 0),
            "fadeOutMs": mapping["fadeOutMs"].get(role, 0),
            "event": event["event"],
            "label": event["label"],
        })
    return {"format_version": 1, "pack": manifest["id"], "events": mapping["events"], "cues": cues}


def write_cues(root: Path, document: dict, *, force: bool = False) -> Path:
    path = studio_file(root, "sfx-cues.json")
    if path.exists() and not force:
        raise ProjectError(f"sound-effect cues already exist: {path}; edit that file or pass --force")
    _validate_cue_document(document)
    write_json(path, document)
    return path


def read_cues(root: Path) -> dict:
    path = studio_file(root, "sfx-cues.json")
    if not path.is_file():
        raise ProjectError(f"sound-effect cues are missing: {path}; run `explainer sfx-cues` and review the file before rendering")
    document = read_json(path)
    _validate_cue_document(document)
    return document


def search_openverse(query: str, *, page_size: int = 5, opener=None) -> list[dict]:
    text = _query(query)
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 20:
        raise ProjectError("page size must be an integer from 1 to 20")
    payload = _openverse_json({"q": text, "page_size": str(page_size)}, opener)
    results = payload.get("results")
    if not isinstance(results, list):
        raise ProjectError("Openverse returned an invalid audio result list")
    collected = []
    for item in results:
        normalized = _openverse_item(item)
        if normalized is not None:
            collected.append(normalized)
    return collected


def add_openverse_result(pack: Path, role: str, query: str, *, pick: int = 1, opener=None) -> dict:
    if not isinstance(role, str) or not _KEY.fullmatch(role):
        raise ProjectError("sound pack role must use lowercase letters, digits, and hyphens")
    if isinstance(pick, bool) or not isinstance(pick, int) or pick < 1:
        raise ProjectError("pick must be a positive integer")
    matches = search_openverse(query, page_size=20, opener=opener)
    if pick > len(matches):
        raise ProjectError(f"no Creative Commons audio matched {query!r} at position {pick}")
    chosen = matches[pick - 1]
    manifest = validate_pack(pack)
    audio = _download_audio(chosen["url"], opener)
    extension = chosen["extension"]
    _validate_download(audio, extension)
    filename = f"{role}-{_safe_id(chosen['id'])}{extension}"
    previous = manifest["roles"].get(role, {}).get("file") if isinstance(manifest["roles"].get(role), dict) else None
    target = pack / filename
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ProjectError("refusing to replace a symlink in the sound pack")
    if not target.resolve().is_relative_to(pack.resolve()):
        raise ProjectError("refusing to write a sound file outside the pack")
    target.write_bytes(audio)
    entry = {
        "file": filename,
        "license": chosen["license"],
        "license_version": chosen["license_version"],
        "license_url": chosen["license_url"],
        "attribution": chosen["attribution"],
        "creator": chosen["creator"],
        "creator_url": chosen["creator_url"],
        "source": "openverse",
        "source_id": chosen["id"],
        "title": chosen["title"],
        "landing_url": chosen["landing_url"],
        "query": query.strip(),
    }
    entry = {key: value for key, value in entry.items() if value}
    manifest["roles"][role] = entry
    write_json(pack / "manifest.json", manifest)
    if isinstance(previous, str) and previous != filename:
        old = pack / previous
        still_used = any(item.get("file") == previous for item in manifest["roles"].values() if isinstance(item, dict))
        if not still_used and old.is_file() and not old.is_symlink() and old.resolve().is_relative_to(pack.resolve()):
            old.unlink()
    validate_pack(pack)
    return entry


def sfx_output_path(video: Path) -> Path:
    return video.with_name(f"{video.stem}-sfx{video.suffix}")


def resolve_render_sfx(args, settings: dict) -> dict | None:
    if getattr(args, "sfx", None) is not None:
        enabled = bool(args.sfx)
    else:
        enabled = settings.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ProjectError("project sfx.enabled must be true or false")
    if not enabled:
        return None
    duck = args.duck_under_speech if getattr(args, "duck_under_speech", None) is not None else settings.get("duckUnderSpeech", False)
    gain_cap = args.gain_cap_db if getattr(args, "gain_cap_db", None) is not None else settings.get("gainCapDb")
    pack = args.sfx_pack if getattr(args, "sfx_pack", None) else settings.get("pack")
    options = _mix_options(duck, gain_cap)
    return {"pack": pack, "options": options}


def preflight_sfx(root: Path, profile: dict, pack: str | None = None) -> Path:
    """Fail before a render when the cue list or its audio files are not ready."""
    document = read_cues(root)
    if not document["cues"]:
        raise ProjectError("sound-effect cue list is empty; edit sfx-cues.json or render without sound effects")
    pack_spec = pack or document.get("pack") or DEFAULT_PACK_ID
    pack_path = resolve_pack(pack_spec if isinstance(pack_spec, str) else None, profile)
    for cue in document["cues"]:
        _resolve_cue_file(cue, pack_path, root)
    return pack_path


def apply_sfx(root: Path, video: Path, profile: dict, *, pack: str | None = None, options: dict | None = None, command: list[str] | None = None) -> Path:
    """Mix the edited cue list onto a finished render. The source file stays in place."""
    root = root.resolve()
    video = video.resolve()
    if not video.is_file():
        raise ProjectError(f"rendered video not found: {video}")
    if video.suffix.lower() not in {".mp4", ".m4a", ".wav"}:
        raise ProjectError("sound-effect mix needs an .mp4, .m4a, or .wav render")
    output = sfx_output_path(video)
    if output.exists():
        raise ProjectError(f"output already exists: {output}")
    pack_path = preflight_sfx(root, profile, pack)
    document = read_cues(root)
    if command is None:
        command, _ = require_sfx_aivee()
    mix_options = options or {}
    work = studio_data(root) / ".work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sfx-", dir=work) as temporary:
        staging = Path(temporary)
        aivee_cues = [
            _aivee_cue(cue, staging, pack_path, root, index)
            for index, cue in enumerate(document["cues"], start=1)
        ]
        cue_path = staging / "cues.json"
        write_json(cue_path, aivee_cues)
        arguments = ["sfx", str(video), str(cue_path), str(output)]
        if mix_options:
            options_path = staging / "sfx-options.json"
            write_json(options_path, mix_options)
            arguments.append(str(options_path))
        _engine_cli(command, root, arguments)
    if not output.is_file():
        raise ProjectError(f"AIVEE sfx did not write {output}")
    return output


def _default_manifest() -> dict:
    return {
        "format_version": 1,
        "id": DEFAULT_PACK_ID,
        "name": "Default Tones",
        "version": "1.0.0",
        "creator": "Explainer Studio",
        "license": "CC0-1.0",
        "license_file": "LICENSE",
        "attribution": "Synthesized tones dedicated to the public domain.",
        "roles": {role: {"file": f"{role}.wav"} for role in _ROLES},
    }


def _synthesize(role: str) -> list[float]:
    if role == "whoosh":
        return _whoosh()
    if role == "pop":
        return _tone(0.09, 720, 180, harmonics=1)
    if role == "click":
        return _click()
    if role == "ding":
        return _tone(0.45, 880, 880, harmonics=2)
    raise ProjectError(f"unknown synthesized role: {role}")


def _whoosh() -> list[float]:
    duration = 0.36
    count = int(SAMPLE_RATE * duration)
    state = 0x12345678
    low = 0.0
    samples = []
    for index in range(count):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        noise = ((state >> 16) / 32768.0) - 1.0
        time = index / SAMPLE_RATE
        opening = min(1.0, time / (duration * 0.7))
        coefficient = 0.08 + 0.72 * opening
        low += coefficient * (noise - low)
        samples.append(low * _envelope(time, 0.02, duration) * 0.85)
    return samples


def _tone(duration: float, start_hz: float, end_hz: float, *, harmonics: int) -> list[float]:
    count = int(SAMPLE_RATE * duration)
    samples = []
    for index in range(count):
        time = index / SAMPLE_RATE
        progress = time / duration if duration else 1
        frequency = start_hz + (end_hz - start_hz) * progress
        sample = 0.0
        for harmonic in range(1, harmonics + 1):
            sample += math.sin(2 * math.pi * frequency * harmonic * time) / harmonic
        samples.append(sample * _envelope(time, 0.005, duration) * 0.45)
    return samples


def _click() -> list[float]:
    duration = 0.02
    count = int(SAMPLE_RATE * duration)
    state = 0x4E1C3
    samples = []
    for index in range(count):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        noise = (state / 0x7FFFFFFF) * 2 - 1
        time = index / SAMPLE_RATE
        samples.append(noise * _envelope(time, 0.001, duration) * 0.7)
    return samples


def _envelope(time: float, attack: float, duration: float) -> float:
    if time < attack:
        return time / attack if attack else 1
    remain = max(duration - attack, 1e-6)
    return math.exp(-3 * (time - attack) / remain)


def _write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        frames = b"".join(
            struct.pack("<h", max(-32767, min(32767, int(sample * 32767))))
            for sample in samples
        )
        handle.writeframes(frames)


def _storyboard_events(root: Path, board: dict) -> list[dict]:
    scenes = board.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ProjectError("storyboard.json needs a nonempty scenes array")
    events = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ProjectError(f"scene {index + 1} must be an object")
        start, end = _scene_bounds(scene, index)
        label = f"scene-{index + 1}"
        if _has_transition(scene.get("transition")):
            events.append({"event": "transition", "at": start, "label": label})
        elif index:
            events.append({"event": "scene-change", "at": start, "label": label})
        cues = scene.get("visual_cues", [])
        if not isinstance(cues, list):
            raise ProjectError(f"scene {index + 1} visual_cues must be an array")
        for cue_index, cue in enumerate(cues):
            if not isinstance(cue, dict):
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} must be an object")
            asset = cue.get("asset") if isinstance(cue.get("asset"), str) else ""
            try:
                cue_start = float(cue["start"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} needs a start time") from exc
            if not math.isfinite(cue_start):
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} needs a finite start time")
            events.append({
                "event": _event_kind(asset),
                "at": cue_start,
                "label": f"{label}:{Path(asset).name or cue_index + 1}",
            })
        composition = scene.get("composition")
        if isinstance(composition, str) and composition:
            path = (root / composition).resolve()
            if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
                raise ProjectError(f"scene {index + 1} composition is missing: {composition}")
            events.extend(_composition_events(path.read_text(encoding="utf-8"), start, end - start, label))
    return events


def _composition_events(html_text: str, scene_start: float, scene_duration: float, label: str) -> list[dict]:
    if scene_duration <= 0 or not math.isfinite(scene_duration):
        raise ProjectError(f"{label} duration must be positive")
    fraction = bool(_AT_FRACTION.search(html_text))
    events = []
    for match in _REVEAL_CALL.finditer(html_text):
        events.append(_composition_event(match.group("selector"), "reveal", float(match.group("time")), True, scene_start, scene_duration, label))
    for match in _TIMELINE_CALL.finditer(html_text):
        position = _POSITION.search(match.group("body"))
        if not position:
            continue
        fraction_value, seconds_value = position.group(1), position.group(2)
        if fraction_value is not None:
            moment, uses_fraction = float(fraction_value), fraction
        else:
            moment, uses_fraction = float(seconds_value), False
        method = match.group("method")
        if method in {"to", "set"} and _explicit_kind(match.group("selector")) is None:
            continue
        events.append(_composition_event(match.group("selector"), method, moment, uses_fraction, scene_start, scene_duration, label))
    return events


def _composition_event(selector: str, method: str, moment: float, uses_fraction: bool, scene_start: float, scene_duration: float, label: str) -> dict:
    if not math.isfinite(moment) or moment < 0:
        raise ProjectError(f"{label} has an invalid timeline time")
    offset = moment * scene_duration if uses_fraction else moment
    kind = _explicit_kind(selector)
    if kind is None and method in {"from", "fromTo", "reveal"}:
        kind = "element"
    if kind is None:
        kind = "element"
    return {"event": kind, "at": scene_start + offset, "label": f"{label}:{selector}"}


def _timeline_events(timeline: dict, *, storyboard_present: bool) -> list[dict]:
    tracks = timeline.get("tracks", [])
    if not isinstance(tracks, list):
        raise ProjectError("timeline tracks must be an array")
    events = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_id = str(track.get("id", ""))
        if track.get("kind") == "audio" or track_id in _SKIPPED_TRACKS:
            for clip in _clips(track):
                events.extend(_transition_events(clip))
            continue
        for clip in _clips(track):
            events.extend(_transition_events(clip))
            if storyboard_present and track_id in _GENERATED_TRACKS:
                continue
            start = _clip_start(clip)
            if start is None:
                continue
            identity = " ".join(str(clip.get(field, "")) for field in ("id", "text"))
            kind = _explicit_kind(f"{identity} {track_id}")
            if kind is None:
                continue
            events.append({"event": kind, "at": start, "label": str(clip.get("id") or track_id or "clip")})
    return events


def _transition_events(clip: dict) -> list[dict]:
    events = []
    start = _clip_start(clip)
    if start is None:
        return events
    clip_id = str(clip.get("id") or "clip")
    if isinstance(clip.get("transitionIn"), dict):
        events.append({"event": "transition", "at": start, "label": f"{clip_id}:in"})
    outgoing = clip.get("transitionOut")
    if isinstance(outgoing, dict):
        duration = _finite(clip.get("durationSeconds"), 0)
        length = _finite(outgoing.get("durationSeconds"), 0)
        events.append({"event": "transition", "at": max(start, start + duration - max(0.0, length)), "label": f"{clip_id}:out"})
    return events


def _clips(track: dict) -> list[dict]:
    clips = track.get("clips", [])
    if not isinstance(clips, list):
        raise ProjectError(f"timeline track {track.get('id', '')} clips must be an array")
    return [clip for clip in clips if isinstance(clip, dict)]


def _clip_start(clip: dict) -> float | None:
    if "timelineStart" not in clip:
        return None
    try:
        start = float(clip["timelineStart"])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(start):
        return None
    return start


def _timeline_duration(board, timeline) -> float:
    ends = []
    if isinstance(board, dict) and isinstance(board.get("scenes"), list) and board["scenes"]:
        try:
            ends.append(float(board["scenes"][-1]["end"]))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ProjectError("storyboard scenes need an end time") from exc
    project = timeline.get("project") if isinstance(timeline, dict) else None
    if isinstance(project, dict) and "durationSeconds" in project:
        try:
            ends.append(float(project["durationSeconds"]))
        except (TypeError, ValueError) as exc:
            raise ProjectError("timeline duration must be numeric") from exc
    finite = [value for value in ends if math.isfinite(value) and value > 0]
    if not finite:
        raise ProjectError("could not determine the timeline duration")
    return max(finite)


def _scene_bounds(scene: dict, index: int) -> tuple[float, float]:
    try:
        start, end = float(scene["start"]), float(scene["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectError(f"scene {index + 1} needs numeric start and end") from exc
    if not math.isfinite(start) or not math.isfinite(end) or end <= start or start < 0:
        raise ProjectError(f"scene {index + 1} needs a positive duration")
    return start, end


def _event_kind(*parts: str, default: str = "element") -> str:
    explicit = _explicit_kind(" ".join(parts))
    return explicit if explicit is not None else default


def _explicit_kind(text: str) -> str | None:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    groups = (
        ("typing", {"typewriter", "typing", "keydown", "keystroke", "caret"}),
        ("click", {"click", "cursor", "pointer", "tap"}),
        ("badge", {"badge"}),
        ("step", {"step"}),
    )
    for kind, names in groups:
        if tokens & names:
            return kind
    return None


def _has_transition(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, dict) and bool(value)


def _read_optional(path: Path):
    if not path.is_file() or path.is_symlink():
        return None
    return read_json(path)


def _merge_mapping(mapping: dict, source, label: str) -> None:
    if source is None:
        return
    if not isinstance(source, dict):
        raise ProjectError(f"{label} must be an object")
    if "events" not in source and "gainDb" not in source and set(source).issubset(set(DEFAULT_EVENTS)):
        source = {"events": source}
    unknown = sorted(set(source) - {"events", "gainDb", "fadeInMs", "fadeOutMs"})
    if unknown:
        raise ProjectError(f"{label} has unknown fields: {', '.join(unknown)}")
    events = source.get("events", {})
    if not isinstance(events, dict):
        raise ProjectError(f"{label} events must be an object")
    for event, role in events.items():
        if not isinstance(event, str) or not event.strip() or not isinstance(role, str) or not _KEY.fullmatch(role):
            raise ProjectError(f"{label} must map event names to sound roles")
        mapping["events"][event] = role
    for field, low, high in (("gainDb", -60, 24), ("fadeInMs", 0, 60000), ("fadeOutMs", 0, 60000)):
        values = source.get(field, {})
        if not isinstance(values, dict):
            raise ProjectError(f"{label} {field} must be an object")
        for role, value in values.items():
            if not isinstance(role, str) or not _KEY.fullmatch(role):
                raise ProjectError(f"{label} {field} role is invalid")
            mapping[field][role] = _bounded_number(value, low, high, f"{label} {field}.{role}")


def _validate_cue_document(document: dict) -> None:
    if not isinstance(document, dict):
        raise ProjectError("sound-effect cues must be an object")
    if document.get("format_version") != 1:
        raise ProjectError("sound-effect cues need format_version 1")
    cues = document.get("cues")
    if not isinstance(cues, list):
        raise ProjectError("sound-effect cues need a cues array")
    for index, cue in enumerate(cues, start=1):
        if not isinstance(cue, dict):
            raise ProjectError(f"sound-effect cue {index} must be an object")
        extra = sorted(set(cue) - _CUE_FIELDS)
        if extra:
            raise ProjectError(f"sound-effect cue {index} has unknown fields: {', '.join(extra)}")
        if "at" not in cue:
            raise ProjectError(f"sound-effect cue {index} needs at")
        _validate_at(cue["at"], index)
        if "file" not in cue and "role" not in cue:
            raise ProjectError(f"sound-effect cue {index} needs a file or role")
        if "role" in cue and (not isinstance(cue["role"], str) or not _KEY.fullmatch(cue["role"])):
            raise ProjectError(f"sound-effect cue {index} role is invalid")
        if "file" in cue and (not isinstance(cue["file"], str) or not cue["file"].strip() or Path(cue["file"]).is_absolute()):
            raise ProjectError(f"sound-effect cue {index} file must be a relative path")
        if "gainDb" in cue:
            _bounded_number(cue["gainDb"], -60, 24, f"sound-effect cue {index} gainDb")
        for field in ("fadeInMs", "fadeOutMs"):
            if field in cue:
                _bounded_number(cue[field], 0, 60000, f"sound-effect cue {index} {field}")


def _validate_at(value, index: int) -> None:
    if isinstance(value, bool):
        raise ProjectError(f"sound-effect cue {index} at must be seconds or a frame")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ProjectError(f"sound-effect cue {index} at must be a nonnegative number")
        return
    if not isinstance(value, dict) or sorted(value) not in (["seconds"], ["frame"]):
        raise ProjectError(f"sound-effect cue {index} at must be seconds or an object with seconds or frame")
    if "seconds" in value:
        seconds = value["seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(float(seconds)) or float(seconds) < 0:
            raise ProjectError(f"sound-effect cue {index} seconds must be a nonnegative number")
        return
    frame = value["frame"]
    if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
        raise ProjectError(f"sound-effect cue {index} frame must be a nonnegative integer")


def _aivee_cue(cue: dict, staging: Path, pack: Path, root: Path, index: int) -> dict:
    source = _resolve_cue_file(cue, pack, root)
    filename = f"{index:02d}-{source.name}"
    shutil.copyfile(source, staging / filename)
    item = {"file": filename, "at": cue["at"]}
    for field in ("gainDb", "fadeInMs", "fadeOutMs"):
        if field in cue:
            item[field] = cue[field]
    return item


def _resolve_cue_file(cue: dict, pack: Path, root: Path) -> Path:
    relative = cue.get("file")
    if not isinstance(relative, str) or not relative.strip():
        role = cue.get("role")
        manifest = read_json(pack / "manifest.json")
        entry = manifest.get("roles", {}).get(role) if isinstance(manifest, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ProjectError(f"sound pack has no file for role {role}")
        relative = entry["file"]
    if Path(relative).is_absolute():
        raise ProjectError(f"sound-effect file must be relative: {relative}")
    for base in (pack, root):
        candidate = (base / relative).resolve()
        if candidate.is_relative_to(base.resolve()) and candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise ProjectError(f"sound-effect file not found: {relative}")


def _mix_options(duck, gain_cap) -> dict:
    options = {}
    if isinstance(duck, dict):
        unknown = sorted(set(duck) - {"thresholdDb", "ratio", "attackMs", "releaseMs"})
        if unknown:
            raise ProjectError(f"duckUnderSpeech has unknown fields: {', '.join(unknown)}")
        parsed = {}
        if "thresholdDb" in duck:
            parsed["thresholdDb"] = _bounded_number(duck["thresholdDb"], -60, 0, "duckUnderSpeech.thresholdDb")
        if "ratio" in duck:
            parsed["ratio"] = _bounded_number(duck["ratio"], 1, 20, "duckUnderSpeech.ratio")
        if "attackMs" in duck:
            parsed["attackMs"] = _bounded_number(duck["attackMs"], 0.01, 2000, "duckUnderSpeech.attackMs")
        if "releaseMs" in duck:
            parsed["releaseMs"] = _bounded_number(duck["releaseMs"], 0.01, 9000, "duckUnderSpeech.releaseMs")
        options["duckUnderSpeech"] = parsed or True
    elif duck is True:
        options["duckUnderSpeech"] = True
    elif duck not in (False, None):
        raise ProjectError("duckUnderSpeech must be true or an object")
    if gain_cap is not None:
        options["gainCapDb"] = _bounded_number(gain_cap, -24, 0, "gainCapDb")
    return options


def _bounded_number(value, low: float, high: float, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not low <= float(value) <= high:
        raise ProjectError(f"{label} must be from {low:g} to {high:g}")
    return value


def _optional_text(payload: dict, field: str, label: str, *, required: bool = False) -> None:
    if field not in payload and not required:
        return
    value = payload.get(field)
    if not isinstance(value, str) or (required and not value.strip()):
        raise ProjectError(f"{label} must be text")


def _pack_file(pack: Path, relative, label: str, *, audio: bool = False) -> Path:
    if not isinstance(relative, str) or not relative.strip() or Path(relative).is_absolute():
        raise ProjectError(f"invalid {label}")
    path = (pack / relative).resolve()
    if not path.is_relative_to(pack.resolve()) or path.is_symlink() or not path.is_file():
        raise ProjectError(f"unsafe or missing {label}: {relative}")
    if audio and path.suffix.lower() not in _AUDIO_EXTENSIONS:
        raise ProjectError(f"{label} must be an audio file: {relative}")
    return path


def _query(query: str) -> str:
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
        raise ProjectError("search query must be from 1 to 200 characters")
    return query.strip()


def _openverse_json(params: dict, opener) -> dict:
    url = OPENVERSE_AUDIO_URL + "?" + urllib.parse.urlencode(params)
    try:
        payload = json.loads(_request(url, opener).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectError("Openverse returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProjectError("Openverse returned an invalid response")
    return payload


def _openverse_item(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    raw_license = item.get("license")
    if not isinstance(raw_license, str):
        return None
    code = raw_license.strip().lower().removeprefix("cc-")
    if code not in _CC_LICENSES:
        return None
    url = item.get("url")
    identifier = item.get("id")
    if not isinstance(url, str) or not url.startswith("https://") or not isinstance(identifier, str) or not identifier.strip():
        return None
    extension = _audio_extension(item.get("filetype"), url)
    if extension is None:
        return None
    version = item.get("license_version") if isinstance(item.get("license_version"), str) else ""
    return {
        "id": identifier.strip(),
        "title": _text(item.get("title"), "Audio"),
        "url": url,
        "extension": extension,
        "license": _spdx(code, version),
        "license_version": version,
        "license_url": _text(item.get("license_url"), ""),
        "attribution": _attribution(item, code, version),
        "creator": _text(item.get("creator"), ""),
        "creator_url": _text(item.get("creator_url"), ""),
        "landing_url": _text(item.get("foreign_landing_url"), ""),
    }


def _attribution(item: dict, code: str, version: str) -> str:
    supplied = item.get("attribution")
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip()
    title = _text(item.get("title"), "Audio")
    creator = _text(item.get("creator"), "the creator")
    landing = _text(item.get("foreign_landing_url"), "")
    credit = f"{title} by {creator}. {_spdx(code, version)}"
    return f"{credit}. {landing}" if landing else credit


def _spdx(code: str, version: str) -> str:
    names = {
        "cc0": "CC0-1.0",
        "pdm": "PDM",
        "by": "CC-BY",
        "by-sa": "CC-BY-SA",
        "by-nc": "CC-BY-NC",
        "by-nd": "CC-BY-ND",
        "by-nc-sa": "CC-BY-NC-SA",
        "by-nc-nd": "CC-BY-NC-ND",
    }
    name = names[code]
    if code in {"cc0", "pdm"} or not version:
        return name
    return f"{name}-{version}"


def _audio_extension(filetype, url: str) -> str | None:
    if isinstance(filetype, str) and filetype.strip():
        extension = "." + filetype.strip().lower().lstrip(".")
        return extension if extension in _AUDIO_EXTENSIONS else None
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in _AUDIO_EXTENSIONS else None


class _HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).startswith("https://"):
            raise ProjectError("Openverse audio URL redirected off https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_open(request, timeout):
    return urllib.request.build_opener(_HttpsRedirect).open(request, timeout=timeout)


def _validate_download(audio: bytes, extension: str) -> None:
    if extension != ".wav":
        return
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            if handle.getnframes() <= 0:
                raise ProjectError("Openverse audio has no samples")
    except (wave.Error, EOFError) as exc:
        raise ProjectError("Openverse download was not a WAV file") from exc


def _download_audio(url: str, opener) -> bytes:
    if not url.startswith("https://"):
        raise ProjectError("Openverse audio URL must use https")
    body = _request(url, opener)
    if len(body) < 16:
        raise ProjectError("Openverse audio download was empty")
    return body


def _request(url: str, opener) -> bytes:
    accept = "application/json" if url.startswith(OPENVERSE_AUDIO_URL) else "*/*"
    request = urllib.request.Request(url, headers={"User-Agent": "explainer-studio", "Accept": accept})
    open_url = opener or _default_open
    try:
        response = open_url(request, timeout=30)
        if hasattr(response, "__enter__"):
            with response as handle:
                return _read_limited(handle)
        return _read_limited(response)
    except ProjectError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProjectError(f"Openverse request failed: {exc}") from exc


def _read_limited(handle) -> bytes:
    chunks = []
    total = 0
    while True:
        block = handle.read(64 * 1024)
        if not block:
            break
        total += len(block)
        if total > MAX_AUDIO_BYTES:
            raise ProjectError("Openverse audio exceeds the download limit")
        chunks.append(block)
    return b"".join(chunks)


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (cleaned or "audio")[:80]


def _text(value, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _finite(value, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


_DEFAULT_README = """# Default Tones

Short synthesized tones for whoosh, pop, click, and ding cues. The files are generated by Explainer Studio and contain no third-party recording.

## License

These tones are dedicated to the public domain under CC0-1.0. See `LICENSE`.

## Roles

`manifest.json` maps `whoosh`, `pop`, `click`, and `ding` to the WAV files in this folder. Replace a role's file to use a different recording, and keep that recording's license and attribution on the role.
"""

_DEFAULT_LICENSE = """Creative Commons Zero 1.0 Universal

The synthesized tones in this pack are dedicated to the public domain. You can copy, modify, and share them for any purpose.
"""

