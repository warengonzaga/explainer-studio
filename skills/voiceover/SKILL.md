---
name: voiceover
description: Select and import narration for Explainer Studio from a user-provided recording or a connected provider capability. Use before every explainer narration.
---

# Narration selection

Read `voice_provider_default` from the Studio profile with `profile --json` (`data.voice_provider_default`).

- If it is `ask` or missing, ask which source to use for this generation: a recording file supplied by the user, ElevenLabs, Higgsfield, or Suno.
- If it names a provider or `recording`, use that choice by default. A user may override it for one film; do not change the saved preference unless asked.
- Check that the selected provider's tools are actually available in the current Codex or Claude Code session. A skill or account name alone does not prove a callable connection exists.
- If unavailable, give the provider's official connection guide and ask whether to connect it or choose another source. Never silently fall back to another provider.
- Keep the approved script unchanged. Do not invoke generation until the script is approved and the user has selected the provider through this default-or-per-generation flow.
- Before using a paid provider, state which service will receive the script and that generation may consume the account's paid credits or quota. Check the provider's current account pricing/credit display; do not invent a price or imply the service is free. Continue under the user's saved provider preference or explicit per-generation choice, while honoring any additional confirmation required by the host or provider.
- Do not collect API keys, account passwords, or voice credentials in chat or Studio files. Let the connected host/provider handle authentication. Never clone a voice without the user's explicit request and rights to that voice.
- If `recording` is selected but no recording file is available, ask the user to provide one or choose another source; never silently switch.
- Return generated audio as an accessible local file. If the provider returns only a hosted or expiring link, tell the user to download and attach the audio in chat before continuing.
- Once narration is ready, create the AIVEE project with `init <slug> --script <approved-script-file> --json` and register the narration with `attach-voice <project> <audio-file> --json`. Preserve prior takes by creating a new project for each new narration take.

Use the selected provider guide: [ElevenLabs](../elevenlabs-voiceover/SKILL.md), [Higgsfield](../higgsfield-voiceover/SKILL.md), or [Suno](../suno-voiceover/SKILL.md). These providers must be callable through the active Codex or Claude Code host. Studio does not integrate their APIs directly. Local text-to-speech is not supported yet; do not present it as an available source.
