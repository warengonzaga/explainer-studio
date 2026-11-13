# Motion quality baseline

The creator approved the open-source Reel v6 presentation as Studio's visual quality baseline. Apply its craft principles to each topic, rather than repeating its colors, diagrams, or layout in every film. Its strength was a readable, original scene whose objects developed with the narration, supported by the presenter and captions.

## Out-of-box creative defaults

- Start with the original bundled presenter and the adaptable visual craft described below. The Waren avatar pack is an optional sample, not the default identity for every creator.
- Show narration captions as compact speech bubbles beside the avatar, with the tail clearly pointing to the speaker. Use short timed phrases, not a full-screen subtitle bar or long paragraph inside the bubble. Use AIVEE's configurable `speechBubble` layout and tune its position and tail for the shot.
- Keep the bubble's size and position consistent across adjacent phrases. Place it clear of the face, primary explanatory graphic, and platform controls; reposition it only when the composition requires it.
- Highlight the currently spoken word subtly within the bubble when supported. Do not let word emphasis resize text into collisions or make the bubble jump.
- Let the user replace the avatar, art direction, colors, or caption treatment. Defaults should make a topic-to-storyboard start easy without constraining the approved storyboard.

## Reels framing

- For 1080 × 1920 Reels, keep essential content inside x=100–886 px and y=250–1480 px. Leave the bottom 440 px and top 250 px clear for interface overlays; keep extra clearance on the right for the action rail. These are conservative Studio authoring bounds and should be checked against the target platform preview.
- Put a short, large hook near the top of the safe area when it helps the story. Use a bold condensed display style as a starting point, not a mandatory font or a repeated title card.
- If the scene uses lower captions instead of the default avatar speech bubble, use short 1–3 word bursts with white text and a restrained yellow keyword highlight. Keep them above the bottom danger zone and away from the avatar's face and explanatory graphic.
- Let the presenter extend into reserved overlay space when needed for framing, but keep the face and other essential details visible. Reels controls must not cover the important subject, text, or action.

## Model recommendations

| Environment | Recommended for best results | Minimum recommended |
| --- | --- | --- |
| Codex | Astra | Sol |
| Claude Code | Opus | Sonnet |

These are project recommendations for story planning, art direction, animation authoring, and visual correction. The user chooses a model through the host chat environment. Continue with the active model and retain visual review as the quality gate. Rendering runs locally through AIVEE; no model identifier belongs in render commands or the creator profile.

## Compose the explanation

- Make the subject large enough to understand on the target screen. Give diagrams, product interfaces, and illustrations a substantial visual area. Avoid a thin strip of tiny graphics surrounded by empty space.
- Use a clear hierarchy: subject first, presenter as guide, captions as support. Keep labels legible and clear of the avatar, subtitles, and platform controls throughout their motion.
- Design each visual change around the spoken idea. Draw a connection when a relationship is introduced; move a contribution through review when that process is explained; assemble a tool from earlier pieces when describing shared foundations.
- For a progressive build, preserve useful prior objects, then reframe, transform, or connect them. Keep the idea visible until the next meaningful state takes over. A completed diagram should not disappear while the narrator is still explaining it.
- Choose a faithful walkthrough for product explanations. A progressive diagram is an available technique, not a mandatory format.
- Use coordinated easing and restrained camera movement. Reserve overshoot for objects whose action benefits from it. Set SVG pivots deliberately; use `svgOrigin` for absolute SVG coordinates. Moving markers must follow their actual paths.
- Keep captions in short, readable phrases with word timing. Allow enough spacing for highlights; animated word scaling must not collide with adjacent words.
- Keep source art and animation original. Reference videos inform pacing, visual hierarchy, and motion intent; do not copy their artwork or compositions.

## Native AIVEE composition route

Studio's `visual_cues` and PNG layer manifests support preset staged entrances. When the storyboard needs expressive motion, author a project-specific AIVEE composition using its existing HTML/SVG and GSAP support. Merely staggering parts of a finished diagram does not fulfill object travel, transformations, or drawn-path choreography. Use `python <plugin-root>/scripts/explainer.py engine -- ...` to invoke the managed AIVEE CLI without relying on a repository checkout being on `PATH`.

1. Create a new AIVEE project or a separate copy of the prior editable project. Preserve source narration, avatar artwork, approved avatar timing, and existing outputs. Give the new project its own metadata and output filename.
2. Author the visual scene in the AIVEE project's `index.html`, using local assets and the project's GSAP dependency. Build original SVG or HTML objects as independently addressable elements with stable IDs. Use a paused GSAP timeline registered as `window.__timelines.root`, with the root's dimensions and duration matching the AIVEE project.
3. Keep time deterministic. Animate from narration timestamps; avoid CSS animation loops, wall-clock timers, and unseeded randomness. Include every scene's initial state so seeking directly to a later time produces the correct frame.
4. Mount the approved avatar states using their existing timing. Add the narration with a stable media ID, source path, start time, and duration. Reuse reviewed word timestamps for captions. Keep visual changes within the approved story beats; obtain approval if the narrative or storyboard meaning changes.
5. Run `python <plugin-root>/scripts/explainer.py engine -- lint <engine-project>`. Resolve errors and actionable warnings before rendering. Inspect browser frames at cue boundaries and during the transitions, including a direct seek into later scenes.
6. Render through AIVEE with `python <plugin-root>/scripts/explainer.py engine -- render <engine-project> <new-output.mp4> standard`. Use the host's configured local browser when needed. This route renders the authored composition; `timeline render` generates its HTML from timeline data and can replace a hand-authored `index.html`.
7. Review actual encoded frames and transitions, then check media dimensions, frame rate, duration, and narration alignment. Deliver the MP4 and editable AIVEE project alongside the Studio project. Keep any topic-specific builder or authoring instructions with that project.

The automatic Studio cue renderer remains a simpler route. Native compositions are authored for the film; this guide does not imply that the generic CLI automatically supplies the approved Reel's choreography.

## Review before delivery

Review representative opening, middle, and closing frames, plus consecutive samples from each important transition. Confirm that objects move continuously, the visual states develop coherently, and there are no unintended gaps, jumps, overlaps, detached paths, or clipped labels. Verify the final encoded file against the authored composition; a still contact sheet alone cannot establish fluid motion.

Confirm that narration is present and aligned and that lip sync and blinks remain intact. Preserve previous renders for comparison. Only call the film rendered after an output file exists and its media checks pass. Report remaining visual review or validation gaps without claiming that a tool choice or model guarantees reference-level quality.
