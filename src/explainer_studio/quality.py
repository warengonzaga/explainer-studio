"""Review artifacts and timing checks for rendered films."""

from __future__ import annotations

import io
import math
import statistics
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageDraw

from .common import ProjectError, command, read_json, studio_file, write_json
from .timing import tokens


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
