# Scene starters

These HTML scenes are editable AIVEE compositions. Each one keeps a paused GSAP timeline on `window.__timelines.root` and takes its timing from the storyboard scene.

`explainer templates` lists every starter in this folder, including the [animated shot plan](reel-shot-plan/README.md).

| Starter | Use |
| --- | --- |
| [hook-title](hook-title/README.md) | Hook, title, and one supporting line |
| [numbered-steps](numbered-steps/README.md) | Three numbered steps |
| [before-after](before-after/README.md) | Earlier state beside a later state |
| [badge-callout](badge-callout/README.md) | Badge and the line it calls out |

Add one to a project:

```text
explainer add-template <project> <starter> --scene <number> --set key=value
```

`--scene` reads that scene's duration and attaches `compositions/scenes/<starter>/index.html`. Attaching clears storyboard approval. Omit `--scene` and pass `--duration <seconds>` to write the file without attaching it. `--name <slug>` chooses the scene folder. The command refuses to replace an existing scene file.

The filled scene uses the project background, ink, and accent, the project canvas size, and the project language when it is a language tag. Its document id is `root`, which portrait safe-check seeks. A vertical canvas uses the portrait visual region inside the Reels safe area. Other canvases use the taller open band beside the avatar, above or below the captions. That caption box is the one rendering uses: the format default, then profile placement, project placement, and the attached scene's caption position. Omitted text fields keep the short defaults in each starter. The starters do not name a brand, person, or organization.

On-screen copy is HTML text. Use `--set` once per field, for example `--set title="North star"`.
