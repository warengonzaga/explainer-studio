"""Export an approved Explainer Studio storyboard to a HyperFrames/GSAP composition.

The existing Python renderer remains available. Export never edits source media.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from .common import ProjectError, probe_duration, project_file, read_json
from .render import storyboard_hash
from .timing import validate_storyboard, validate_words


def export_hyperframes(root: Path, portrait: bool = False) -> Path:
    root = root.resolve()
    project = read_json(root / "project.json")
    board = read_json(root / "storyboard.json")
    if not board.get("approved") or board.get("approval_hash") != storyboard_hash(board):
        raise ProjectError("storyboard is not approved; review and approve it before exporting")
    voice = project_file(root, project["voice"])
    duration = probe_duration(voice)
    validate_storyboard(root, board, duration)
    words = read_json(root / "words.json")
    validate_words(words, duration)
    target = root / ("hyperframes-portrait" if portrait else "hyperframes-landscape")
    if target.exists():
        raise ProjectError(f"HyperFrames export already exists: {target}; use a new take/project")
    width, height = ((1080, 1920) if portrait else
                     (int(project.get("width", 1920)), int(project.get("height", 1080))))
    colors = project.get("colors", {})
    bg = colors.get("background", "#F6F8FC")
    ink = colors.get("ink", "#172236")
    accent = colors.get("accent", "#426BEB")
    scenes = board["scenes"]
    # HTML is built from escaped, approved data only; paths are URI-encoded and
    # confined to the project by project_file.
    from urllib.parse import quote
    voice_url = "../" + quote(voice.relative_to(root).as_posix(), safe="/")
    clips = []
    animations = []
    for i, scene in enumerate(scenes):
        start = float(scene["start"])
        end = float(scene["end"])
        length = end - start
        if length <= 0:
            raise ProjectError(f"scene {i + 1} has invalid duration")
        headline = html.escape(str(scene.get("headline", "")))
        body = html.escape(str(scene.get("body", "")))
        label = html.escape(str(scene.get("visual_label", "")))
        image = ""
        if scene.get("asset"):
            asset = project_file(root, scene["asset"])
            if not asset.is_file():
                raise ProjectError(f"scene asset not found: {asset}")
            src = "../" + quote(asset.relative_to(root).as_posix(), safe="/")
            image = f'<img class="visual" src="{html.escape(src, quote=True)}" alt="">'
        clips.append(
            f'<section id="scene-{i}" class="clip scene" data-start="{start:.4f}" '
            f'data-duration="{length:.4f}" data-track-index="{i + 1}">'
            f'<div class="eyebrow">{label or "THE IDEA"}</div>'
            f'<h1 id="headline-{i}">{headline}</h1>'
            f'<div class="card">{image}<p>{body}</p></div>'
            f'<div class="progress">{i + 1:02d} / {len(scenes):02d}</div>'
            '</section>'
        )
        animations.append(
            f'tl.fromTo("#headline-{i}", {{y:32,opacity:0}}, '
            f'{{y:0,opacity:1,duration:Math.min(0.55,{length:.4f}),ease:"power2.out"}}, {start:.4f});'
        )
    captions = []
    # Word-level timing is source-of-truth; no invented timestamps.
    for i, word in enumerate(words):
        start = max(0.0, float(word["start"]))
        end = min(duration, float(word["end"]))
        if end <= start:
            continue
        captions.append(
            f'<div class="clip caption" data-start="{start:.4f}" '
            f'data-duration="{end - start:.4f}" data-track-index="{1000 + i}">'
            f'{html.escape(str(word["text"]))}</div>'
        )
    safe = ("left:9%;right:22%;top:12%;bottom:21%;" if portrait else
            "left:8%;right:8%;top:10%;bottom:12%;")
    markup = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>
* {{box-sizing:border-box}}
html,body {{margin:0;width:100%;height:100%;overflow:hidden;background:{bg};font-family:Arial,sans-serif;color:{ink}}}
#stage {{position:relative;width:{width}px;height:{height}px;background:{bg};overflow:hidden}}
.scene {{position:absolute;inset:0;padding:7%;display:flex;flex-direction:column;justify-content:center;gap:2.5%}}
.scene .eyebrow {{font-size:{32 if portrait else 24}px;letter-spacing:.12em;font-weight:bold;color:{accent}}}
.scene h1 {{font-size:{68 if portrait else 76}px;line-height:1.12;margin:0;max-width:95%;overflow-wrap:break-word}}
.card {{background:#ffffff;border-radius:26px;padding:4%;max-height:55%;overflow:hidden}}
.card p {{font-size:{36 if portrait else 30}px;line-height:1.3;margin:1% 0}}
.visual {{max-width:100%;max-height:{460 if portrait else 340}px;object-fit:contain}}
.progress {{position:absolute;right:8%;top:6%;font-size:24px;color:{accent}}}
.caption {{position:absolute;bottom:{23 if portrait else 7}%;left:10%;right:{24 if portrait else 10}%;text-align:center;font-size:{48 if portrait else 40}px;font-weight:bold;color:{ink};text-shadow:0 2px 4px #fff}}
/* Portrait safe zone is intentionally conservative and platform-dependent. */
{".scene {padding:12% 22% 21% 9%;}" if portrait else ""}
</style></head><body>
<div id="stage" data-composition-id="explainer-studio" data-start="0"
 data-width="{width}" data-height="{height}">
{''.join(clips)}
{''.join(captions)}
<audio data-start="0" data-duration="{duration:.4f}" data-track-index="0"
 src="{html.escape(voice_url, quote=True)}"></audio>
</div>
<script src="./node_modules/gsap/dist/gsap.min.js"></script>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{paused:true}});
{''.join(animations)}
tl.to({{}}, {{duration:{duration:.4f}}}, 0);
window.__timelines["explainer-studio"] = tl;
</script></body></html>
"""
    package = {
        "name": "explainer-studio-hyperframes",
        "version": "0.1.0",
        "private": True,
        "scripts": {
            "lint": "hyperframes lint",
            "preview": "hyperframes preview",
            "render": "hyperframes render --output renders/final.mp4"
        },
        "dependencies": {"hyperframes": "0.7.109", "gsap": "3.14.2"}
    }
    target.mkdir(parents=True)
    (target / "index.html").write_text(markup, encoding="utf-8")
    (target / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    (target / "renders").mkdir()
    return target
