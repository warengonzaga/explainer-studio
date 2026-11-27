"""Review artifacts and timing checks for rendered films."""

from __future__ import annotations

import io
import json
import math
import os
import re
import statistics
import subprocess
import tempfile
from difflib import SequenceMatcher
from importlib.resources import as_file, files
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
    runner = files("explainer_studio").joinpath("scripts", "safe_check.mjs")
    manifest = {"compositions": compositions, "width": width, "height": height}
    with tempfile.TemporaryDirectory(prefix="explainer-safe-check-") as temporary:
        manifest_path = Path(temporary) / "compositions.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        environment = {**os.environ, **_browser_env(Path(temporary))}
        with as_file(runner) as runner_path:
            script = Path(runner_path)
            if not script.is_file():
                raise ProjectError("safe-zone checker is missing from the Explainer Studio package")
            try:
                result = subprocess.run(
                    [node, str(script), str(manifest_path), package_root], capture_output=True, text=True,
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


_VERTICAL_SOCIAL = 9 / 16


def safe_zone_preset(width: int, height: int) -> str:
    """Pick the safe-zone preset that matches this frame.

    A frame near 9:16 uses vertical-social. Other tall frames use title-safe.
    Wide frames use full: the landscape avatar and caption are placed inside
    the outer five percent, so a tighter preset would fail the designed layout.
    """
    if width > 0 and height > 0 and abs((width / height) - _VERTICAL_SOCIAL) / _VERTICAL_SOCIAL <= 0.02:
        return "vertical-social"
    if height > width:
        return "title-safe"
    return "full"


def region_qa_plan(
    project: dict, board: dict, width: int, height: int, profile: dict | None = None, fps: float | str | None = None,
) -> dict:
    """Flicker regions and safe-zone boxes from the avatar and caption layout."""
    from .templates import avatar_region, caption_region

    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ProjectError("region QA needs positive integer frame dimensions")
    scenes = board.get("scenes") if isinstance(board, dict) else None
    if not isinstance(scenes, list):
        raise ProjectError("storyboard scenes must be an array")
    avatar = _fraction_box(avatar_region(width, height))
    flicker_regions = [{"id": "avatar", **avatar}]
    boxes = [{"id": "avatar", **avatar}]
    unique: list[dict[str, float]] = []
    seen: set[tuple[float, float, float, float]] = set()
    timed = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ProjectError(f"scene {index} must be an object")
        box = _fraction_box(caption_region(project, width, height, profile=profile, scene=scene))
        key = (box["x"], box["y"], box["width"], box["height"])
        if key not in seen:
            seen.add(key)
            unique.append(box)
        try:
            start, end = float(scene["start"]), float(scene["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"scene {index} needs numeric start and end") from exc
        duration = end - start
        if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
            raise ProjectError(f"scene {index} needs a positive duration")
        timed.append((index, box, start, duration))
    if len(unique) == 1:
        flicker_regions.append({"id": "caption", **unique[0]})
    else:
        flicker_regions.extend({"id": f"caption-{index}", **box} for index, box in enumerate(unique, start=1))
    for index, box, start, duration in timed:
        boxes.append({
            "id": "caption" if len(timed) == 1 else f"caption-{index}",
            **box,
            "timeSeconds": start,
            "durationSeconds": duration,
        })
    return {
        "preset": safe_zone_preset(width, height),
        "flicker": {"regions": flicker_regions},
        "boxes": {
            "schemaVersion": 1,
            "width": width,
            "height": height,
            "fps": _qa_frame_rate(fps, project.get("fps", 30)),
            "boxes": boxes,
        },
    }


def region_qa(
    root: Path, project: dict, board: dict, video: Path, width: int, height: int, fps: float | str | None = None,
) -> dict:
    """Run AIVEE flicker and safe-zone checks on the avatar and caption regions."""
    from .engine import require_aivee_version, resolve_aivee
    from .templates import _saved_profile

    command, package_root = resolve_aivee()
    require_aivee_version(package_root, "region flicker and safe-zone checks")
    plan = region_qa_plan(project, board, width, height, _saved_profile(), fps)
    with tempfile.TemporaryDirectory(prefix="explainer-region-qa-") as temporary:
        temporary = Path(temporary)
        flicker_options = temporary / "flicker.json"
        boxes_path = temporary / "boxes.json"
        safe_options = temporary / "safe-zone.json"
        write_json(flicker_options, plan["flicker"])
        write_json(boxes_path, plan["boxes"])
        write_json(safe_options, {"preset": plan["preset"]})
        flicker = _aivee_qa(command, ["qa", "flicker", str(video), str(flicker_options)], root)
        safe_zone = _aivee_qa(command, ["qa", "safe-zone", str(boxes_path), str(safe_options)], root)
    return {
        "pass": flicker.get("passed") is True and safe_zone.get("passed") is True,
        "preset": plan["preset"],
        "regions": plan["flicker"]["regions"],
        "flicker": flicker,
        "safe_zone": safe_zone,
    }


def _fraction_box(box: dict) -> dict[str, float]:
    return {key: round(float(box[key]), 6) for key in ("x", "y", "width", "height")}


def _qa_frame_rate(value: float | str | None, fallback) -> float | str:
    if isinstance(value, str) and re.fullmatch(r"\d+/\d+", value.strip()):
        return value.strip()
    parsed = _parse_frame_rate(value)
    if parsed is not None:
        return parsed
    parsed = _parse_frame_rate(fallback)
    if parsed is None:
        raise ProjectError("region QA needs a positive frame rate")
    return parsed


def _parse_frame_rate(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return float(value)
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            rate = float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            return None
        if math.isfinite(rate) and rate > 0:
            return rate
    return None


def _aivee_qa(command: list[str], args: list[str], cwd: Path) -> dict:
    result = subprocess.run([*command, *args], cwd=cwd, capture_output=True, text=True)
    detail = (result.stderr or result.stdout).strip()
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProjectError(detail or "AIVEE region QA returned invalid JSON") from exc
    if not isinstance(report, dict) or not isinstance(report.get("passed"), bool):
        raise ProjectError(detail or "AIVEE region QA returned an unexpected report")
    if result.returncode not in (0, 1) or (result.returncode == 0) != report["passed"]:
        raise ProjectError(detail or f"AIVEE region QA exited {result.returncode}")
    return report


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


def export_stills(video: Path, timestamps: list[float], output_dir: Path, make_sheet: bool = False) -> dict:
    if not timestamps or len(timestamps) > 100:
        raise ProjectError("provide between 1 and 100 timestamps")
    frames = [output_dir / f"frame-{index:02d}-at-{at:.3f}s.png" for index, at in enumerate(timestamps, 1)]
    sheet_path = output_dir / "contact-sheet.jpg"
    targets = [*frames, *([sheet_path] if make_sheet else [])]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise ProjectError(f"still output already exists: {existing[0]}; choose another output directory")
    if output_dir.exists() and not output_dir.is_dir():
        raise ProjectError(f"still output is not a directory: {output_dir}")

    made_directory = not output_dir.exists()
    created = []
    thumbnails = []
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for at, path in zip(timestamps, frames):
            result = subprocess.run(
                [command("ffmpeg"), "-nostdin", "-v", "error", "-i", str(video), "-ss", f"{at:.6f}",
                 "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True, check=False,
            )
            if result.returncode or not result.stdout:
                raise ProjectError(f"could not extract a frame at {at:.3f}s")
            with Image.open(io.BytesIO(result.stdout)) as image:
                image.load()
                if make_sheet:
                    thumb = image.convert("RGB")
                    thumb.thumbnail((420, 420), Image.Resampling.LANCZOS)
                    thumbnails.append(thumb.copy())
            with path.open("xb") as frame_file:
                created.append(path)
                frame_file.write(result.stdout)

        if make_sheet:
            columns = 3 if thumbnails[0].width >= thumbnails[0].height else 4
            cell_width = max(image.width for image in thumbnails) + 20
            cell_height = max(image.height for image in thumbnails) + 44
            rows = math.ceil(len(thumbnails) / columns)
            sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#E9EDF4")
            draw = ImageDraw.Draw(sheet)
            for index, image in enumerate(thumbnails):
                x, y = (index % columns) * cell_width, (index // columns) * cell_height
                sheet.paste(image, (x + 10, y + 10))
                draw.text((x + 10, y + cell_height - 25), f"{timestamps[index]:.3f}s", fill="#172236")
            with sheet_path.open("xb") as sheet_file:
                created.append(sheet_path)
                sheet.save(sheet_file, format="JPEG", quality=92)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        if made_directory:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        raise
    return {
        "video": str(video), "frames": [{"time": at, "path": str(path)} for at, path in zip(timestamps, frames)],
        "contact_sheet": str(sheet_path) if make_sheet else None,
    }


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
