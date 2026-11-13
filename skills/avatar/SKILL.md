---
name: avatar
description: Create or inspect standardized layered avatar packs, validate their sprites, and attach approved packs to Explainer Studio projects.
---

# Avatar packs

Explainer Studio's default presenter is the original **Emo** robot pack at `assets/avatars/emo`. The repo also includes **Waren** as an optional sample pack at `assets/avatars/waren`, based on the creator's supplied avatar references. Users can install other packs they own or have permission to use. If an image generation tool is available, create original transparent sprites in chat and show them to the user. Otherwise request the source images as attachments. Keep generated artwork original or use assets the user is authorized to provide; do not reproduce characters or artwork from other projects.

Prepare every user supplied pack using the strict v1 sprite-sheet format in [pack.md](references/pack.md). Each pack includes talking, pointing, and emotion pose sheets, matching talking and emotion eye/mouth sheets, a manifest, README, license or terms, and preview. The bundled legacy assets are not examples of the new user-pack format and must not be rewritten as part of this workflow.

When creating a pack, follow [pack.md](references/pack.md) and the canonical [v1 format](../../docs/avatar-pack-format.md). Generate separate pose, eye, and mouth sheets; keep pose art free of facial features; record every frame rectangle and the face placements in `manifest.json`. Preserve the same pose-cell dimensions and baseline, and make sure each frame has transparent pixels rather than an opaque background. Use only the exact frame names from the format. Create `preview.png`, inspect the full contact sheet for alignment and consistent facial styling, and fix any bad or missing frames before presenting the pack.

Run `explainer avatar-validate <pack-folder>` and attach only packs that pass. Use the supplied manifest schema for required frame names, then the CLI validator for asset paths, image format, frame bounds, and per-frame transparency. Validation does not assess visual quality or rights; inspect the preview and confirm the user has permission to use the assets.

Use `attach-avatar` to copy and validate the pack into the film project. The setup skill must get the user's approval of the avatar review sheet before saving it to their profile.
