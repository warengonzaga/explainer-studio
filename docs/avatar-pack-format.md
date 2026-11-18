# Avatar Pack Format

Explainer Studio avatar packs use `format_version: 1`. A pack is a folder containing `README.md`, `manifest.json`, `LICENSE` or `TERMS.md`, `preview.png`, and these seven transparent PNG sprite sheets. Every declared frame must include transparent pixels (alpha 0); an alpha channel alone does not make an opaque frame valid.

```text
poses/talking.png
poses/pointing.png
poses/emotion.png
eyes/talking.png
eyes/emotion.png
mouth/talking.png
mouth/emotion.png
```

Pose frames contain the full body and head, with no eyes or mouth. All pose frames share a canvas size and baseline. Eye frames show both eyes; eye and mouth overlays use the placement rectangles in the manifest. The renderer fits the completed layers to the scene as one image.

Required pose frames:

| Sheet | Frame names |
|---|---|
| `poses/talking.png` | `idle`, `present`, `like`, `thinking`, `idea`, `celebrate` |
| `poses/pointing.png` | `top_left`, `left`, `bottom_left`, `top_right`, `right`, `bottom_right`, `viewer` |
| `poses/emotion.png` | `smile`, `grin`, `laugh`, `sad`, `worried`, `surprised`, `angry` |
| `eyes/talking.png` | `open`, `closed`, `top_left`, `left`, `bottom_left`, `top_right`, `right`, `bottom_right` |
| `eyes/emotion.png` | The seven matching emotion names |
| `mouth/talking.png` | `rest`, `closed`, `small`, `open`, `wide` |
| `mouth/emotion.png` | The seven matching emotion names |

`manifest.json` is the machine-readable source of truth. It must identify the format version, pack ID/name/version, creator and license, sheet paths, named frame rectangles (`[x, y, width, height]` in pixels), and eye/mouth placement rectangles within a pose frame. Emotion frame names must match across pose, eye, and mouth sheets. Pointing pose directions map to the same eye gaze; `viewer` uses open forward-facing eyes.

Minimal manifest shape (frame rectangles are examples; replace them with the actual coordinates in each sheet):

```json
{
  "format_version": 1,
  "id": "sample-avatar",
  "name": "Sample Avatar",
  "version": "1.0.0",
  "creator": "Creator Name",
  "license": "CC-BY-4.0",
  "license_file": "LICENSE",
  "sheets": {
    "poses": {
      "talking": {"path": "poses/talking.png", "frames": {"idle": [0, 0, 400, 800], "present": [400, 0, 400, 800], "like": [800, 0, 400, 800], "thinking": [1200, 0, 400, 800], "idea": [1600, 0, 400, 800], "celebrate": [2000, 0, 400, 800]}},
      "pointing": {"path": "poses/pointing.png", "frames": {"top_left": [0, 0, 400, 800], "left": [400, 0, 400, 800], "bottom_left": [800, 0, 400, 800], "top_right": [1200, 0, 400, 800], "right": [1600, 0, 400, 800], "bottom_right": [2000, 0, 400, 800], "viewer": [2400, 0, 400, 800]}},
      "emotion": {"path": "poses/emotion.png", "frames": {"smile": [0, 0, 400, 800], "grin": [400, 0, 400, 800], "laugh": [800, 0, 400, 800], "sad": [1200, 0, 400, 800], "worried": [1600, 0, 400, 800], "surprised": [2000, 0, 400, 800], "angry": [2400, 0, 400, 800]}}
    },
    "eyes": {
      "talking": {"path": "eyes/talking.png", "frames": {"open": [0, 0, 100, 40], "closed": [100, 0, 100, 40], "top_left": [200, 0, 100, 40], "left": [300, 0, 100, 40], "bottom_left": [400, 0, 100, 40], "top_right": [500, 0, 100, 40], "right": [600, 0, 100, 40], "bottom_right": [700, 0, 100, 40]}},
      "emotion": {"path": "eyes/emotion.png", "frames": {"smile": [0, 0, 100, 40], "grin": [100, 0, 100, 40], "laugh": [200, 0, 100, 40], "sad": [300, 0, 100, 40], "worried": [400, 0, 100, 40], "surprised": [500, 0, 100, 40], "angry": [600, 0, 100, 40]}}
    },
    "mouth": {
      "talking": {"path": "mouth/talking.png", "frames": {"rest": [0, 0, 60, 40], "closed": [60, 0, 60, 40], "small": [120, 0, 60, 40], "open": [180, 0, 60, 40], "wide": [240, 0, 60, 40]}},
      "emotion": {"path": "mouth/emotion.png", "frames": {"smile": [0, 0, 60, 40], "grin": [60, 0, 60, 40], "laugh": [120, 0, 60, 40], "sad": [180, 0, 60, 40], "worried": [240, 0, 60, 40], "surprised": [300, 0, 60, 40], "angry": [360, 0, 60, 40]}}
    }
  },
  "face": {"eyes": [145, 220, 100, 40], "mouth": [165, 300, 60, 40]}
}
```

During speech, Studio uses talking mouth frames for lip sync. During pauses in an emotion pose, it uses the matching emotion mouth. Blinks replace only the eye layer with `closed`, including during an emotion pose; the blink uses `eyes/talking.closed` because emotion eye sheets do not have a closed frame.

`README.md` explains the pack, its variants, credits, compatibility and use. `LICENSE` or `TERMS.md` states the rights granted by the creator. `preview.png` shows the pack variants together. Structural validation cannot judge visual quality, alignment, or whether facial details were baked into a pose; inspect the generated preview before publishing a pack.

Start a pack's human-readable documentation from the [avatar pack README template](avatar-pack-README-template.md).

The JSON Schema and a complete manifest example are maintained alongside this guide. Packs without `format_version: 1` are legacy and are rejected by the standardized pack reader; Studio reports the format issue without modifying the pack.
