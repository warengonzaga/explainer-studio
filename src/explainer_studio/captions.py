"""Profile defaults and font checks for Studio caption styling."""

from __future__ import annotations

import os
import re
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

# Portrait speech bubbles stay short. Landscape uses a wider phrase.
VERTICAL_CAPTION_DEFAULTS = {"fontSize": 32, "wordsPerLine": 2, "wordsPerCaption": 6, "paddingPixels": 22}
LANDSCAPE_CAPTION_DEFAULTS = {"fontSize": 48, "wordsPerLine": 3, "wordsPerCaption": 6}
_EMPHASIS_COLOR = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
_EDGE_PUNCTUATION = ".,;:!?\"'“”‘’()[]{}"
_KEYWORD_MIN_LENGTH = 4
_AUTO_KEYWORD_LIMIT = 1
_EXPLICIT_KEYWORD_LIMIT = 8
_STUDIO_CAPTION_KEYS = {"keywordEmphasis"}
_EMPHASIS_OPTION_KEYS = {"emphasisWords", "emphasisColor", "emphasisWeight"}

DEFAULT_HOOK_FONT = "Bebas Neue"
CAPTION_PLACEMENT_FIELDS = ("x", "y", "width", "height")


def format_caption_defaults(*, portrait: bool) -> dict[str, int]:
    """Caption metrics for a vertical or landscape frame.

    Callers scale fontSize and paddingPixels with the frame. wordsPerLine and
    wordsPerCaption stay as word counts. Project and scene caption settings
    can replace any of these values.
    """
    return dict(VERTICAL_CAPTION_DEFAULTS if portrait else LANDSCAPE_CAPTION_DEFAULTS)


def caption_word(text: str) -> str:
    """Strip surrounding punctuation without splitting a hyphenated word."""
    return text.strip().strip(_EDGE_PUNCTUATION)


def pick_emphasis_keywords(*sources: str, limit: int = _AUTO_KEYWORD_LIMIT) -> list[str]:
    """Pick keywords from the first source that has one.

    The longest word in that source wins. Equal lengths keep the earlier word.
    Hyphenated words stay whole because the split is on whitespace only. Words
    shorter than four characters are skipped so the rule does not need a word list.
    """
    for source in sources:
        found = _keywords_in(source)
        if not found:
            continue
        order = sorted(range(len(found)), key=lambda index: (-len(found[index]), index))
        return [found[index] for index in order[:limit]]
    return []


def _keywords_in(source: str) -> list[str]:
    if not isinstance(source, str):
        return []
    found = []
    seen = set()
    for raw in source.split():
        word = caption_word(raw)
        if len(word) < _KEYWORD_MIN_LENGTH or _has_control_character(word):
            continue
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(word)
    return found


def keyword_emphasis_enabled(profile: dict | None, project: dict | None, scene: dict | None = None) -> bool:
    """Profile, then project, then scene caption can turn keyword emphasis off."""
    enabled = True
    for source, label in ((profile, "profile"), (project, "project")):
        enabled = _emphasis_flag(source, label, enabled)
    if isinstance(scene, dict):
        enabled = _emphasis_flag({"caption": scene.get("caption")}, "scene", enabled)
    return enabled


def emphasis_words_for_scene(scene: dict) -> list[str]:
    """Scene keywords, or one picked from the headline and then the body.

    A list is explicit, including an empty list. A string remains the single
    keyword stored by older storyboards. A missing value is picked.
    """
    if not isinstance(scene, dict):
        raise ProjectError("scene must be an object")
    if "emphasis" not in scene or scene.get("emphasis") is None:
        return pick_emphasis_keywords(scene.get("headline", ""), scene.get("body", ""))
    raw = scene.get("emphasis")
    if isinstance(raw, str):
        word = raw.strip()
        if not word or len(word) > 80 or _has_control_character(word):
            raise ProjectError("scene emphasis must be non-empty text up to 80 characters")
        return [word]
    if isinstance(raw, list):
        if len(raw) > _EXPLICIT_KEYWORD_LIMIT:
            raise ProjectError(f"scene emphasis accepts at most {_EXPLICIT_KEYWORD_LIMIT} keywords")
        words = []
        for item in raw:
            if not isinstance(item, str):
                raise ProjectError("scene emphasis entries must be text")
            word = item.strip()
            if not word or len(word) > 80 or _has_control_character(word):
                raise ProjectError("scene emphasis entries must be non-empty text up to 80 characters")
            words.append(word)
        return words
    raise ProjectError("scene emphasis must be a string or a list of words")


def prepare_caption_emphasis(options: dict, scene: dict, *, enabled: bool) -> dict:
    """Add AIVEE emphasis fields, or remove them when emphasis is off."""
    prepared = {
        key: value for key, value in options.items()
        if key not in _STUDIO_CAPTION_KEYS and key not in _EMPHASIS_OPTION_KEYS
    }
    if not enabled:
        return prepared
    words = emphasis_words_for_scene(scene)
    if not words:
        return prepared
    color = options.get("emphasisColor") or options.get("wordHighlightColor") or DEFAULT_CAPTION_STYLE["wordHighlightColor"]
    if not isinstance(color, str) or not _EMPHASIS_COLOR.fullmatch(color):
        raise ProjectError("caption emphasis color must be a hex color")
    prepared["emphasisWords"] = words
    prepared["emphasisColor"] = color
    return prepared


def _emphasis_flag(source: dict | None, label: str, current: bool) -> bool:
    if not isinstance(source, dict):
        return current
    caption = source.get("caption")
    if not isinstance(caption, dict) or "keywordEmphasis" not in caption:
        return current
    value = caption.get("keywordEmphasis")
    if not isinstance(value, bool):
        raise ProjectError(f"{label} caption keyword emphasis must be true or false")
    return value


def _has_control_character(text: str) -> bool:
    return any(ord(char) <= 31 or ord(char) == 127 for char in text)


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
    options = {**DEFAULT_CAPTION_STYLE, **_caption_values(profile_caption)}
    options.update(_caption_values(project_caption))
    placement = {**profile_placement, **project_placement}
    options.update({key: value for key, value in placement.items() if key in CAPTION_PLACEMENT_FIELDS})
    options["fontFamily"] = font_stack(options.get("fontFamily"))
    return options


def _caption_values(caption: dict) -> dict:
    return {key: value for key, value in caption.items() if key not in {"placement", "keywordEmphasis"}}


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
