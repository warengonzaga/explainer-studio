"""Speech timing and storyboard generation."""

from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from pathlib import Path

from .common import ProjectError, file_hash, probe_duration, project_file, read_json, write_json


def tokens(text: str) -> list[str]:
    return [x.casefold() for x in re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text, re.UNICODE)]


def validate_words(words: list[dict], duration: float) -> None:
    if not isinstance(words, list) or not words:
        raise ProjectError("word timings must be a nonempty JSON array")
    previous = -1.0
    for index, word in enumerate(words):
        try:
            start, end = float(word["start"]), float(word["end"])
            value = word["text"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"invalid word at index {index}") from exc
        if not isinstance(value, str) or not tokens(value) or start < previous or end <= start or end > duration + 0.25:
            raise ProjectError(f"invalid timing or text at word {index}")
        previous = start


def transcribe(root: Path, model_name: str = "small", language: str | None = None) -> int:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ProjectError("transcription needs the optional package: pip install -e '.[transcribe]'") from exc
    project = read_json(root / "project.json")
    voice = project_file(root, project["voice"])
    if not voice.is_file():
        raise ProjectError(f"missing voice recording: {voice}")
    duration = probe_duration(voice)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(voice), language=language, word_timestamps=True, vad_filter=True)
    words = []
    for segment in segments:
        for word in segment.words or []:
            if tokens(word.word):
                start = round(word.start, 3)
                end = max(round(word.end, 3), start + 0.02)
                words.append({"text": word.word.strip(), "start": start, "end": end})
    validate_words(words, duration)
    write_json(root / "words.json", words)
    return len(words)


def import_words(root: Path, source: Path) -> int:
    project = read_json(root / "project.json")
    voice = project_file(root, project["voice"])
    words = read_json(source)
    validate_words(words, probe_duration(voice))
    write_json(root / "words.json", words)
    return len(words)


def build_storyboard(root: Path) -> dict:
    project = read_json(root / "project.json")
    voice = project_file(root, project["voice"])
    duration = probe_duration(voice)
    words = read_json(root / "words.json")
    validate_words(words, duration)
    paragraphs = [p.strip().replace("\n", " ") for p in re.split(r"\n\s*\n", (root / "script.txt").read_text(encoding="utf-8")) if p.strip()]
    if not paragraphs:
        raise ProjectError("script.txt needs at least one paragraph")
    script_words = [w for p in paragraphs for w in tokens(p)]
    spoken = [tokens(w["text"])[0] for w in words]
    mapping = {}
    matcher = SequenceMatcher(None, script_words, spoken, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    coverage = len(mapping) / len(script_words)
    if coverage < 0.75:
        raise ProjectError(f"script and recording differ too much ({coverage:.0%} word match); correct either before planning")
    scenes = []
    cursor = 0
    positions = []
    for paragraph in paragraphs:
        count = len(tokens(paragraph))
        matched = [mapping[i] for i in range(cursor, cursor + count) if i in mapping]
        if not matched:
            raise ProjectError(f"no spoken words matched paragraph {len(scenes) + 1}")
        positions.append((matched[0], matched[-1]))
        cursor += count
    boundaries = [0.0]
    for (_, left_last), (right_first, _) in zip(positions, positions[1:]):
        left = words[left_last]["end"]
        right = words[right_first]["start"]
        boundaries.append(round((left + right) / 2, 3))
    boundaries.append(round(duration, 3))
    for index, paragraph in enumerate(paragraphs):
        headline = " ".join(paragraph.split()[:7]).rstrip(".,;:!?—-")
        scenes.append({
            "start": boundaries[index], "end": boundaries[index + 1],
            "headline": headline, "body": paragraph,
            "pose": ["idle", "present", "point", "celebrate"][index % 4],
            "emphasis": paragraph.split()[0].strip(".,;:!?—-"),
            "emphasis_at": round(float(words[positions[index][0]]["start"]), 3),
            "asset": None,
        })
    board = {
        "version": 1, "approved": False, "scenes": scenes,
        "source": {"script_sha256": file_hash(root / "script.txt"), "voice_sha256": file_hash(voice)},
    }
    validate_storyboard(root, board, duration)
    write_json(root / "storyboard.json", board)
    return board


def validate_storyboard(root: Path, board: dict, duration: float | None = None) -> None:
    if not isinstance(board, dict) or board.get("version") != 1 or not isinstance(board.get("scenes"), list) or not board["scenes"]:
        raise ProjectError("storyboard.json needs version 1 and a nonempty scenes array")
    project = read_json(root / "project.json")
    voice = project_file(root, project["voice"])
    if duration is None:
        duration = probe_duration(voice)
    source = board.get("source")
    if not isinstance(source, dict) or source.get("script_sha256") != file_hash(root / "script.txt") or source.get("voice_sha256") != file_hash(voice):
        raise ProjectError("script or narration changed after storyboarding; run storyboard again")
    previous = 0.0
    for index, scene in enumerate(board["scenes"]):
        try:
            start, end = float(scene["start"]), float(scene["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"scene {index + 1} needs numeric start and end") from exc
        if abs(start - previous) > 0.02 or end <= start or end > duration + 0.05:
            raise ProjectError(f"scene {index + 1} has a gap, overlap, or invalid duration")
        if not isinstance(scene.get("headline"), str) or not scene["headline"].strip():
            raise ProjectError(f"scene {index + 1} needs a headline")
        if scene.get("asset") is not None:
            asset = project_file(root, scene["asset"])
            if not asset.is_file():
                raise ProjectError(f"scene {index + 1} asset not found: {asset}")
        cues = scene.get("visual_cues", [])
        if not isinstance(cues, list):
            raise ProjectError(f"scene {index + 1} visual_cues must be an array")
        for cue_index, cue in enumerate(cues):
            if not isinstance(cue, dict):
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} must be an object")
            asset_name = cue.get("asset")
            if not isinstance(asset_name, str) or not project_file(root, asset_name).is_file():
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} asset not found")
            try:
                cue_start, cue_duration = float(cue["start"]), float(cue["duration"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} needs start and duration") from exc
            if (not math.isfinite(cue_start) or not math.isfinite(cue_duration)
                    or cue_start < start or cue_duration < 0.8 or cue_start + cue_duration > end + 1e-6):
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} is outside its scene or too short")
            for field in ("x", "y", "width", "height"):
                value = cue.get(field)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                    raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} {field} must be numeric")
            x, y = float(cue.get("x", 0.5)), float(cue.get("y", 0.55))
            width, height = float(cue.get("width", 0.38)), float(cue.get("height", 0.2))
            if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
                raise ProjectError(f"scene {index + 1} visual cue {cue_index + 1} must fit inside the frame")
        if scene.get("emphasis_at") is not None:
            cue = float(scene["emphasis_at"])
            if cue < start or cue >= end:
                raise ProjectError(f"scene {index + 1} emphasis cue is outside its time window")
        previous = end
    if abs(previous - duration) > 0.1:
        raise ProjectError(f"storyboard ends at {previous:.2f}s, voice ends at {duration:.2f}s")
