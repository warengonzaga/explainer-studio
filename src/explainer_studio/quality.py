"""Review artifacts and timing checks for rendered films."""

from __future__ import annotations

import io
import json
import math
import os
import statistics
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageDraw

from .common import ProjectError, command, project_file, read_json, studio_file, write_json
from .timing import tokens


_FLICKER_MEAN_CHANGE = 0.20
# shortcut: flags isolated A-B-A changes; add temporal scoring if multi-frame flicker must be detected.
_FLICKER_LOCAL_CHANGE = 0.01
_FLICKER_BASELINE_CHANGE = 0.08
_FLICKER_BASELINE_LOCAL_CHANGE = 0.005


def frame_diff(left: bytes, right: bytes) -> float:
    if len(left) != len(right):
        raise ValueError("frame sizes must match")
    return sum(abs(a - b) for a, b in zip(left, right)) / (len(left) * 255) if left else 0.0


def frame_change(left: bytes, right: bytes) -> tuple[float, float]:
    if len(left) != len(right):
        raise ValueError("frame sizes must match")
    changes = [abs(a - b) for a, b in zip(left, right)]
    return (
        sum(changes) / (len(changes) * 255) if changes else 0.0,
        sum(change >= 64 for change in changes) / len(changes) if changes else 0.0,
    )


def flicker_check(video: Path) -> dict:
    """Find one-frame A-B-A flashes in every decoded frame at thumbnail size."""
    proc = subprocess.Popen(
        [command("ffmpeg"), "-v", "error", "-i", str(video), "-map", "0:v:0", "-vf", "scale=96:96:flags=area,format=gray", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    frame_size = 96 * 96
    scanned = 0
    findings = []
    finding_count = 0
    try:
        assert proc.stdout is not None
        def read_frame() -> bytes | None:
            raw = proc.stdout.read(frame_size)
            if raw and len(raw) != frame_size:
                raise ProjectError("could not decode every frame for flicker check")
            return raw or None

        previous, current = read_frame(), read_frame()
        scanned = int(previous is not None) + int(current is not None)
        while previous is not None and current is not None:
            following = read_frame()
            if following is None:
                break
            scanned += 1
            before, before_local = frame_change(previous, current)
            after, after_local = frame_change(current, following)
            baseline, baseline_local = frame_change(previous, following)
            before_flash = before >= _FLICKER_MEAN_CHANGE or before_local >= _FLICKER_LOCAL_CHANGE
            after_flash = after >= _FLICKER_MEAN_CHANGE or after_local >= _FLICKER_LOCAL_CHANGE
            stable_neighbors = baseline <= _FLICKER_BASELINE_CHANGE and baseline_local <= _FLICKER_BASELINE_LOCAL_CHANGE
            if before_flash and after_flash and stable_neighbors:
                finding_count += 1
                if len(findings) < 20:
                    findings.append({
                        "frame": scanned - 2,
                        "before_change": round(before, 3),
                        "after_change": round(after, 3),
                        "baseline_change": round(baseline, 3),
                        "changed_pixels_percent": round(max(before_local, after_local) * 100, 2),
                    })
            previous, current = current, following
        if scanned < 2:
            raise ProjectError("video contains too few frames for flicker check")
        if proc.wait() != 0:
            raise ProjectError("could not decode video frames for flicker check")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return {"frames_scanned": scanned, "finding_count": finding_count, "findings": findings, "pass": finding_count == 0}


def safe_zone_check(root: Path, project: dict, board: dict) -> dict:
    """Sample custom portrait compositions in Chromium and check visible content bounds."""
    from .engine import _browser_env, resolve_aivee

    compositions = [
        {"path": str(project_file(root, scene["composition"])), "scene": index + 1,
         "duration": float(scene["end"]) - float(scene["start"])}
        for index, scene in enumerate(board["scenes"]) if scene.get("composition")
    ]
    if not compositions:
        return {"applicable": False, "compositions": 0, "findings": [], "pass": True}
    width, height = int(project.get("width", 1920)), int(project.get("height", 1080))
    if width >= height:
        return {"applicable": False, "compositions": len(compositions), "findings": [], "pass": True}

    engine_command, package_root = resolve_aivee()
    node = engine_command[0]
    runner = Path(__file__).resolve().parents[2] / "scripts" / "safe_check.mjs"
    manifest = {"compositions": compositions, "width": width, "height": height}
    with tempfile.TemporaryDirectory(prefix="explainer-safe-check-") as temporary:
        manifest_path = Path(temporary) / "compositions.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        environment = {**os.environ, **_browser_env(Path(temporary))}
        try:
            result = subprocess.run(
                [node, str(runner), str(manifest_path), package_root], capture_output=True, text=True,
                env=environment, timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProjectError("native composition safe-zone check timed out after 180 seconds") from exc
    if result.returncode:
        raise ProjectError((result.stderr or result.stdout).strip() or "native composition safe-zone check failed")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ProjectError("native composition safe-zone check returned invalid JSON") from exc


def contact_sheet(root: Path, video: Path, output: Path) -> Path:
    if output.exists():
        raise ProjectError(f"contact sheet already exists: {output}")
    board = read_json(studio_file(root, "storyboard.json"))
    scenes = board["scenes"]
    frames = []
    for scene in scenes:
        at = (float(scene["start"]) + float(scene["end"])) / 2
        proc = subprocess.run(
            [command("ffmpeg"), "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True,
            check=False,
        )
        if proc.returncode or not proc.stdout:
            raise ProjectError(f"could not extract scene at {at:.2f}s")
        with Image.open(io.BytesIO(proc.stdout)) as image:
            frame = image.convert("RGB")
        frame.thumbnail((420, 420), Image.Resampling.LANCZOS)
        frames.append(frame)
    cols = 3 if frames[0].width >= frames[0].height else 4
    cell_w = max(x.width for x in frames) + 20
    cell_h = max(x.height for x in frames) + 44
    rows = math.ceil(len(frames) / cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "#E9EDF4")
    draw = ImageDraw.Draw(sheet)
    for i, frame in enumerate(frames):
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        sheet.paste(frame, (x + 10, y + 10))
        draw.text((x + 10, y + cell_h - 25), f"Scene {i + 1:02d}: {scenes[i]['headline'][:48]}", fill="#172236")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def compare_words(source: list[dict], rendered: list[dict]) -> dict:
    a = [tokens(x["text"])[0] for x in source if tokens(x["text"])]
    b = [tokens(x["text"])[0] for x in rendered if tokens(x["text"])]
    times_a = [float(x["start"]) for x in source if tokens(x["text"])]
    times_b = [float(x["start"]) for x in rendered if tokens(x["text"])]
    offsets = []
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        offsets.extend(times_b[block.b + i] - times_a[block.a + i] for i in range(block.size))
    if not offsets:
        raise ProjectError("no common words between source and rendered audio")
    sorted_abs = sorted(abs(x) for x in offsets)
    median = statistics.median(offsets)
    p95 = sorted_abs[min(len(sorted_abs) - 1, math.ceil(len(sorted_abs) * .95) - 1)]
    return {
        "matched": len(offsets), "source_words": len(a),
        "median_offset": round(median, 3),
        "p95_absolute_offset": round(p95, 3),
        "pass": len(offsets) / max(1, len(a)) >= .75 and abs(median) <= .08 and p95 <= .25,
    }


def sync_check(root: Path, video: Path, model: str, language: str | None, render_words: Path | None = None) -> dict:
    source = read_json(studio_file(root, "words.json"))
    if render_words:
        rendered = read_json(render_words)
    else:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ProjectError("render sync check needs faster-whisper or --render-words JSON") from exc
        segments, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(str(video), language=language, word_timestamps=True)
        rendered = [
            {"text": word.word.strip(), "start": round(word.start, 3), "end": round(word.end, 3)}
            for segment in segments for word in (segment.words or []) if tokens(word.word)
        ]
        work = studio_file(root, ".work") / "render-words.json"
        write_json(work, rendered)
    return compare_words(source, rendered)
