---
name: create-explainer
description: Make or revise a narrated explainer video from a topic, script, recording, or storyboard using Explainer Studio. Use for explainer video creation, voice-timed scenes, presenter animation, draft previews, and final render.
---

# Create an explainer

Use the bundled CLI at `python <plugin-root>/scripts/explainer.py` (the plugin root is `../..` from this file). Keep the creative decisions and review in the chat. If no creator profile exists, run the [setup skill](../setup/SKILL.md) first.

## Film workflow

1. Ask for the topic, target audience, desired length, and any facts or sources the user wants included. Infer reasonable defaults from the request. Research claims when facts could have changed. Write a short script in the saved language and speaking style, with one paragraph per scene. Show it in chat and wait for the user's approval before generating narration.
2. `init` a project under the saved output folder, then write the approved script to `script.txt`. Never overwrite an existing project or source media. If the user brings a recording, `attach-voice` it. If they selected ElevenLabs, run `synthesize` only after the script is approved and a configured voice ID and API key are available. The user's recording or selected TTS output is the film's timing source.
3. Run `transcribe` to create `words.json` with word timestamps; `import-words` supports a reviewed external word-timing file. Check that the transcript matches the script. Run `storyboard` to align paragraphs. Edit `storyboard.json` with concise headlines, verified visual labels, suitable poses, and optional project-owned images. Show the scene list and a preview plan in chat. Wait for an explicit yes, then run `approve`.
4. Run `render --preview`. Display the Engine-rendered preview and ask for specific revisions. Editing the storyboard invalidates its approval hash until reviewed again. Once accepted, run `render` for the full file, then `check` and `contact-sheet`; inspect the contact sheet in chat. Use `sync-check` when faster-whisper is available to compare rendered speech with the source. Deliver the MP4 path and the editable Studio and Engine project folders in chat. Use `render-legacy` only to compare against the old Studio compositor. If a custom avatar is requested, follow the [avatar skill](../avatar/SKILL.md) before rendering. For a portrait cut, render `render --portrait --preview`, review its layout, then render `render --portrait`. For a new take, run `retime` into a new project and review the new storyboard.

Only the user approves the script and storyboard. The agent may prepare files and run read-only checks while waiting. If a render fails, report the exact failed step; do not call the film complete. Engine-backed renders use Rhubarb phonetic cues when configured and map them to the bundled five mouth states; otherwise they use voice loudness. Obtain rights to user-supplied music, images, logos, and voice recordings before publication.
