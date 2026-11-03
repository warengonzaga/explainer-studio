# Explainer Studio

Explainer Studio is a local plugin for creating narrated explainer videos from Codex or Claude Code chat. Its skills handle the creator setup, script and storyboard review, avatar preparation, and revision. A bundled Python tool handles word timing, audio-reactive mouth animation, scene composition, and MP4 rendering. The project is an independent implementation inspired by the workflow in [Talking Explainer](https://github.com/brewed-ops/talking-explainer); it does not contain that project's code or artwork.

## Creator experience

1. Install the plugin and run **Set up Explainer Studio**. The setup skill checks the machine and asks for brand/language, voice route, and avatar. Settings are saved in `~/.explainer-studio/profile.json` (or `EXPLAINER_STUDIO_HOME`). API keys are never stored there.
2. Ask the plugin to make an explainer about a topic. Review the script in chat. The voice route is either an attached recording or an ElevenLabs voice configured by the user.
3. The plugin times spoken words, plans one scene per script paragraph, and shows the storyboard for approval. It then renders a small preview for in-chat review and a final MP4 after revisions.
4. A user can provide a custom sprite pack or use the original geometric presenter included in the renderer. An avatar contact sheet makes mouth and pose placement reviewable.

The same project can produce a 16:9 film and a separate 9:16 output. A new take creates a new retimed project so the previous render stays intact. The built-in mouth shapes follow voice loudness, not phonemes.

## Requirements

- Python 3.11+
- FFmpeg and ffprobe on `PATH`
- Pillow (`pip install -e .`)
- `faster-whisper` for automatic word timing (`pip install -e ".[transcribe]"`); a reviewed `words.json` can be imported instead
- Optional ElevenLabs account and `ELEVENLABS_API_KEY` for generated narration

Run `python scripts/explainer.py doctor` for a machine check. Automatic transcription downloads a model on first use. Rendering, custom images, and the default avatar run locally.

## Plugin installation

The root `plugin.json` and `.codex-plugin/plugin.json` package the Codex skills and onboarding skill. `.claude-plugin/plugin.json` packages the same skills for Claude Code. The marketplace files support local development; a future private GitHub release can be registered as a marketplace by users with repository access.

For local Claude Code development, run `claude --plugin-dir <path-to-this-repo>`. For Codex, add the repo's local marketplace to the plugin browser. In either host, invoke the setup skill once, then ask in chat for an explainer. No separate editing application is required.

## CLI reference

The chat skills call these commands; users can also run them directly for troubleshooting:

```text
python scripts/explainer.py doctor
python scripts/explainer.py setup --brand "My Brand" --language en --voice-route recording
python scripts/explainer.py init projects/my-film --title "My Film"
python scripts/explainer.py attach-voice projects/my-film narration.mp3
python scripts/explainer.py transcribe projects/my-film
python scripts/explainer.py storyboard projects/my-film
python scripts/explainer.py approve projects/my-film
python scripts/explainer.py avatar-preview projects/my-film
python scripts/explainer.py render projects/my-film --preview
python scripts/explainer.py render projects/my-film
python scripts/explainer.py check projects/my-film projects/my-film/renders/final.mp4
python scripts/explainer.py contact-sheet projects/my-film projects/my-film/renders/final.mp4
python scripts/explainer.py sync-check projects/my-film projects/my-film/renders/final.mp4
```

`storyboard.json` is editable before approval. Each scene has start/end times, a headline, body, pose, optional `visual_label`, and optional project-relative `asset` image. `words.json` is a list of `{ "text": "word", "start": 1.2, "end": 1.5 }`. The storyboard records hashes of the script and voice; changing either requires planning again. Render output is never overwritten.

Use `render --portrait` for a separate vertical layout. Use `retime <old-project> <new-project> --voice <new-take>` to keep the previous project and carry scene choices into a new timing plan. These routes still require a preview and review before delivery.

## Current limits

This first version provides a deterministic template renderer and basic checks. Automatic transcription and ElevenLabs synthesis require the optional provider/runtime and have not been verified with live accounts. There is no native microphone capture or image generation inside the plugin; the user can attach media in chat, and an agent may use an available image generation tool to create original scene/pose assets. The full 1080p60 render is slower than preview and depends on local CPU/GPU/FFmpeg performance.
