# Waren avatar

An original sample presenter based on Waren Gonzaga's supplied avatar images. The four poses and five mouth states were generated as transparent sprite sheets, then cropped into individual PNGs for Explainer Studio.

Use this pack with `avatar-preview-pack` or choose **Waren (sample)** during setup. The transparent source sheets are kept in `source/`. The character uses neutral, even lighting and audio-reactive mouth states.

The `point`, `present`, and `celebrate` poses use per-pose mouth fitting: their mouth patches are scaled to 85% and centered at `[0.5, 0.31]`. Each pose also has a matching closed-eye frame, so the renderer can blink without changing the front-facing expression or mouth placement. The contact sheet is rendered through the same avatar compositor used in explainer videos.

This avatar is licensed under the repository MIT License.
