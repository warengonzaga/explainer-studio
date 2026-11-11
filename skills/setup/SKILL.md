---
name: setup
description: Set up Explainer Studio for the first time, repair missing local tools, or update the saved creator profile. Use when a user installs Explainer Studio, asks to set it up, or starts a film without a profile.
---

# Set up Explainer Studio

Resolve the plugin root from this file (`../..`). Run `python <plugin-root>/scripts/explainer.py bootstrap` to install Studio's Python dependencies into its managed user environment, then run `doctor`. Explain missing tools in plain language. Python 3.11+, Node.js 22+ with npm, FFmpeg, ffprobe, and Chrome or Edge are required; `faster-whisper` is optional until automatic transcription is needed. The launcher uses the managed Python environment for later commands. Do not change system Python or put an API key in command arguments, chat output, or `profile.json`.

Explainer Studio installs and manages its AIVEE CLI dependency for the user. If `doctor` reports AIVEE missing, run `python <plugin-root>/scripts/explainer.py install-engine`, then rerun `doctor` and do not continue until it reports AIVEE available. Reuse a compatible AIVEE npm installation when present; otherwise install the Studio-supported package in the Studio user data directory. Do not ask users to clone the Engine repository, install AIVEE separately, or provide an Engine path. If Node.js, npm, or installation is unavailable, explain the specific prerequisite and stop setup before saving a profile.

Briefly recommend a model for creative planning and animation authoring: Astra for best results in Codex, with Sol as the minimum recommendation; Opus for best results in Claude Code, with Sonnet as the minimum recommendation. The user selects the model in their chat environment. Continue setup with the active model; these are project recommendations, not an enforced runtime requirement. Apply the [motion quality guide](../create-explainer/references/motion-quality.md) when creating the first film.

Ask the user one short grouped set of questions, offering these defaults so setup can be completed with minimal input:

1. Brand defaults to **Explainer Studio**; narration language defaults to English. Logo, colors, and output folder are optional.
2. Voice route defaults to a user-provided recording. ElevenLabs is optional and needs an API key set privately as `ELEVENLABS_API_KEY` and a voice ID. Never require a voice clone.
3. Avatar defaults to the original built-in geometric presenter. The bundled **Waren (sample)** at `<plugin-root>/assets/avatars/waren` or a user-owned sprite pack can be selected; preview the contact sheet in chat and get approval before saving either pack. See [avatar pack guide](../avatar/references/pack.md).
4. Optional Rhubarb Lip Sync executable path. When configured, Studio uses phonetic cues mapped to its five mouth states. Without it, Studio falls back to audio-level mouth timing.

Save only non-secret user choices through `python <plugin-root>/scripts/explainer.py setup [--brand ...] [--language ...] [--voice-route ...] [--avatar ...] [--output-dir ...]`; add `--rhubarb-path`, `--avatar-pack`, `--logo`, colors, and `--cta` when chosen. Defaults are **Explainer Studio**, English, recording voice, built-in avatar, the default palette, and `~/Explainer Studio` output. If a profile exists, show the current non-secret choices with `profile`, ask only what should change, and use `--force` for the intentional update. The profile lives at `EXPLAINER_STUDIO_HOME/profile.json`, or `~/.explainer-studio/profile.json` by default. Keep every response and setup result in the chat.

Once setup succeeds, offer to make the first film from a topic. Do not create one until the user supplies a topic.
