---
name: higgsfield-voiceover
description: Generate explainer narration with Higgsfield through a connected Codex or Claude Code capability, then import its audio into Explainer Studio.
---

# Higgsfield narration

Follow the [voiceover selection workflow](../voiceover/SKILL.md). Use only a callable Higgsfield capability connected to the current host; Explainer Studio does not call a vendor API directly or store account credentials.

Before generation, disclose that the approved script will be sent to Higgsfield and that generation can use paid workspace credits or quota. Check the current account credit display instead of quoting stale prices. Preserve the approved wording and selected voice. Do not clone a voice unless explicitly requested and authorized.

If Higgsfield is unavailable, direct the user to the [official integrations guide](https://higgsfield.ai/enterprise-help-center/platform/integrations) and the [official Higgsfield skills repository](https://github.com/higgsfield-ai/skills). Ask them to connect or install the provider's supported integration in the active host, then verify callable tools are present before generating. Never request credentials in chat.

Return an audio file that the Studio workflow can access. If the result is available only in the provider's library, have the user download and attach it, then continue with `attach-voice`.
