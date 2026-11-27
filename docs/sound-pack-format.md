# Sound Pack Format

Explainer Studio sound packs use `format_version: 1`. A pack is a folder of short audio files plus a manifest that maps cue roles to those files. Packs are installed in the AIVEE Explainer library, in `Sound Packs` next to `Avatar Packs`.

```text
manifest.json
README.md
LICENSE
whoosh.wav
pop.wav
click.wav
ding.wav
```

The default pack, `default-tones`, is synthesized when it is installed. Its tones are original generated audio under CC0-1.0, so the repository does not ship third-party recordings.

`manifest.json` is the machine-readable source of truth:

```json
{
  "format_version": 1,
  "id": "default-tones",
  "name": "Default Tones",
  "version": "1.0.0",
  "creator": "Explainer Studio",
  "license": "CC0-1.0",
  "license_file": "LICENSE",
  "attribution": "Synthesized tones dedicated to the public domain.",
  "roles": {
    "whoosh": {"file": "whoosh.wav"},
    "pop": {"file": "pop.wav"},
    "click": {"file": "click.wav"},
    "ding": {"file": "ding.wav"}
  }
}
```

Role names use lowercase letters, digits, and hyphens. Each `file` is a path inside the pack to a `.wav`, `.mp3`, `.ogg`, `.flac`, `.m4a`, `.aac`, or `.aiff` file. A role can also record `license`, `license_version`, `license_url`, `attribution`, `creator`, `creator_url`, `source`, `source_id`, `title`, `landing_url`, and `query`. Those fields are required bookkeeping when the file comes from another recording.

`README.md` describes the pack. `LICENSE`, or the file named by `license_file`, states the rights for the pack as a whole. A role's own license and attribution override that general statement for that file.

The cue generator maps timeline events to roles:

| Event | Default role |
|---|---|
| Scene change | `whoosh` |
| Transition | `whoosh` |
| Element, badge, or step appearance | `pop` |
| Click or typing | `click` |

`ding` is available for cues you add or for a mapping override. A mapping file can replace any of these roles and the default gain or fade for a role:

```json
{
  "events": {"badge": "ding"},
  "gainDb": {"ding": -8},
  "fadeOutMs": {"ding": 120}
}
```

`explainer sfx-cues <project>` writes `studio-data/explainer/sfx-cues.json`. Edit `at`, `gainDb`, `fadeInMs`, `fadeOutMs`, `role`, or `file` before rendering. `at` is seconds, or an object with `seconds` or `frame`. The command will not replace an existing cue list unless you pass `--force`.

`explainer sound-pack-search --query <words>` queries the Openverse audio API and keeps Creative Commons results. `explainer sound-pack-add <pack> <role> --query <words>` downloads one of those results into the pack and stores its license and attribution. Both commands need a network; cue generation and the default pack do not.
