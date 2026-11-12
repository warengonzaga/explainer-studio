---
name: avatar
description: Add or inspect an original custom presenter for Explainer Studio, including pose images, mouth anchor, contact-sheet review, and project attachment.
---

# Avatar packs

Explainer Studio's default presenter is the original **Emo** robot pack at `assets/avatars/emo`. The repo also includes **Waren** as an optional sample pack at `assets/avatars/waren`, based on the creator's supplied avatar references. Users can install other packs they own or have permission to use. If an image generation tool is available, generate original transparent pose images in chat and show them to the user. Otherwise request the pose files as attachments. Do not use the Talking Explainer demo character or its artwork.

Prepare a pack following [pack.md](references/pack.md). The pack has an idle pose, optional present/point/celebrate poses, a normalized mouth anchor, and transparent mouth patches. A single idle pose works but will not visibly switch pose.

When building an original avatar from image references, use separate pose and face/mouth sheets; effects can be a third optional sheet for separate scene assets. Keep each cell consistent in head size and position, leave clear gutters, and omit labels. Cut each approved cell into its own transparent PNG. Fit mouth patches to each pose (do not assume a single anchor works for every face), add optional closed-eye pose frames for blinking, generate the contact sheet, and show it in chat. Adjust the fit or artwork until every pose/mouth combination looks right; only then use it in a render. This adapts the pose fitting and review-sheet workflow from [Talking Explainer](https://github.com/brewed-ops/talking-explainer) without reusing its code or artwork.

Use `attach-avatar` to copy and validate the pack into the film project. The setup skill must get the user's approval of the avatar review sheet before saving it to their profile.
