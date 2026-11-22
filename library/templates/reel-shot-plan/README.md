# Animated Reel scene starter

Use this as an editable native AIVEE composition when a storyboard scene needs a small animated explanation. It demonstrates a signal moving through three stages, a counter update, a rejected route, a replacement route, and a loop-back. Replace every sample label and the counter value with details from the approved script; the example content is not a product claim.

Design decision: keep the familiar source-to-process-to-result layout because it makes the animation beats easy to find and replace. The labels, count, and colors are sample values; adapt them to the project and narration.

## Add it to a project

1. Create `compositions/scenes/<scene-name>/` in the AIVEE project.
2. Copy `scene.html` there as `index.html`.
3. Replace `{{COMPOSITION_ID}}`, `{{SCENE_DURATION}}`, `{{PROJECT_WIDTH}}`, and `{{PROJECT_HEIGHT}}` with a unique kebab-case id, the storyboard scene duration in seconds, and the project canvas dimensions.
4. Run `explainer scene-composition <project> <scene-number> compositions/scenes/<scene-name>/index.html --json`.
5. Review the storyboard again, render a portrait preview, and adjust the layout to the narration, presenter, and Reels controls before approval.

The AIVEE render page provides its local GSAP runtime. The template's paused timeline uses fractions of the scene duration, so it stays aligned when the narration changes. Keep all assets in the same scene folder; attaching the composition records their hashes and requires storyboard reapproval after edits.

## Shot-plan beats

| Beat | Starter action | Approximate time |
| --- | --- | --- |
| Establish | Reveal the source and processing stages | 8% |
| Explain | Move a signal between stages | 24% |
| Count | Update the sample counter | 42% |
| Correct | Strike the rejected route and reveal the replacement | 60–76% |
| Connect | Draw the loop-back ending | 84% |

These are editable animation cues, not required story structure. Keep labels short, make each movement explain a spoken idea, and remove any beat that does not help the viewer.
