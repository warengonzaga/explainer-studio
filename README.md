![Explainer Studio — Make explainer videos from chat](https://ghrb.waren.build/render/banner?header=Explainer%20Studio&subheader=Make%20explainer%20videos%20from%20chat&bg=101827-243b53&color=FFFFFF&stats=false)

## 🎬 Overview

Explainer Studio is an agent plugin for creating narrated explainer videos from Codex or Claude Code. It guides the work from topic and script through narration timing, storyboard review, preview, and MP4 delivery. Studio owns the explainer workflow and original avatar assets. It depends on [AIVEE](https://github.com/warengonzaga/ai-video-editing-engine) for editable timeline composition and video rendering.

## ✨ Features

- Chat guided first run for brand, language, narration preference, and avatar.
- Use your own narration or connected ElevenLabs, Higgsfield, or Suno capabilities.
- Create and review word timed storyboards before rendering.
- Use custom per-scene HTML and GSAP compositions in Studio renders.
- Use the bundled Emo robot presenter or prepare a custom sprite pack.
- Start with the bundled presenter, a clean motion-graphics style, and phrase captions in a speech bubble beside the avatar.
- Compose scenes, avatar states, and narration in an editable AIVEE timeline.
- Render landscape or portrait video through AIVEE and run basic media checks.
- Keep prior narration and renders intact when creating a new take.

Supported narration sources are a recording file supplied by the user, or a connected ElevenLabs, Higgsfield, or Suno capability in Codex or Claude Code. Studio guides provider use but does not call their APIs directly or store provider credentials. Setup defaults to asking which source to use each time, or you can save a preferred source. Provider generation may consume paid credits; check the selected provider's account costs before generating. See the [voiceover skill](skills/voiceover/SKILL.md) and provider guides for setup. Local text-to-speech is not supported yet.

Rhubarb Lip Sync can provide phonetic mouth cues mapped to the five bundled mouth states. Without Rhubarb, mouth timing follows voice loudness. Automatic transcription requires its optional runtime.

For creative planning and animation authoring, our project recommendations are:

| Chat environment | Recommended for best results | Minimum recommended |
| --- | --- | --- |
| Codex | Astra | Sol |
| Claude Code | Opus | Sonnet |

Select the model in your chat environment. These recommendations guide creative work; rendering uses the locally installed AIVEE CLI. Every video still needs visual review.

The visual quality baseline is a deliberately composed scene with readable artwork, narration-timed object movement, and coherent visual progression. By default, show short narration-synced phrases in a speech bubble beside the presenter, with its tail pointing toward the avatar; keep it clear of the main visual and Reels controls. AIVEE provides this as a configurable caption layout. See the [motion quality guide](skills/create-explainer/references/motion-quality.md) for authoring and review requirements.

For a reusable animated scene starter with timed signal movement, a counter, route change, and loop-back, see [`library/templates/reel-shot-plan`](library/templates/reel-shot-plan/README.md). It attaches to the existing storyboard approval and preview flow.

Create a portrait project with `explainer init <project> --format reel`. This sets both the Studio project and AIVEE canvas to 1080 × 1920 at 30 fps. Rendering a Reel project automatically uses portrait placement and safe-zone checks; existing landscape projects can still opt in with `render --portrait`.

Caption presets are saved once in the creator profile and applied by default to new and existing projects. The default uses bold white captions, a yellow keyword highlight, a soft shadow, and Bebas Neue for scene hooks. Set the caption font, keyword color, placement, or hook font with `setup --caption-font`, `--caption-keyword-color`, `--caption-x`, `--caption-y`, `--caption-width`, `--caption-height`, and `--hook-font`. Placement values are normalized from 0 to 1; portrait renders still enforce the Reels safe area. Studio warns when a configured font is missing or cannot be checked. Project and scene caption options can override the profile preset.

## 🚀 Quick start

Requirements: Python 3.11+, Node.js 22+ with npm, FFmpeg, ffprobe, and Chrome or Edge. Studio uses npm's global AIVEE installation. When running from a source checkout, bootstrap Studio's managed Python environment:

```bash
python scripts/explainer.py bootstrap
```

For normal use, install the plugin in Codex or Claude Code and invoke **Set up Explainer Studio**. Setup bootstraps Studio's Python dependencies, checks the machine, reuses a compatible global AIVEE CLI, or runs `npm install --global aivee@latest` when AIVEE is missing. AIVEE is shared globally with other Studios; Studio does not keep a private copy or silently replace an incompatible global installation. If an installed version is incompatible, update it with `npm install --global aivee@latest` and rerun setup. The default workspace is `~/AIVEE`; it contains `Studios/Explainer/Library/Avatar Packs` and `Studios/Explainer/Projects`. The starter profile defaults to the **Explainer Studio** brand, English, ask-before-generation voice selection, the bundled Emo robot avatar, and default colors. A Rhubarb executable is optional for phonetic mouth cues. Provider access is managed by the active Codex or Claude Code host and is not saved to the profile.

## Install and use in chat

### Codex

```text
codex plugin marketplace add warengonzaga/explainer-studio
codex plugin add explainer-studio@explainer-studio
```

Open a Codex chat with the plugin enabled and start with **Set up Explainer Studio** (or ask Codex to set it up). After setup, describe the video you want, for example: “Create a 60-second Reel explaining open source.” Codex guides you through the script, narration, storyboard approval, and render review in chat.

### Claude Code

In a Claude Code session, add the marketplace and install the plugin:

```text
/plugin marketplace add warengonzaga/explainer-studio
/plugin install explainer-studio@explainer-studio
```

Run `/explainer-studio:setup` for first-time setup. To make a video, run `/explainer-studio:create-explainer` or describe the video in chat and let the skill guide you through the workflow.

For local plugin development, Claude Code also supports `claude --plugin-dir <path-to-this-repo>`.

## 🎙️ Voice and avatars

Choose a narration recording file you provide, or a connected provider capability for ElevenLabs, Higgsfield, or Suno. Setup lets you save a preferred source or ask each time. Provider availability depends on the active Codex or Claude Code host; accounts and credits are managed by those services. Studio does not store provider API keys. Local text-to-speech is not supported yet. No voice clone is required.

Use the bundled **Emo** robot avatar by default, choose the **Waren** sample avatar, or install a sprite pack you own. The free sample packs are in [`library/avatars`](library/avatars) and each includes an MIT license. Emo includes four poses, matching blink frames, and five screen-mouth states. Waren is based on the creator's supplied avatar references and includes four poses and five mouth states. See the [avatar pack guide](skills/avatar/references/pack.md) for manifest and image requirements. Rendering and avatar previews run locally.

## 🧭 Workflow

1. Choose a topic, audience, length, and language; review the script in chat.
2. Attach or generate narration, then transcribe it or import reviewed word timings.
3. Review the storyboard in chat. For a custom scene, author `compositions/scenes/<name>/index.html` in the AIVEE project and attach it with `scene-composition <project> <scene-number> compositions/scenes/<name>/index.html --json`; review and approve the updated storyboard.
4. Render a preview through AIVEE, request revisions, then render and inspect the final video. `check <project> <video>` reports ffprobe details, scans every encoded frame for one-frame A-B-A flashes, and checks attached portrait compositions at 15 samples per second. It also runs speech sync when faster-whisper is installed; otherwise run `sync-check` separately. AIVEE owns all composition and rendering.
5. Share the MP4 and AIVEE-owned project folder; the editable timeline, registered media, renders, and Studio workflow files are kept together in the project. Studio workflow files live under `studio-data/explainer/`.

`status <project>` reports whether voice, words, storyboard, approved, preview, and final are done, the path of each existing file, and the next safe command. Preview and final paths are the default files in `renders/` (`draft-engine.mp4`, `draft-portrait-engine.mp4`, `final-engine.mp4`, and `final-portrait-engine.mp4`).

`scene-composition <project> <scene-number> <html-path>` attaches a project-owned AIVEE HTML/GSAP composition to a storyboard scene. Keep the composition and its local assets in `compositions/scenes/<name>/`; it replaces that scene's `visual_cues` and renders on its narration timing under Studio's avatar and captions. The command records a hash of the scene folder and clears storyboard approval. Reattach and review the storyboard after changing any file in that folder.

`safe-check <project>` samples visible text and graphic bounds in every attached portrait HTML composition against the approved Reels safe area. `check <project> <video>` includes the same composition check and scans decoded frames for isolated A-B-A flashes. The flicker scan targets one-frame flashes; it does not replace watching the encoded video and reviewing its motion.

`stills <project> --at 0.6,4.9 --sheet` exports full-resolution PNGs at the requested seconds from the latest final render (or latest preview if no final exists). Pass `--video <path>` to choose a specific render, `--output <directory>` to choose a destination, and `--sheet` to add a timestamp-labeled contact sheet. Existing files are never overwritten.

`init <project> --theme-from <image...>` derives the new project's background, ink, and accent colors from one or more PNG, JPEG, or other Pillow-readable images. Transparent pixels are sampled over white. The palette is stored with the project and does not change the saved profile.

`transcribe <project> --model small --language en` creates word timings from narration. It uses the project's `studio-data/explainer/script.txt` as an optional recognition hint; pass `--script <path>` to use another text file. The script guides recognition but does not force words or timings to match it. Choose another faster-whisper model size with `--model` when accuracy or local compute needs differ.

Run `python scripts/explainer.py --help` for CLI commands. Projects preserve source media and never overwrite existing render outputs. Previous renders remain available for comparison; new takes use a separate project.

## JSON output

Add `--json` to a command to print one object on stdout. On `engine`, the flag may come before or after the engine arguments.

```json
{
  "ok": true,
  "command": "storyboard",
  "data": {"scenes": 4, "review_gate": "storyboard"},
  "next_steps": [],
  "error": null
}
```

`ok` is true when the command finished. `command` is the subcommand name. `data` is that command's result. `next_steps` lists shell-quoted commands that are safe to run now, and each one includes `--json`. `error` is null on success and a string when the command failed. A failed command still prints this object and exits non-zero. A usage error with `--json` prints the same object and exits 2.

`next_steps` never includes `init`, `approve`, `setup --avatar-pack`, or a final `render` (a render without `--preview`). Those wait for a chat review. `data.review_gate` is `storyboard` or `preview` while that review is open. A draft preview lists `contact-sheet` as its next step. `init` leaves `next_steps` empty when it did not receive a narration file (`data.voice_attached` is false). Without `--json`, commands print the same plain text as before, and errors go to stderr.

`status` uses the same object. `data.project` is the project path. `data.voice_attached` is true when the narration file is present. `data.stages` has `voice`, `words`, `storyboard`, `approved`, `preview`, and `final`. Each stage has `done` and `paths`. `paths` lists files that exist. The approved stage uses the storyboard file. While narration is missing, or a storyboard review is open, `next_steps` is empty. After approval, the next command is `check` when a final file exists, `contact-sheet` when only a preview exists (`review_gate` is `preview`), and `render --preview` when neither render exists.

## 🛠️ Development

```bash
python -m pip install -e ".[transcribe]"
python -m unittest discover -s tests -v
```

Releases follow Clean Flow: merge feature work into `dev`, then promote stable `dev` to `main`. A push to `main` runs the pinned [Release Build Flow Action](https://github.com/wgtechlabs/release-build-flow-action) (`v1.8.0`) to update the changelog, sync `pyproject.toml`, and publish a GitHub Release when the commit history calls for a version bump.

## 📋 Limitations

Studio guides story, narration timing, storyboard review, and explainer-specific assets; AIVEE handles editable timeline composition and rendering. It does not capture microphone audio or generate images inside the plugin. Automatic transcription downloads a model on first use. The five-state sample avatar groups related phonetic cues; a pack with dedicated Rhubarb A-H artwork can improve articulation detail. Full resolution renders depend on local CPU, memory, and FFmpeg performance.

## 📄 License

Explainer Studio is licensed under the [GNU General Public License v3.0 only](LICENSE). The avatar packs in [`library/avatars`](library/avatars) are separately licensed under MIT; each pack includes its own `LICENSE` file and manifest entry. Third-party tools, models, and media keep their own licenses and notices. AIVEE is an independent dependency and retains its MIT license.
