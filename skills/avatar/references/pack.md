# Avatar pack format

Create user supplied packs as folders using the strict v1 format documented in [`docs/avatar-pack-format.md`](../../../docs/avatar-pack-format.md), with the normative [manifest schema](../../../docs/avatar-pack.schema.json). Do not convert or edit the bundled Waren or Emo packs as part of this workflow.

Every v1 pack contains `README.md`, `manifest.json`, a `LICENSE` or `TERMS.md`, `preview.png`, and seven transparent PNG sheets:

```text
poses/talking.png   poses/pointing.png   poses/emotion.png
eyes/talking.png    eyes/emotion.png
mouth/talking.png  mouth/emotion.png
```

The manifest declares pack identity, license, sheet paths, named pixel rectangles for every frame, and eyes/mouth destination rectangles within each pose frame. Use the exact required frame names and keep all pose cells the same size and baseline. Pose artwork contains the complete body and head without eyes or mouth. Eye sprites contain both eyes. Emotional frame names must match across pose, eye, and mouth sheets. Follow the no-lips, clean-mouth appearance when that is part of the avatar design.

Before a pack is selected, create a review image with `explainer avatar-preview-pack <pack-folder> --output <pack-folder>/preview.png` and inspect it for alignment, style consistency, and missing or baked-in facial details. Then validate it with `explainer avatar-validate <pack-folder>`. Attach only a pack that passes validation. Legacy packs are rejected with a format error; never rewrite a user's pack in place.

The standard talking mouth frames are `rest`, `closed`, `small`, `open`, and `wide`. Emotion frames are `smile`, `grin`, `laugh`, `sad`, `worried`, `surprised`, and `angry`. Lip sync uses talking mouths during speech and the selected emotion mouth during pauses. Eye blinking changes only the eye layer. Pointing poses select the matching gaze automatically, and `viewer` points toward the audience with open forward-facing eyes.

Use the manifest example in [`docs/avatar-pack-format.md`](../../../docs/avatar-pack-format.md) as a starting point. Explain license and commercial terms in the pack's README and declared license file. Structural validation does not certify visual quality or ownership rights.
