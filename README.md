![Explainer Studio — Make explainer videos from chat](https://ghrb.waren.build/render/banner?header=Explainer%20Studio&subheader=Make%20explainer%20videos%20from%20chat&bg=101827-243b53&color=FFFFFF&stats=false)

## 🎬 Overview

Explainer Studio is a local plugin for making narrated explainer videos from Codex or Claude Code chat. It guides you from topic and script through voice timing, storyboard review, preview, and MP4 delivery. Studio owns the explainer workflow and avatar assets; the generic [AI Video Editing Engine](https://github.com/warengonzaga/ai-video-editing-engine) owns final timeline composition and rendering. The implementation and bundled presenter are original; [Talking Explainer](https://github.com/brewed-ops/talking-explainer) informed the workflow.

## ✨ Features

- Chat guided first run for brand, language, voice route, and avatar.
- Use your own narration or generate speech with ElevenLabs.
- Create and review word timed storyboards before rendering.
- Use an original geometric presenter or prepare a custom sprite pack.
- Compose scenes, avatar states, and narration in an editable Engine timeline.
- Render landscape or portrait video through the Engine and run basic media checks.
- Keep prior narration and renders intact when creating a new take.

Rhubarb Lip Sync can provide phonetic mouth cues mapped to the five bundled mouth states. Without Rhubarb, mouth timing follows voice loudness. Automatic transcription and ElevenLabs require their optional runtime and account credentials.

## 🚀 Quick start

Requirements: Python 3.11+, Pillow, FFmpeg, ffprobe, Node.js 22+, and a local AI Video Editing Engine checkout. A published AIVEE package is not required: Studio calls the checkout's CLI with `node <engine-path>/src/cli.mjs` and does not import its JavaScript API. Run `npm install` once inside that checkout to install its local dependencies, then add it to setup with `--engine-path`; `AI_VIDEO_ENGINE_PATH` can override the saved path for a single session. Install Pillow and the Studio CLI:

```bash
python -m pip install -e .
python scripts/explainer.py doctor
```

Install the plugin in Codex or Claude Code, invoke **Set up Explainer Studio**, then ask for a video topic in chat. The starter profile defaults to the **Explainer Studio** brand, English, recording voice, built-in geometric avatar, default colors, and `~/Explainer Studio` output. Set `AI_VIDEO_ENGINE_PATH` or provide the local Engine checkout path during setup. A Rhubarb executable is optional for phonetic mouth cues. Provider keys stay in environment variables and are not saved to the profile.

For local Claude Code development, run `claude --plugin-dir <path-to-this-repo>`. Codex supports local marketplace installation from this repository.

## 🎙️ Voice and avatars

Choose a recording you attach to chat or an ElevenLabs voice. For generated narration, set `ELEVENLABS_API_KEY` in the environment and provide a voice ID. No voice clone is required.

Choose the built-in presenter, the bundled **Waren** sample avatar, or a sprite pack you own. The Waren pack is based on the creator's supplied avatar references and includes four poses and five mouth states, with pose-specific mouth fitting for `present` and `celebrate`. See the [avatar pack guide](skills/avatar/references/pack.md) for manifest and image requirements. Rendering and avatar previews run locally.

## 🧭 Workflow

1. Choose a topic, audience, length, and language; review the script in chat.
2. Attach or generate narration, then transcribe it or import reviewed word timings.
3. Review the storyboard and approve it in chat.
4. Render a preview through the Engine, request revisions, then render and inspect the final video. Use `render-legacy` only to compare against the old Studio compositor.
5. Share the MP4 and editable project folder.

Run `python scripts/explainer.py --help` for CLI commands. Projects preserve source media and never overwrite existing render outputs.

## 🛠️ Development

```bash
python -m pip install -e ".[transcribe]"
python -m unittest discover -s tests -v
```

Releases follow Clean Flow: merge feature work into `dev`, then promote stable `dev` to `main`. A push to `main` runs the [Release Build Flow Action](https://github.com/wgtechlabs/release-build-flow-action) to update the changelog, sync `pyproject.toml`, and publish a GitHub Release when the commit history calls for a version bump.

## 📋 Limitations

The first version provides a deterministic template renderer and basic media checks. It does not capture microphone audio or generate images inside the plugin. Automatic transcription downloads a model on first use. The five-state sample avatar groups related phonetic cues; a pack with dedicated Rhubarb A-H artwork can improve articulation detail. Full resolution renders depend on local CPU, memory, and FFmpeg performance.

## 📄 License

Explainer Studio is licensed under the [MIT License](LICENSE).
