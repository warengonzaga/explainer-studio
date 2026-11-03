![Explainer Studio — Make explainer videos from chat](https://ghrb.waren.build/render/banner?header=Explainer%20Studio&subheader=Make%20explainer%20videos%20from%20chat&bg=101827-243b53&color=FFFFFF&stats=false)

## 🎬 Overview

Explainer Studio is a local plugin for making narrated explainer videos from Codex or Claude Code chat. It guides you from topic and script through voice timing, storyboard review, preview, and MP4 delivery. The implementation and bundled presenter are original; [Talking Explainer](https://github.com/brewed-ops/talking-explainer) informed the workflow.

## ✨ Features

- Chat guided first run for brand, language, voice route, and avatar.
- Use your own narration or generate speech with ElevenLabs.
- Create and review word timed storyboards before rendering.
- Use an original geometric presenter or prepare a custom sprite pack.
- Render landscape or portrait video locally and run basic media checks.
- Keep prior narration and renders intact when creating a new take.

Lip movement follows voice loudness; it is not phoneme accurate. Automatic transcription and ElevenLabs require their optional runtime and account credentials.

## 🚀 Quick start

Requirements: Python 3.11+, FFmpeg, and ffprobe. Install Pillow and the CLI:

```bash
python -m pip install -e .
python scripts/explainer.py doctor
```

Install the plugin in Codex or Claude Code, invoke **Set up Explainer Studio**, then ask for a video topic in chat. Setup asks for your brand and language, voice route, and avatar. Provider keys stay in environment variables and are not saved to the profile.

For local Claude Code development, run `claude --plugin-dir <path-to-this-repo>`. Codex supports local marketplace installation from this repository.

## 🎞️ HyperFrames + GSAP motion-graphics export (optional)

Explainer Studio supports an editable HTML-native rendering path alongside the existing Pillow/FFmpeg renderer. The original Python renderer remains the default, including the built-in presenter and loudness-driven mouth animation. The HyperFrames export currently provides animated headlines, scene cards, source-word captions, optional scene images, and narration; it does **not yet** recreate the Python presenter's lip animation.

After the script, word timings, storyboard, and explicit approval:

```bash
python scripts/explainer.py export-hyperframes /path/to/project --portrait
cd /path/to/project/hyperframes-portrait
npm install
npm run lint
npm run preview
# After visually reviewing the preview:
npm run render
```

Requires Node.js 22+, FFmpeg/ffprobe, and Chrome/Chromium in addition to Python. The generated project's `package.json` pins HyperFrames 0.7.109 and GSAP 3.14.2, following the versions documented by Herk Edit Kit. Commit a lockfile for a reproducible local installation when desired. No remote GSAP CDN is used; the generated composition references its local npm installation. The exporter refuses to overwrite an existing composition directory. `--portrait` uses conservative top, right, and bottom UI margins, but review the actual platform overlays before publishing.

HyperFrames HTML is editable: use the CLI preview to review timing and motion, then lint, render, and run `explainer check` on the MP4. Do not treat structural lint as visual approval. The storyboard and voice remain the timing source; original source media is preserved.

Reference implementations: [HyperFrames](https://github.com/heygen-com/hyperframes), [Herk Edit Kit](https://github.com/nateherkai/herk-edit-kit), and [Talking Explainer](https://github.com/brewed-ops/talking-explainer). Their workflow ideas informed this integration; no third-party templates or assets are copied.

## 🎙️ Voice and avatars

Choose a recording you attach to chat or an ElevenLabs voice. For generated narration, set `ELEVENLABS_API_KEY` in the environment and provide a voice ID. No voice clone is required.

Choose the built-in presenter, the bundled **Waren** sample avatar, or a sprite pack you own. The Waren pack is based on the creator's supplied avatar references and includes four poses and five mouth states, with pose-specific mouth fitting for `present` and `celebrate`. See the [avatar pack guide](skills/avatar/references/pack.md) for manifest and image requirements. Rendering and avatar previews run locally.

## 🧭 Workflow

1. Choose a topic, audience, length, and language; review the script in chat.
2. Attach or generate narration, then transcribe it or import reviewed word timings.
3. Review the storyboard and approve it in chat.
4. Render a preview, request revisions, then render and inspect the final video.
5. Share the MP4 and editable project folder.

Run `python scripts/explainer.py --help` for CLI commands. Projects preserve source media and never overwrite existing render outputs.

## 🛠️ Development

```bash
python -m pip install -e ".[transcribe]"
python -m unittest discover -s tests -v
```

Releases follow Clean Flow: merge feature work into `dev`, then promote stable `dev` to `main`. A push to `main` runs the [Release Build Flow Action](https://github.com/wgtechlabs/release-build-flow-action) to update the changelog, sync `pyproject.toml`, and publish a GitHub Release when the commit history calls for a version bump.

## 📋 Limitations

The first version provides a deterministic template renderer and basic media checks. It does not capture microphone audio or generate images inside the plugin. Automatic transcription downloads a model on first use. Full resolution renders depend on local CPU, memory, and FFmpeg performance.

## 📄 License

Explainer Studio is licensed under the [MIT License](LICENSE).
