# Explainer Studio agent notes

- Keep the product usable from Codex and Claude Code chat. Put deterministic media work in the shared Python engine and decisions/reviews in plugin skills.
- Keep implementation and assets original. The Talking Explainer repository is workflow inspiration only; do not copy its scripts, artwork, fonts, templates, or example film.
- Do not write credentials to project files, the creator profile, logs, or command arguments. `ELEVENLABS_API_KEY` is read from the environment only when selected.
- Preserve source narration and existing renders. New takes go into a new project; commands must refuse to overwrite user output.
- Treat the narration as the timing source. Script and storyboard review gates must be visible in chat before a final render.
- Use the global Clean Commit and Clean Flow rules provided by the user. Run the CLI smoke test, skill validation, and plugin validation before sharing changes.
