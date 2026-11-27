# Changelog

All notable changes to Explainer Studio are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]


## [0.3.1] - 2026-11-27

### Changed

- fix render crash and package safe-check runner (#70)

## [0.3.0] - 2026-11-22

### Added

- export timed sprites to AIVEE (#62)
- initialize portrait Reel projects (#61)
- add editable animated scene starter (#60)
- save reusable caption presets in profile (#59)
- derive project colors from brand images (#58)
- guide recognition with project scripts (#57)
- export stills at requested timestamps (#56)
- add render flicker and safe-zone checks (#55)
- add custom HTML scene compositions (#54)
- add a status command (#53)
- add json output with next steps (#51)

### Changed

- sync dev metadata to v0.2.1 (#63)

## [0.2.1] - 2026-11-22

### Changed

- install the fake AIVEE where npm root -g looks (#52)
- smooth amplitude lip-sync mouth states (#49)
- keep the portrait bubble off the visual (#45)
- allow a draft preview before approval (#36)
- trim headlines on phrase boundaries (#35)
- detect a symlinked managed venv (#33)

## [0.2.0] - 2026-11-18

### Added

- add provider voiceover workflows
- publish v1 Waren and Emo avatar packs (#17)
- standardize layered avatar packs (#15)

### Changed

- reuse assets and remove dead validation
- adopt GPLv3 for Studio
- clarify Codex and Claude Code setup (#24)
- use shared global AIVEE CLI (#23)
- make failed retimes resumable
- move free packs into library (#20)
- use AIVEE-owned projects and assets (#18)
- align avatar guide and document AIVEE dependency (#16)
- align safe-area guidance and validation
- make Emo the default presenter

## [0.1.0] - 2026-11-11

### Added

- install AIVEE with Studio and render through CLI
- add Waren sample avatar pack
- add chat-first explainer studio plugin (#1)

### Changed

- pin release-build-flow-action (#10)
- harden AIVEE rendering workflow (#8)
- use generic Engine timelines
- keep short-form content within safe zones
- initialize explainer studio
