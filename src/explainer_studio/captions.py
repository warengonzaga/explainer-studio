"""Profile defaults and font checks for Studio caption styling."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .common import ProjectError


DEFAULT_CAPTION_STYLE = {
    "layoutPreset": "speechBubble",
    "fontFamily": "Arial",
    "fontWeight": 800,
    "color": "#FFFFFF",
    "backgroundColor": "#000000B8",
    "wordHighlight": True,
    "wordHighlightColor": "#FFE45C",
    "wordHighlightAnimation": "pop",
    "textShadow": {"color": "#000000B8", "blurPixels": 4, "offsetXPixels": 0, "offsetYPixels": 2},
}

DEFAULT_HOOK_FONT = "Bebas Neue"
CAPTION_PLACEMENT_FIELDS = ("x", "y", "width", "height")


def caption_options(profile: dict, project: dict) -> dict:
    """Merge profile caption defaults with explicit project settings."""
    profile_caption = profile.get("caption", {}) or {}
    project_caption = project.get("caption", {}) or {}
    if not isinstance(profile_caption, dict) or not isinstance(project_caption, dict):
        raise ProjectError("caption settings must be an object")
    profile_placement = profile_caption.get("placement", {}) or {}
    project_placement = project_caption.get("placement", {}) or {}
    if not isinstance(profile_placement, dict) or not isinstance(project_placement, dict):
        raise ProjectError("caption placement must be an object")
    options = {**DEFAULT_CAPTION_STYLE, **{key: value for key, value in profile_caption.items() if key != "placement"}}
    options.update({key: value for key, value in project_caption.items() if key != "placement"})
    placement = {**profile_placement, **project_placement}
    options.update({key: value for key, value in placement.items() if key in CAPTION_PLACEMENT_FIELDS})
    options["fontFamily"] = font_stack(options.get("fontFamily"))
    return options


def _font_families() -> set[str] | None:
    if os.name == "nt":
        try:
            import winreg

            families = set()
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(hive, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts")
                except OSError:
                    continue
                with key:
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, _, _ = winreg.EnumValue(key, index)
                        families.add(name.split(" (")[0].casefold())
            return families
        except (ImportError, OSError):
            return None

    fc_list = shutil.which("fc-list")
    if not fc_list:
        return None
    try:
        result = subprocess.run([fc_list, "--format=%{family}\n"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return {family.strip().casefold() for line in result.stdout.splitlines() for family in line.split(",") if family.strip()}


def _primary_family(value: str) -> str:
    return value.split(",", 1)[0].strip().strip("\"'")


def font_stack(value: str, fallback: str = "sans-serif") -> str:
    if not isinstance(value, str) or not value.strip() or any(char in value for char in ";{}\r\n"):
        raise ProjectError("font family must be a nonempty CSS font-family value")
    value = value.strip()
    if "," in value or _primary_family(value).casefold() in {"sans-serif", "serif", "monospace", "system-ui"}:
        return value
    return f"{value}, {fallback}"


def warn_missing_fonts(profile: dict, *, stream=None) -> list[str]:
    """Warn when configured display fonts cannot be confirmed on this machine."""
    if stream is None:
        stream = sys.stderr
    caption = profile.get("caption", {})
    caption_font = caption.get("fontFamily", DEFAULT_CAPTION_STYLE["fontFamily"]) if isinstance(caption, dict) else DEFAULT_CAPTION_STYLE["fontFamily"]
    hook_font = profile.get("hook_font_family", DEFAULT_HOOK_FONT)
    families = _font_families()
    warnings = []
    for role, value in (("caption", caption_font), ("hook", hook_font)):
        if not isinstance(value, str) or not value.strip():
            continue
        family = _primary_family(value)
        if family.casefold() in {"sans-serif", "serif", "monospace", "system-ui"}:
            continue
        if families is None:
            warnings.append(f"could not verify {role} font '{family}'; install or verify it in the render environment")
        elif family.casefold() not in families:
            warnings.append(f"{role} font '{family}' is not installed; install it or choose an available font")
    if stream is not False:
        for warning in warnings:
            print(f"Warning: {warning}", file=stream)
    return warnings
