"""Build accessible project colors from creator-supplied images."""

from __future__ import annotations

import colorsys
from collections import defaultdict
from pathlib import Path

from PIL import Image

from .common import ProjectError


def _blend(color: tuple[int, int, int], target: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(source * (1 - amount) + destination * amount) for source, destination in zip(color, target))


def _luminance(color: tuple[int, int, int]) -> float:
    channels = [value / 255 for value in color]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    bright, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def _hex(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{value:02X}" for value in color)


def extract_theme(image_paths: list[Path]) -> dict[str, str]:
    """Extract a light background, dark ink, and readable accent from images."""
    palette: dict[tuple[int, int, int], float] = defaultdict(float)
    for path in image_paths:
        if not path.is_file():
            raise ProjectError(f"theme image not found: {path}")
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
                white = Image.new("RGBA", image.size, "white")
                white.alpha_composite(image)
                sample = white.convert("RGB")
                sample.thumbnail((128, 128))
                colors = sample.quantize(colors=8).convert("RGB").getcolors(128 * 128)
        except (Image.DecompressionBombError, OSError, ValueError) as exc:
            raise ProjectError(f"could not read theme image: {path}") from exc
        if not colors:
            raise ProjectError(f"theme image has no pixels: {path}")
        total = sum(count for count, _ in colors)
        for count, color in colors:
            palette[color] += count / total / len(image_paths)

    if not palette:
        raise ProjectError("provide at least one theme image")
    dominant = max(palette, key=palette.get)
    background = _blend(dominant, (255, 255, 255), 0.9)
    ink = _blend(dominant, (0, 0, 0), 0.85)
    accent_source = max(
        palette,
        key=lambda color: (colorsys.rgb_to_hsv(*(value / 255 for value in color))[1], palette[color]),
    )
    accent = accent_source
    for step in range(11):
        accent = _blend(accent_source, (0, 0, 0), step / 10)
        if _contrast(accent, background) >= 4.5:
            break
    return {"background": _hex(background), "ink": _hex(ink), "accent": _hex(accent)}
