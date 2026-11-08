"""Decode narration and derive a simple audio-reactive mouth track."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import ProjectError, command, run


RHUBARB_MOUTH_MAP = {
    "A": "closed", "B": "small", "C": "open", "D": "wide",
    "E": "small", "F": "small", "G": "open", "H": "open", "X": "rest",
}


def mouth_track(voice: Path, rate: int = 15) -> list[str]:
    raw = run(
        [command("ffmpeg"), "-v", "error", "-i", str(voice), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
    ).stdout
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    hop = max(1, 16000 // rate)
    levels = []
    for start in range(0, len(samples), hop):
        chunk = samples[start : start + hop]
        levels.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)) / 32768 if chunk else 0)
    if not levels:
        return ["rest"]
    high = sorted(levels)[min(len(levels) - 1, round(len(levels) * .95))]
    scale = max(high, .008)
    states = []
    for level in levels:
        v = level / scale
        states.append("rest" if v < .10 else "closed" if v < .22 else "small" if v < .42 else "open" if v < .72 else "wide")
    return states


def mouth_at(states: list[str], t: float, rate: int = 15) -> str:
    return states[min(len(states) - 1, max(0, int(t * rate)))]


def map_phonetic_cues(cues: list[dict], duration: float, rate: int = 15) -> list[str]:
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ProjectError("Audio duration must be a positive finite number")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 1 or rate > 120:
        raise ProjectError("Mouth cue rate must be an integer between 1 and 120")
    if not isinstance(cues, list) or not cues:
        raise ProjectError("Rhubarb mouthCues must be a non-empty array")
    states = ["rest"] * max(1, math.ceil(duration * rate))
    previous_end = 0.0
    for cue in cues:
        try:
            start, end, shape = float(cue["start"]), float(cue["end"]), cue["value"].upper()
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ProjectError("Rhubarb returned a malformed mouth cue") from exc
        if shape not in RHUBARB_MOUTH_MAP or start < previous_end - 1e-6 or end <= start or end > duration + 0.02:
            raise ProjectError("Rhubarb returned unsupported or out-of-range mouth cues")
        first = max(0, int(start * rate))
        last = min(len(states), math.ceil(min(duration, end) * rate))
        for index in range(first, last):
            states[index] = RHUBARB_MOUTH_MAP[shape]
        previous_end = end
    return states


def phonetic_mouth_track(
    voice: Path, duration: float, work_dir: Path, executable: str | None = None, rate: int = 15,
) -> list[str] | None:
    """Return Rhubarb mouth states, or None when its optional CLI is unavailable."""
    configured = executable or os.environ.get("RHUBARB_PATH") or shutil.which("rhubarb")
    if not configured:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="rhubarb-", dir=work_dir) as temporary:
        wav_path = Path(temporary) / "voice.wav"
        cue_path = Path(temporary) / "mouth-cues.json"
        run([
            command("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(voice),
            "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path),
        ])
        try:
            subprocess.run(
                [
                    configured, "--exportFormat", "json", "--recognizer", "phonetic",
                    "--extendedShapes", "GHX", "--quiet", "--output", str(cue_path), str(wav_path),
                ],
                check=True, capture_output=True, text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ProjectError(f"Rhubarb lip-sync generation failed: {exc}") from exc
        try:
            cues = json.loads(cue_path.read_text(encoding="utf-8"))["mouthCues"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProjectError("Rhubarb did not produce a valid mouthCues array") from exc
    return map_phonetic_cues(cues, duration, rate)
