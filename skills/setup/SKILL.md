---
name: setup
description: Set up Explainer Studio for the first time, repair missing local tools, or update the saved creator profile. Use when a user installs Explainer Studio, asks to set it up, or starts a film without a profile.
---

# Set up Explainer Studio

Resolve the plugin root from this file (`../..`). Run `python <plugin-root>/scripts/explainer.py doctor` first. Explain missing tools in plain language. Python 3.11+, Pillow, FFmpeg, ffprobe, Node.js, and a local AI Video Editing Engine checkout are required for Engine-backed rendering; `faster-whisper` is optional until automatic transcription is needed. No published AIVEE package is required: Studio invokes the local checkout's CLI and does not import its JavaScript API. If its dependencies are missing, run `npm install` inside the Engine checkout. Use a project-local virtual environment for Python packages when possible. Do not put an API key in command arguments, chat output, or `profile.json`.

Ask the user one short grouped set of questions, offering these defaults so setup can be completed with minimal input:

1. Brand defaults to **Explainer Studio**; narration language defaults to English. Logo, colors, and output folder are optional.
2. Voice route defaults to a user-provided recording. ElevenLabs is optional and needs an API key set privately as `ELEVENLABS_API_KEY` and a voice ID. Never require a voice clone.
3. Avatar defaults to the original built-in geometric presenter. The bundled **Waren (sample)** at `<plugin-root>/assets/avatars/waren` or a user-owned sprite pack can be selected; preview the contact sheet in chat and get approval before saving either pack. See [avatar pack guide](../avatar/references/pack.md).
4. Use `AI_VIDEO_ENGINE_PATH` when it is set; otherwise ask for the local Engine checkout path. It must contain `src/cli.mjs`, and Node.js must be on `PATH`.
5. Optional Rhubarb Lip Sync executable path. When configured, Studio uses phonetic cues mapped to its five mouth states. Without it, Studio falls back to audio-level mouth timing.

Save only non-secret user choices through `python <plugin-root>/scripts/explainer.py setup [--brand ...] [--language ...] [--voice-route ...] [--avatar ...] [--engine-path ...] [--output-dir ...]`; add `--rhubarb-path`, `--avatar-pack`, `--logo`, colors, and `--cta` when chosen. Defaults are **Explainer Studio**, English, recording voice, built-in avatar, the default palette, and `~/Explainer Studio` output. If a profile exists, show the current non-secret choices with `profile`, ask only what should change, and use `--force` for the intentional update. The profile lives at `EXPLAINER_STUDIO_HOME/profile.json`, or `~/.explainer-studio/profile.json` by default. Keep every response and setup result in the chat.

Once setup succeeds, offer to make the first film from a topic. Do not create one until the user supplies a topic.
