"""Decode narration and derive a simple audio-reactive mouth track."""

from __future__ import annotations

import math
import sys
from array import array
from pathlib import Path

from .common import command, run


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
