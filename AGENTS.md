# Explainer Studio agent notes

- Keep the product usable from Codex and Claude Code chat. Put deterministic media work in the shared Python engine and decisions/reviews in plugin skills.
- Keep implementation and assets original. The Talking Explainer repository is workflow inspiration only; do not copy its scripts, artwork, fonts, templates, or example film.
- Do not write credentials to project files, the creator profile, logs, or command arguments. `ELEVENLABS_API_KEY` is read from the environment only when selected.
- Preserve source narration and existing renders. New takes go into a new project; commands must refuse to overwrite user output.
- Treat the narration as the timing source. Script and storyboard review gates must be visible in chat before a final render.
- Follow `skills/create-explainer/references/motion-quality.md` for the approved visual quality baseline. Author expressive motion in an editable Engine composition and review actual encoded transitions.
- Use the bundled original presenter, adaptable v6-inspired visual style, and avatar-anchored speech-bubble captions as the out-of-box creation defaults. Keep the Waren sample and custom packs optional.
- Recommend Astra in Codex and Opus in Claude Code for best creative results; Sol and Sonnet are the respective minimum recommendations. Model selection belongs to the user's chat environment.
- Use the global Clean Commit and Clean Flow rules provided by the user. Run the CLI smoke test, skill validation, and plugin validation before sharing changes.

## Clean Flow

- Keep `main` stable and use `dev` for integration.
- Create short-lived `feature/*`, `fix/*`, `docs/*`, `chore/*`, `test/*`, or `refactor/*` branches from `dev`.
- Open feature pull requests against `dev` and squash merge them.
- Promote stable `dev` to `main` with a regular merge commit and a release title following Clean Commit.
- Do not commit directly to `main` or `dev`; delete feature branches after merge.
- Apply only existing repository labels to pull requests.

## Release workflow

- `.github/workflows/release.yml` runs only on pushes to `main` after a `dev` to `main` release merge.
- Keep the Release Build Flow Action's `main-branch` input aligned with the production branch.
- The action may update `CHANGELOG.md`, version manifests, tags, and GitHub Releases; review its permissions and configuration before changing them.
