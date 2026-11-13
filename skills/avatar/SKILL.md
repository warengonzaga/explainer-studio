---
name: avatar
description: Add or inspect an original custom presenter for Explainer Studio, including pose images, mouth anchor, contact-sheet review, and project attachment.
---

# Avatar packs

Explainer Studio's default presenter is the original **Emo** robot pack at `assets/avatars/emo`. The repo also includes **Waren** as an optional sample pack at `assets/avatars/waren`, based on the creator's supplied avatar references. Users can install other packs they own or have permission to use. If an image generation tool is available, generate original transparent pose images in chat and show them to the user. Otherwise request the pose files as attachments. Do not use the Talking Explainer demo character or its artwork.

Prepare every user supplied pack using the strict v1 sprite-sheet format in [pack.md](references/pack.md). Each pack includes talking, pointing, and emotion pose sheets, matching talking and emotion eye/mouth sheets, a manifest, README, license or terms, and preview. The bundled legacy assets are not examples of the new user-pack format and must not be rewritten as part of this workflow.

When building an original avatar from image references, prepare the seven required transparent sheets and record named frame rectangles and face placement in the manifest. Keep every pose cell consistent in canvas size and baseline; pose sprites have no eyes or mouth. Eye sprites contain both eyes. Generate `preview.png`, show it in chat, and review composition and asset quality before use. This adapts the pose fitting and review-sheet workflow from [Talking Explainer](https://github.com/brewed-ops/talking-explainer) without reusing its code or artwork.

Use `attach-avatar` to copy and validate the pack into the film project. The setup skill must get the user's approval of the avatar review sheet before saving it to their profile.
