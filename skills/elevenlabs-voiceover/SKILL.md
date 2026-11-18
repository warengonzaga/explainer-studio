---
name: elevenlabs-voiceover
description: Generate explainer narration with ElevenLabs through a connected Codex or Claude Code capability, then import its audio into Explainer Studio.
---

# ElevenLabs narration

Follow the [voiceover selection workflow](../voiceover/SKILL.md). Use only a callable ElevenLabs capability connected to the current host; Explainer Studio does not call the ElevenLabs API directly or store an API key.

Before generation, disclose that the approved script will be sent to ElevenLabs and that generation can use paid account credits or quota. Use the provider's current credit display rather than quoting stale prices. Preserve the approved wording, chosen voice, language, and pronunciation guidance. Do not clone a voice unless explicitly requested and authorized.

If ElevenLabs is unavailable, direct the user to the [official ElevenLabs MCP documentation](https://elevenlabs.io/docs/eleven-api/resources/mcp-server) and its [connection page](https://elevenlabs.io/mcp). Ask them to connect through the active host, then verify callable tools are present before generating. Never request credentials in chat.

Return an audio file that the Studio workflow can access. If the result is an expiring hosted link, have the user download and attach the file, then continue with `attach-voice`.
