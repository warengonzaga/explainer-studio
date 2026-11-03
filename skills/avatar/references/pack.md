# Avatar pack

Place transparent PNG pose files and `manifest.json` in one directory. The head, feet, and mouth location should remain consistent between poses. Each image is fitted inside the presenter's scene box, anchored at the bottom.

Optional `name` metadata identifies a pack in the creator profile. The bundled Waren example uses this field.

```json
{
  "poses": {
    "idle": "idle.png",
    "present": "present.png",
    "point": "point.png",
    "celebrate": "celebrate.png"
  },
  "blinks": {
    "idle": "idle-blink.png"
  },
  "mouth_anchor": [0.5, 0.34],
  "mouth_width": 0.13,
  "mouth_fit": {
    "point": {"anchor": [0.48, 0.31], "width": 0.13, "scale": 0.85},
    "present": {"anchor": [0.5, 0.31], "width": 0.13, "scale": 0.85}
  },
  "mouths": {
    "closed": "mouth-closed.png",
    "small": "mouth-small.png",
    "open": "mouth-open.png",
    "wide": "mouth-wide.png"
  }
}
```

`mouth_anchor` is `[x, y]` measured from the top-left of the visible fitted sprite, each value from 0 to 1. `mouth_width` is the fraction of sprite width used for a patch. Use optional `mouth_fit.<pose>.anchor`, `width`, and `scale` to tune a pose; pose-specific `mouths` can override individual patch files when the face angle or proportions change. This follows the reference workflow's per-pose fitting: review each pose/mouth combination, then tune only the poses that need it. A scale around `0.85` can soften open shapes that look too large. Optional `blinks` map pose names to full-pose closed-eye PNGs; preserve the original image size and framing so the blink does not jump. During rendering, supplied blink sprites display for a brief moment on a regular cycle, and the contact sheet adds a blink preview when any blink assets are present. Mouth images are optional; if absent, the engine draws simple mouth shapes on the avatar. For clean results, supply pose artwork with a neutral face and transparent mouth patches. The rendered lips follow the voice's loudness, not phonemes.
