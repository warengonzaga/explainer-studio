---
name: suno-voiceover
description: Generate spoken explainer narration with Suno through a connected Codex or Claude Code capability, then import its audio into Explainer Studio.
---

# Suno narration

Follow the [voiceover selection workflow](../voiceover/SKILL.md). Use a callable Suno speech capability connected to the current host. Do not substitute music generation for speech narration. Explainer Studio does not call a vendor API directly or store account credentials.

Before generation, disclose that the approved script will be sent to Suno and that generation can use paid account credits or quota. Check the current account credit display instead of quoting stale prices. Preserve the approved wording and requested speech style. Do not clone a voice unless explicitly requested and authorized.

If Suno speech is unavailable, direct the user to the [official Suno MCP Beta setup guide](https://help.suno.com/en/articles/14551361). Ask them to connect it through a supported client, then verify that a speech-generation capability is callable before proceeding. Never request credentials in chat.

Return an audio file that the Studio workflow can access. If the result is only in the Suno Library or is not exposed as a local file, have the user download and attach it, then continue with `attach-voice`.
