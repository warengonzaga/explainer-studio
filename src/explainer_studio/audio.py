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
from .rhubarb import installed_rhubarb_path


# A and F are closed-lip shapes (pressed M/B/P and puckered W/UW/OW). B and E stay slightly open.
RHUBARB_MOUTH_MAP = {
    "A": "closed", "B": "small", "C": "open", "D": "wide",
    "E": "small", "F": "closed", "G": "open", "H": "open", "X": "rest",
}
_SILENCE_RMS = 0.012
_OPEN_RUN_CAP = 4
_LOCAL_WINDOW_SECONDS = 0.45
_PEAK_WINDOW_SECONDS = 0.09
_NEAR_PEAK = 0.90
_NUCLEUS_LEVEL = 0.70
_WIDE_LEVEL = 1.15
_VALLEY_RATIO = 0.84
_DEEP_VALLEY_RATIO = 0.72


def _check_rate(rate: int) -> None:
    if type(rate) is not int or not 1 <= rate <= 120:
        raise ProjectError("Mouth cue rate must be an integer between 1 and 120")


def resolve_rhubarb(*candidates: str | None) -> str | None:
    """Return the first usable Rhubarb executable, including the optional bootstrap install."""
    for item in candidates:
        if not item:
            continue
        path = Path(item).expanduser()
        if path.is_file():
            return str(path.resolve())
        found = shutil.which(item)
        if found:
            return found
    installed = installed_rhubarb_path()
    if installed.is_file():
        return str(installed.resolve())
    return None


def frame_levels(samples: array, frame_count: int, rate: int, sample_rate: int = 16000) -> list[float]:
    """RMS for each timeline frame. Frames past the end of the audio are silent."""
    hop = sample_rate / rate
    total = len(samples)
    levels = []
    for index in range(frame_count):
        start = min(total, round(index * hop))
        end = min(total, round((index + 1) * hop))
        chunk = samples[start:end]
        if not chunk:
            levels.append(0.0)
            continue
        levels.append(math.sqrt(sum(value * value for value in chunk) / len(chunk)) / 32768)
    return levels


def _local_scales(levels: list[float], rate: int) -> list[float]:
    """90th percentile of a short rolling window, so a loud take does not pin the whole track."""
    radius = max(1, round(_LOCAL_WINDOW_SECONDS * rate / 2))
    scales = []
    for index in range(len(levels)):
        window = levels[max(0, index - radius) : index + radius + 1]
        ordered = sorted(window)
        high = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.90))]
        scales.append(max(high, 0.008))
    return scales


def _smooth(values: list[float]) -> list[float]:
    if len(values) < 3:
        return list(values)
    smoothed = [values[0]]
    smoothed.extend(
        (values[index - 1] + values[index] + values[index + 1]) / 3
        for index in range(1, len(values) - 1)
    )
    smoothed.append(values[-1])
    return smoothed


def amplitude_mouth_states(levels: list[float], rate: int) -> list[str]:
    """Map per-frame RMS to mouth states, opening on syllable peaks and closing in the valleys."""
    _check_rate(rate)
    if not levels:
        return ["rest"]
    normalized = _smooth([
        0.0 if level < _SILENCE_RMS else min(1.5, level / scale)
        for level, scale in zip(levels, _local_scales(levels, rate))
    ])
    peak_radius = max(1, round(_PEAK_WINDOW_SECONDS * rate))
    states: list[str] = []
    run = 0
    armed = True
    for index, level in enumerate(normalized):
        if levels[index] < _SILENCE_RMS:
            states.append("rest")
            run = 0
            armed = True
            continue
        window = normalized[max(0, index - peak_radius) : index + peak_radius + 1]
        peak = max(window)
        nucleus = level >= peak * _NEAR_PEAK and level >= _NUCLEUS_LEVEL
        valley = level <= peak * _VALLEY_RATIO
        if nucleus and level >= _WIDE_LEVEL:
            state = "wide"
        elif nucleus:
            state = "open"
        elif valley and level <= peak * _DEEP_VALLEY_RATIO:
            state = "closed"
        else:
            state = "small"
        if state in {"open", "wide"}:
            if not armed or run >= _OPEN_RUN_CAP:
                state = "small"
                armed = False
                run = 0
            else:
                run += 1
        else:
            run = 0
            if valley or state == "closed":
                armed = True
        states.append(state)
    return states


def mouth_track(voice: Path, rate: int = 15, duration: float | None = None) -> list[str]:
    _check_rate(rate)
    if duration is not None and (
        isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0
    ):
        raise ProjectError("Audio duration must be a positive finite number")
    raw = run(
        [command("ffmpeg"), "-v", "error", "-i", str(voice), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
    ).stdout
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if duration is None:
        duration = len(samples) / 16000 if samples else 0.0
    if duration <= 0:
        return ["rest"]
    frame_count = max(1, math.ceil(duration * rate))
    return amplitude_mouth_states(frame_levels(samples, frame_count, rate), rate)


def mouth_at(states: list[str], t: float, rate: int = 15) -> str:
    if not states:
        return "rest"
    return states[min(len(states) - 1, max(0, int(t * rate)))]


def map_phonetic_cues(cues: list[dict], duration: float, rate: int = 15) -> list[str]:
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ProjectError("Audio duration must be a positive finite number")
    _check_rate(rate)
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
    configured = executable or resolve_rhubarb(os.environ.get("RHUBARB_PATH"), shutil.which("rhubarb"))
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
