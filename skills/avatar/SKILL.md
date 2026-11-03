---
name: avatar
description: Add or inspect an original custom presenter for Explainer Studio, including pose images, mouth anchor, contact-sheet review, and project attachment.
---

# Custom avatar

The built-in presenter is drawn by Explainer Studio and requires no outside assets. The repo includes an original sample pack named **Waren** at `assets/avatars/waren`; it is based on the creator's supplied avatar references. For another custom presenter, use images the user owns or has permission to use. If an image generation tool is available, generate original transparent pose images in chat and show them to the user. Otherwise request the pose files as attachments. Do not use the Talking Explainer demo character or its artwork.

Prepare a pack following [pack.md](references/pack.md). The pack has an idle pose, optional present/point/celebrate poses, a normalized mouth anchor, and optional transparent mouth patches. A single idle pose works but will not visibly switch pose. Use `attach-avatar` to copy and validate the pack into the film project. Create a contact sheet with the avatar preview command and show it in chat. Adjust the anchor or artwork until the resting and talking mouth positions look right; only then use it in a render.
