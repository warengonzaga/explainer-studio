---
name: setup
description: Set up Explainer Studio for the first time, repair missing local tools, or update the saved creator profile. Use when a user installs Explainer Studio, asks to set it up, or starts a film without a profile.
---

# Set up Explainer Studio

Resolve the plugin root from this file (`../..`). Run `python <plugin-root>/scripts/explainer.py doctor` first. Explain missing tools in plain language. Python 3.11+, Pillow, FFmpeg, and ffprobe are required for rendering; `faster-whisper` is optional until automatic transcription is needed. Use a project-local virtual environment for Python packages when possible. Do not put an API key in command arguments, chat output, or `profile.json`.

Ask the user one short grouped set of questions:

1. Brand name and narration language. Logo, colors, and output folder are optional; offer defaults.
2. Voice route: attach their recording, or use their ElevenLabs voice with an API key set privately as `ELEVENLABS_API_KEY` and a voice ID. Never require a voice clone. The selected route must work before the first render.
3. Avatar: the original built-in geometric presenter, or a user-owned sprite pack. For a custom pack, run `avatar-preview-pack <pack> --output <image>`, show the contact sheet in chat, and get approval before saving it. See [avatar pack guide](../avatar/references/pack.md).

Save only the answers needed through `python <plugin-root>/scripts/explainer.py setup --brand ... --language ... --voice-route ... --avatar ... --output-dir ...`; add `--avatar-pack`, `--logo`, colors, and `--cta` when chosen. If a profile exists, show the current non-secret choices with `profile`, ask only what should change, and use `--force` for the intentional update. The profile lives at `EXPLAINER_STUDIO_HOME/profile.json`, or `~/.explainer-studio/profile.json` by default. Keep every response and setup result in the chat.

Once setup succeeds, offer to make the first film from a topic. Do not create one until the user supplies a topic.
