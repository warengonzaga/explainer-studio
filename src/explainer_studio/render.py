"""Deterministic scene compositor and FFmpeg encoder."""

from __future__ import annotations

import math
import hashlib
import json
import subprocess
from bisect import bisect_right
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .audio import mouth_at, mouth_track
from .avatar import draw_avatar
from .common import ProjectError, command, probe_duration, project_file, read_json
from .timing import validate_storyboard, validate_words


def storyboard_hash(board: dict) -> str:
    data = json.dumps(board["scenes"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _font(size: int, bold: bool = False):
    names = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def _lines(draw, value: str, font, max_width: int, max_lines: int) -> list[str]:
    lines = []
    current = ""
    for word in value.split():
        candidate = (current + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _scene_image(root: Path, scene: dict, size: tuple[int, int]) -> Image.Image | None:
    if not scene.get("asset"):
        return None
    asset = project_file(root, scene["asset"])
    try:
        with Image.open(asset) as image:
            return image.convert("RGBA")
    except OSError as exc:
        raise ProjectError(f"cannot read scene asset: {asset}") from exc


def _brand_mark(image: Image.Image, project: dict, x: int, y: int, max_w: int, max_h: int, font_size: int, ink: str) -> None:
    logo = project.get("_logo_image")
    if logo:
        mark = logo.copy()
        mark.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        image.paste(mark, (x, y), mark)
    else:
        ImageDraw.Draw(image).text((x, y), project.get("brand", "Explainer Studio"), font=_font(font_size, True), fill=ink)


def _portrait_frame(root: Path, project: dict, scene: dict, index: int, t: float, size: tuple[int, int], words: list[dict], starts: list[float], states: list[str], asset: Image.Image | None, include_avatar: bool = True, include_captions: bool = True) -> Image.Image:
    w, h = size
    s = min(w / 1080, h / 1920)
    colors = project.get("colors", {})
    bg, ink, accent = colors.get("background", "#F6F8FC"), colors.get("ink", "#172236"), colors.get("accent", "#426BEB")
    image = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(image)
    pad = round(72 * s)
    if not scene.get("visual_cues"):
        _brand_mark(image, project, pad, round(180 * s), round(400 * s), round(80 * s), round(35 * s), ink)
        d.text((w - round(190 * s), round(185 * s)), f"{index + 1:02d} / {len(project['_scenes']):02d}", font=_font(round(26 * s)), fill=accent)
    local = max(0, t - float(scene["start"]))
    rise = max(0, 1 - min(1, local / .45)) * round(28 * s)
    if not scene.get("visual_cues"):
        title_font = _font(round(68 * s), True)
        for k, line in enumerate(_lines(d, scene["headline"], title_font, w - pad * 2, 3)):
            d.text((pad, round(300 * s) + k * round(84 * s) + rise), line, font=title_font, fill=ink)
        d.rounded_rectangle((pad, round(565 * s), w - pad, round(1110 * s)), radius=round(35 * s), fill="white", outline="#DEE4EF", width=max(1, round(2 * s)))
    if asset:
        progress = min(1, local / max(.1, float(scene["end"]) - float(scene["start"])))
        thumb = asset.copy()
        thumb.thumbnail((round((w - pad * 3) * (1 + .035 * progress)), round(465 * s * (1 + .035 * progress))), Image.Resampling.LANCZOS)
        image.paste(thumb, ((w - thumb.width) // 2, round(600 * s) + (round(465 * s) - thumb.height) // 2), thumb)
    elif not scene.get("visual_cues"):
        d.text((pad + round(42 * s), round(625 * s)), scene.get("visual_label") or "THE IDEA", font=_font(round(29 * s), True), fill=accent)
        body_font = _font(round(39 * s))
        for k, line in enumerate(_lines(d, scene.get("body", ""), body_font, w - pad * 3, 6)):
            d.text((pad + round(42 * s), round(700 * s) + k * round(55 * s)), line, font=body_font, fill=ink)
    if include_avatar:
        draw_avatar(image, root, project, scene.get("pose", "idle"), mouth_at(states, t), t, avatar_box(size))
    if include_captions and scene.get("emphasis") and not scene.get("visual_cues") and t >= float(scene.get("emphasis_at", 1e12)):
        d.text((round(560 * s), round(1180 * s)), str(scene["emphasis"])[:20].upper(), font=_font(round(30 * s), True), fill=accent)
    if index == len(project["_scenes"]) - 1 and project.get("cta"):
        d.text((round(550 * s), round(1250 * s)), project["cta"][:32], font=_font(round(38 * s), True), fill=ink)
    wi = bisect_right(starts, t) - 1
    if include_captions and wi >= 0 and t < float(words[wi]["end"]) + .6:
        active = words[wi]["text"].strip()
        word_font = _font(round(55 * s), True)
        for k, line in enumerate(_lines(d, active, word_font, round(360 * s), 2)):
            d.text((round(540 * s), round(1350 * s) + k * round(68 * s)), line, font=word_font, fill=accent)
    return image


def _frame(root: Path, project: dict, scene: dict, index: int, t: float, size: tuple[int, int], words: list[dict], starts: list[float], states: list[str], asset: Image.Image | None, include_avatar: bool = True, include_captions: bool = True) -> Image.Image:
    w, h = size
    if h > w:
        return _portrait_frame(root, project, scene, index, t, size, words, starts, states, asset, include_avatar, include_captions)
    s = min(w / 1280, h / 720)
    colors = project.get("colors", {})
    bg, ink, accent = colors.get("background", "#F6F8FC"), colors.get("ink", "#172236"), colors.get("accent", "#426BEB")
    image = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(image)
    pad = round(60 * s)
    _brand_mark(image, project, pad, round(28 * s), round(280 * s), round(45 * s), round(22 * s), ink)
    d.text((w - pad - round(110 * s), round(30 * s)), f"{index + 1:02d} / {len(project['_scenes']):02d}", font=_font(round(16 * s)), fill=accent)

    local = max(0, t - float(scene["start"]))
    rise = max(0, 1 - min(1, local / .45)) * round(22 * s)
    hx = round(w * .36)
    hy = round(h * .19 + rise)
    title_font = _font(round(54 * s), True)
    title_lines = _lines(d, scene["headline"], title_font, round(w * .56), 3)
    for line in title_lines:
        d.text((hx, hy), line, font=title_font, fill=ink)
        hy += round(66 * s)
    d.rounded_rectangle((hx, hy + round(12 * s), hx + round(72 * s), hy + round(19 * s)), radius=round(4 * s), fill=accent)

    if asset:
        view_w, view_h = round(w * .48), round(h * .33)
        progress = min(1, local / max(.1, float(scene["end"]) - float(scene["start"])))
        thumb = asset.copy()
        thumb.thumbnail((round(view_w * (1 + .035 * progress)), round(view_h * (1 + .035 * progress))), Image.Resampling.LANCZOS)
        ax = hx + max(0, (view_w - thumb.width) // 2)
        ay = round(h * .57 - thumb.height / 2)
        image.paste(thumb, (ax, ay), thumb)
    else:
        card = (round(w * .35), round(h * .46), round(w * .95), round(h * .85)) if scene.get("visual_cues") else (hx, round(h * .55), round(w * .92), round(h * .77))
        d.rounded_rectangle(card, radius=round(26 * s), fill="#FFFFFF", outline="#DEE4EF", width=max(1, round(2 * s)))
        d.text((hx + round(32 * s), card[1] + round(26 * s)), scene.get("visual_label") or "THE IDEA", font=_font(round(19 * s), True), fill=accent)
        body = scene.get("body", "")
        if not scene.get("visual_cues"):
            for k, line in enumerate(_lines(d, body, _font(round(25 * s)), card[2] - card[0] - round(64 * s), 3)):
                d.text((hx + round(32 * s), card[1] + round(68 * s) + k * round(34 * s)), line, font=_font(round(25 * s)), fill=ink)

    if index == len(project["_scenes"]) - 1 and project.get("cta"):
        d.text((hx, round(h * .82)), project["cta"][:48], font=_font(round(28 * s), True), fill=accent)
    if include_captions and scene.get("emphasis") and t >= float(scene.get("emphasis_at", 1e12)):
        elapsed = t - float(scene["emphasis_at"])
        pulse = 1 + .12 * max(0, 1 - elapsed / .4)
        emphasis_y = round(h * (.405 if scene.get("visual_cues") else .46))
        d.text((hx, emphasis_y), str(scene["emphasis"])[:24].upper(), font=_font(round(29 * s * pulse), True), fill=accent)

    if include_avatar:
        draw_avatar(image, root, project, scene.get("pose", "idle"), mouth_at(states, t), t, avatar_box(size))

    # Word-aligned caption: the current spoken word receives a colored backing.
    wi = bisect_right(starts, t) - 1
    if include_captions and wi >= 0 and t < float(words[wi]["end"]) + .6:
        lo, hi = max(0, wi - 3), min(len(words), wi + 4)
        caption = " ".join(x["text"].strip() for x in words[lo:hi])
        cap_font = _font(round(25 * s), True)
        cap_w = d.textbbox((0, 0), caption, font=cap_font)[2]
        cx, cy = max(pad, (w - cap_w) // 2), round(h * .91)
        d.rounded_rectangle((cx - round(18 * s), cy - round(12 * s), cx + cap_w + round(18 * s), cy + round(42 * s)), radius=round(12 * s), fill=ink)
        d.text((cx, cy), caption, font=cap_font, fill="#FFFFFF")
        prefix = " ".join(x["text"].strip() for x in words[lo:wi])
        prefix_w = d.textbbox((0, 0), prefix + (" " if prefix else ""), font=cap_font)[2]
        active = words[wi]["text"].strip()
        d.text((cx + prefix_w, cy), active, font=cap_font, fill="#AFC3FF")
    return image


def avatar_box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    if h > w:
        scale = min(w / 1080, h / 1920)
        return round(32 * scale), round(1120 * scale), round(475 * scale), round(500 * scale)
    return round(w * .025), round(h * .29), round(w * .31), round(h * .58)


def render(root: Path, output: Path, preview: bool = False, portrait: bool = False) -> Path:
    return _render(root, output, preview, portrait, include_avatar=True, include_audio=True, include_captions=True)


def render_background(root: Path, output: Path, preview: bool = False, portrait: bool = False) -> Path:
    """Render the explainer visuals without narration or presenter for Engine composition."""
    return _render(root, output, preview, portrait, include_avatar=False, include_audio=False, include_captions=False)


def _render(root: Path, output: Path, preview: bool, portrait: bool, include_avatar: bool, include_audio: bool, include_captions: bool) -> Path:
    project = read_json(root / "project.json")
    board = read_json(root / "storyboard.json")
    if not board.get("approved") or board.get("approval_hash") != storyboard_hash(board):
        raise ProjectError("storyboard is not approved; review it in chat, then run `explainer approve <project>`")
    voice = project_file(root, project["voice"])
    duration = probe_duration(voice)
    validate_storyboard(root, board, duration)
    words = read_json(root / "words.json")
    validate_words(words, duration)
    if output.exists():
        raise ProjectError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = (1080, 1920) if portrait else (int(project.get("width", 1920)), int(project.get("height", 1080)))
    fps = int(project.get("fps", 60))
    if preview:
        width, height = round(width / 2), round(height / 2)
        fps = min(fps, 20)
    if width < 320 or height < 240 or fps < 1 or fps > 60:
        raise ProjectError("invalid project resolution or frame rate")
    starts = [float(x["start"]) for x in words]
    states = mouth_track(voice) if include_avatar else ["rest"]
    scenes = board["scenes"]
    project["_scenes"] = scenes
    if project.get("logo"):
        logo_file = project_file(root, project["logo"])
        if not logo_file.is_file():
            raise ProjectError(f"logo not found: {logo_file}")
        with Image.open(logo_file) as mark:
            project["_logo_image"] = mark.convert("RGBA")
    ends = [float(x["end"]) for x in scenes]
    assets = [_scene_image(root, scene, (width, height)) for scene in scenes]
    cmd = [command("ffmpeg"), "-v", "error", "-n", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-"]
    if include_audio:
        cmd += ["-i", str(voice)]
    music = project.get("music")
    if music and include_audio:
        bed = project_file(root, music)
        if not bed.is_file():
            raise ProjectError(f"music not found: {bed}")
        cmd += ["-i", str(bed), "-filter_complex", "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[vo];[2:a]volume=0.10[bed];[bed][vo]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=400[duck];[vo][duck]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]"]
    elif include_audio:
        cmd += ["-map", "0:v", "-map", "1:a", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    else:
        cmd += ["-map", "0:v", "-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast" if preview else "medium", "-crf", "23" if preview else "18"]
    if include_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-t", str(duration)]
    cmd += ["-movflags", "+faststart", str(output)]
    log = output.with_suffix(".render.log")
    try:
        with log.open("wb") as error_log:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=error_log)
            assert proc.stdin is not None
            try:
                count = math.ceil(duration * fps)
                for frame_number in range(count):
                    t = min(duration - 1e-6, frame_number / fps)
                    scene_index = min(len(scenes) - 1, bisect_right(ends, t))
                    frame = _frame(root, project, scenes[scene_index], scene_index, t, (width, height), words, starts, states, assets[scene_index], include_avatar, include_captions)
                    proc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                pass
            finally:
                proc.stdin.close()
            if proc.wait() != 0:
                raise ProjectError(f"render failed; inspect {log}")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output
