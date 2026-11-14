![Explainer Studio — Make explainer videos from chat](https://ghrb.waren.build/render/banner?header=Explainer%20Studio&subheader=Make%20explainer%20videos%20from%20chat&bg=101827-243b53&color=FFFFFF&stats=false)

## 🎬 Overview

Explainer Studio is an agent plugin for creating narrated explainer videos from Codex or Claude Code. It guides the work from topic and script through narration timing, storyboard review, preview, and MP4 delivery. Studio owns the explainer workflow and original avatar assets. It depends on [AIVEE](https://github.com/warengonzaga/ai-video-editing-engine) for editable timeline composition and video rendering.

## ✨ Features

- Chat guided first run for brand, language, voice route, and avatar.
- Use your own narration or generate speech with ElevenLabs.
- Create and review word timed storyboards before rendering.
- Use the bundled Emo robot presenter or prepare a custom sprite pack.
- Start with the bundled presenter, a clean motion-graphics style, and phrase captions in a speech bubble beside the avatar.
- Compose scenes, avatar states, and narration in an editable AIVEE timeline.
- Render landscape or portrait video through AIVEE and run basic media checks.
- Keep prior narration and renders intact when creating a new take.

Rhubarb Lip Sync can provide phonetic mouth cues mapped to the five bundled mouth states. Without Rhubarb, mouth timing follows voice loudness. Automatic transcription and ElevenLabs require their optional runtime and account credentials.

For creative planning and animation authoring, our project recommendations are:

| Chat environment | Recommended for best results | Minimum recommended |
| --- | --- | --- |
| Codex | Astra | Sol |
| Claude Code | Opus | Sonnet |

Select the model in your chat environment. These recommendations guide creative work; rendering uses the locally installed AIVEE CLI. Every video still needs visual review.

The visual quality baseline is a deliberately composed scene with readable artwork, narration-timed object movement, and coherent visual progression. By default, show short narration-synced phrases in a speech bubble beside the presenter, with its tail pointing toward the avatar; keep it clear of the main visual and Reels controls. AIVEE provides this as a configurable caption layout. See the [motion quality guide](skills/create-explainer/references/motion-quality.md) for authoring and review requirements.

## 🚀 Quick start

Requirements: Python 3.11+, Node.js 22+ with npm, FFmpeg, ffprobe, and Chrome or Edge. Node.js and npm are needed for Studio to manage its required AIVEE dependency. When running from a source checkout, bootstrap Studio's managed Python environment:

```bash
python scripts/explainer.py bootstrap
```

For normal use, install the plugin in Codex or Claude Code and invoke **Set up Explainer Studio**. Setup bootstraps Studio's Python dependencies, checks the machine, installs the supported `aivee` npm package when needed, and asks AIVEE to create its workspace. Users do not need to install AIVEE separately. The default workspace is `~/AIVEE`; it contains `Studios/Explainer/Library/Avatar Packs` and `Studios/Explainer/Projects`. The starter profile defaults to the **Explainer Studio** brand, English, recording voice, the bundled Emo robot avatar, and default colors. A Rhubarb executable is optional for phonetic mouth cues. Provider keys stay in environment variables and are not saved to the profile.

For a local checkout, add this repository as a plugin marketplace and install `explainer-studio`:

```text
Claude Code: /plugin marketplace add warengonzaga/explainer-studio
Claude Code: /plugin install explainer-studio@explainer-studio
Codex:       codex plugin marketplace add warengonzaga/explainer-studio
Codex:       codex plugin add explainer-studio@explainer-studio
```

Claude Code also supports local development with `claude --plugin-dir <path-to-this-repo>`.

## 🎙️ Voice and avatars

Choose a recording you attach to chat or an ElevenLabs voice. For generated narration, set `ELEVENLABS_API_KEY` in the environment and provide a voice ID. No voice clone is required.

Use the bundled **Emo** robot avatar by default, choose the **Waren** sample avatar, or install a sprite pack you own. Emo includes four poses, matching blink frames, and five screen-mouth states. Waren is based on the creator's supplied avatar references and includes four poses and five mouth states. See the [avatar pack guide](skills/avatar/references/pack.md) for manifest and image requirements. Rendering and avatar previews run locally.

## 🧭 Workflow

1. Choose a topic, audience, length, and language; review the script in chat.
2. Attach or generate narration, then transcribe it or import reviewed word timings.
3. Review the storyboard and approve it in chat.
4. Render a preview through AIVEE, request revisions, then render and inspect the final video. AIVEE owns all composition and rendering.
5. Share the MP4 and AIVEE-owned project folder; the editable timeline, registered media, renders, and Studio workflow files are kept together in the project. Studio workflow files live under `studio-data/explainer/`.

Run `python scripts/explainer.py --help` for CLI commands. Projects preserve source media and never overwrite existing render outputs. Previous renders remain available for comparison; new takes use a separate project.

## 🛠️ Development

```bash
python -m pip install -e ".[transcribe]"
python -m unittest discover -s tests -v
```

Releases follow Clean Flow: merge feature work into `dev`, then promote stable `dev` to `main`. A push to `main` runs the pinned [Release Build Flow Action](https://github.com/wgtechlabs/release-build-flow-action) (`v1.8.0`) to update the changelog, sync `pyproject.toml`, and publish a GitHub Release when the commit history calls for a version bump.

## 📋 Limitations

Studio guides story, narration timing, storyboard review, and explainer-specific assets; AIVEE handles editable timeline composition and rendering. It does not capture microphone audio or generate images inside the plugin. Automatic transcription downloads a model on first use. The five-state sample avatar groups related phonetic cues; a pack with dedicated Rhubarb A-H artwork can improve articulation detail. Full resolution renders depend on local CPU, memory, and FFmpeg performance.

## 📄 License

Explainer Studio is licensed under the [MIT License](LICENSE).
